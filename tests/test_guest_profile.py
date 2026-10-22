"""Гостевой онбординг до регистрации: cookie, эндпоинты, перенос в профиль."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from storage.sqlite import SQLiteRepository

VALID_PROFILE = {"goal": "work", "minutes": 20, "level": "B1"}


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    settings = Settings(
        jwt_secret="test-secret",
        database_path=os.path.join(tmp, "guest.db"),
        session_cookie_secure=0,
        llm_daily_limit=30,
        api_insecure_auth=0,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _post_profile(client: TestClient, **overrides) -> None:
    response = client.post("/api/guest/profile", json={**VALID_PROFILE, **overrides})
    assert response.status_code == 200


# ---------- cookie и эндпоинты ----------


def test_post_sets_signed_cookie_and_get_returns_it(client: TestClient):
    response = client.post("/api/guest/profile", json=VALID_PROFILE)
    assert response.status_code == 200
    assert response.json() == {"profile": VALID_PROFILE}

    header = response.headers.get("set-cookie", "")
    assert "adapteng_guest=" in header
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert "Max-Age=2592000" in header  # 30 дней
    assert "Path=/" in header
    assert "Secure" not in header  # в тестах session_cookie_secure=0

    fetched = client.get("/api/guest/profile")
    assert fetched.status_code == 200
    assert fetched.json() == {"profile": VALID_PROFILE}


def test_get_without_cookie_returns_null(client: TestClient):
    response = client.get("/api/guest/profile")
    assert response.status_code == 200
    assert response.json() == {"profile": None}


@pytest.mark.parametrize(
    "payload",
    [
        {"goal": "fun", "minutes": 20, "level": "B1"},
        {"goal": "work", "minutes": 15, "level": "B1"},
        {"goal": "work", "minutes": 20, "level": "C2"},
        {"goal": "", "minutes": 20, "level": "B1"},
    ],
)
def test_post_invalid_values_rejected(client: TestClient, payload: dict):
    response = client.post("/api/guest/profile", json=payload)
    assert response.status_code == 422
    assert "adapteng_guest" not in client.cookies


def test_tampered_cookie_returns_null_without_error(client: TestClient):
    _post_profile(client)
    token = client.cookies.get("adapteng_guest")
    assert token

    client.cookies.set(
        "adapteng_guest",
        token[:-1] + ("0" if token[-1] != "0" else "1"),
        domain="testserver.local",
        path="/",
    )
    response = client.get("/api/guest/profile")
    assert response.status_code == 200
    assert response.json() == {"profile": None}


def test_garbage_cookie_returns_null_without_error(client: TestClient):
    client.cookies.set("adapteng_guest", "not-a-valid-cookie-value")
    response = client.get("/api/guest/profile")
    assert response.status_code == 200
    assert response.json() == {"profile": None}


def test_expired_cookie_returns_null(client: TestClient):
    """Подпись верная, но iat старше TTL — профиль считается протухшим."""
    settings = client.app.state.settings
    payload = {
        **VALID_PROFILE,
        "iat": int(time.time()) - settings.guest_cookie_ttl_days * 86_400 - 60,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    client.cookies.set("adapteng_guest", f"{encoded}.{signature}")

    response = client.get("/api/guest/profile")
    assert response.status_code == 200
    assert response.json() == {"profile": None}


def test_delete_clears_cookie(client: TestClient):
    _post_profile(client)
    response = client.delete("/api/guest/profile")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "adapteng_guest" not in client.cookies
    assert client.get("/api/guest/profile").json() == {"profile": None}


# ---------- регистрация ----------


async def test_register_merges_guest_profile(client: TestClient):
    _post_profile(client)
    response = client.post(
        "/api/auth/register",
        json={"email": "guest@example.com", "password": "superpass1", "name": "Guest"},
    )
    assert response.status_code == 200
    # Гостевая cookie очищена после переноса.
    assert "adapteng_guest" not in client.cookies
    assert client.get("/api/guest/profile").json() == {"profile": None}

    repo = client.app.state.repo
    user = await repo.get_user_by_email("guest@example.com")
    assert user is not None
    profile = await repo.get_profile(user.id)
    assert profile is not None
    assert profile.goal == "Для работы и карьеры"
    assert profile.minutes_per_day == 20
    assert profile.self_level == "B1"

    events = await repo.get_events(user.id, "guest_profile_merged")
    assert events, "событие guest_profile_merged должно записаться"


async def test_register_without_guest_cookie_keeps_profile_empty(client: TestClient):
    response = client.post(
        "/api/auth/register",
        json={"email": "plain@example.com", "password": "superpass1"},
    )
    assert response.status_code == 200

    repo = client.app.state.repo
    user = await repo.get_user_by_email("plain@example.com")
    assert user is not None
    profile = await repo.get_profile(user.id)
    assert profile is None or profile.goal == ""

    me_profile = client.get("/api/me/profile")
    assert me_profile.status_code == 200
    assert me_profile.json()["goal"] == ""


# ---------- миграция 2 ----------


async def test_migration_2_adds_profile_columns_to_old_schema(tmp_path):
    """Старая БД без новых колонок доводится миграцией 2, данные не теряются."""
    db_path = tmp_path / "old.db"
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            level TEXT,
            unlimited INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE user_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            goal TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            weak_areas TEXT NOT NULL DEFAULT '',
            preferred_format TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        INSERT INTO users (id, created_at) VALUES (1, '2025-01-01T00:00:00+00:00');
        INSERT INTO user_profiles (user_id, goal, updated_at)
        VALUES (1, 'Для работы и карьеры', '2025-01-01T00:00:00+00:00');
        """
    )
    cursor = await conn.execute("PRAGMA table_info(user_profiles)")
    old_columns = {row["name"] for row in await cursor.fetchall()}
    assert "minutes_per_day" not in old_columns
    assert "self_level" not in old_columns
    await conn.commit()
    await conn.close()

    repo = SQLiteRepository(str(db_path))
    await repo.connect()
    try:
        cursor = await repo._conn.execute("PRAGMA table_info(user_profiles)")
        columns = {row["name"] for row in await cursor.fetchall()}
        assert {"minutes_per_day", "self_level"} <= columns

        cursor = await repo._conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 2"
        )
        row = await cursor.fetchone()
        assert row is not None and row["name"] == "user_profiles_minutes_self_level"

        profile = await repo.get_profile(1)
        assert profile is not None
        assert profile.goal == "Для работы и карьеры"  # старые данные целы
        assert profile.minutes_per_day == 0
        assert profile.self_level == ""
    finally:
        await repo.close()
