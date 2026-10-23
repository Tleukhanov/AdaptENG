"""Подтверждение email: мягкий флоу (не блокирует продукт).

Проверяем: флаг в /api/me и auth-ответах, dev-режим отправки (SMTP_HOST пуст —
ссылка в лог), rate limit повторной отправки, валидные/битые/чужие токены,
идемпотентность подтверждения и миграцию 4 на старой схеме.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time

import aiosqlite
import jwt
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.routers import auth as auth_router
from api.security import create_verify_token
from core.config import Settings
from storage.migrations import apply_migrations
from storage.sqlite import SQLiteRepository, _SQLiteMigrationDB

PASSWORD = "superpass1"


@pytest.fixture(autouse=True)
def _reset_verify_throttle():
    """Троттлинг отправки живёт в памяти процесса — чистим между тестами."""
    auth_router._verify_sent_at.clear()
    yield
    auth_router._verify_sent_at.clear()


def _client(**overrides):
    tmp = tempfile.mkdtemp()
    settings = Settings(
        jwt_secret="test-secret-email-verify",
        database_path=os.path.join(tmp, "email_verify.db"),
        session_cookie_secure=0,
        llm_daily_limit=30,
        smtp_host="",
        **overrides,
    )
    app = create_app(settings)
    return TestClient(app)


@pytest.fixture()
def client():
    with _client() as test_client:
        yield test_client


def _register(test_client: TestClient, email: str = "user@example.com") -> dict:
    response = test_client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _token(client: TestClient, user_id: int) -> str:
    return create_verify_token(client.app.state.settings, user_id)


def test_register_returns_email_verified_false(client: TestClient, caplog):
    with caplog.at_level(logging.INFO):
        body = _register(client)
    assert body["user"]["email_verified"] is False
    assert client.get("/api/me").json()["user"]["email_verified"] is False

    # Регистрация сама просит письмо (best-effort). Без SMTP — dev-режим:
    # ссылка в логе, письмо не отправлено, регистрация успешна.
    messages = [record.getMessage() for record in caplog.records]
    assert any("/api/auth/verify?token=" in message for message in messages)


def test_verify_request_dev_mode_and_rate_limit(client: TestClient, caplog):
    body = _register(client)

    with caplog.at_level(logging.INFO):
        first = client.post("/api/auth/verify/request")
    assert first.status_code == 200
    assert first.json() == {"ok": True, "sent": False, "already_verified": False}

    # dev-режим: ссылка для этого пользователя попала в лог.
    link_messages = [
        record.getMessage()
        for record in caplog.records
        if "/api/auth/verify?token=" in record.getMessage()
    ]
    assert link_messages
    assert body["user"]["email"] in link_messages[-1]

    second = client.post("/api/auth/verify/request")
    assert second.status_code == 429
    payload = second.json()
    assert payload["ok"] is False
    assert 0 < payload["retry_after"] <= 60


def test_verify_request_after_confirmation_is_already_verified(client: TestClient):
    body = _register(client)
    token = _token(client, body["user"]["id"])
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 200

    response = client.post("/api/auth/verify/request")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "sent": False, "already_verified": True}


def test_valid_token_verifies_email_and_me(client: TestClient):
    body = _register(client)
    token = _token(client, body["user"]["id"])

    response = client.post("/api/auth/verify", json={"token": token})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "email_verified": True}
    assert client.get("/api/me").json()["user"]["email_verified"] is True

    # Флаг отдаётся и в ответе login.
    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login", json={"email": "user@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["user"]["email_verified"] is True


async def test_verify_is_idempotent_and_keeps_first_timestamp(client: TestClient):
    body = _register(client)
    token = _token(client, body["user"]["id"])
    repo = client.app.state.repo

    assert client.post("/api/auth/verify", json={"token": token}).status_code == 200
    user = await repo.get_user(body["user"]["id"])
    first_at = user.email_verified_at
    assert first_at

    # Повторное подтверждение — успех (идемпотентно), дата не перезаписывается.
    again = client.post("/api/auth/verify", json={"token": token})
    assert again.status_code == 200
    assert again.json() == {"ok": True, "email_verified": True}
    user = await repo.get_user(body["user"]["id"])
    assert user.email_verified_at == first_at


def test_broken_token_is_rejected(client: TestClient):
    _register(client)
    response = client.post("/api/auth/verify", json={"token": "not-a-jwt"})
    assert response.status_code == 400
    assert "недействительна" in response.json()["detail"]


def test_token_signed_with_foreign_secret_is_rejected(client: TestClient):
    body = _register(client)
    now = int(time.time())
    forged = jwt.encode(
        {
            "sub": str(body["user"]["id"]),
            "purpose": "verify",
            "iat": now,
            "exp": now + 3600,
        },
        "another-secret",
        algorithm="HS256",
    )
    response = client.post("/api/auth/verify", json={"token": forged})
    assert response.status_code == 400


def test_expired_token_is_rejected(client: TestClient):
    body = _register(client)
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": str(body["user"]["id"]),
            "purpose": "verify",
            "iat": now - 7200,
            "exp": now - 3600,
        },
        "test-secret-email-verify",
        algorithm="HS256",
    )
    assert client.post("/api/auth/verify", json={"token": expired}).status_code == 400


def test_verify_token_does_not_work_as_session(client: TestClient):
    body = _register(client)
    token = _token(client, body["user"]["id"])
    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_verify_request_requires_auth():
    with _client() as test_client:
        assert test_client.post("/api/auth/verify/request").status_code == 401


def test_verify_link_redirects_to_webapp():
    with _client(webapp_public_url="https://app.example/") as test_client:
        body = _register(test_client)
        token = _token(test_client, body["user"]["id"])
        response = test_client.get(
            f"/api/auth/verify?token={token}", follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == "https://app.example/verify?status=ok"

        # Битый токен — тот же редирект, но со статусом error.
        bad = test_client.get(
            "/api/auth/verify?token=broken", follow_redirects=False
        )
        assert bad.status_code == 302
        assert bad.headers["location"] == "https://app.example/verify?status=error"


def test_verify_link_without_webapp_url_returns_json(client: TestClient):
    body = _register(client)
    token = _token(client, body["user"]["id"])
    ok = client.get(f"/api/auth/verify?token={token}")
    assert ok.status_code == 200
    assert ok.json() == {"ok": True, "email_verified": True}
    assert client.get("/api/auth/verify?token=broken").status_code == 400


# ---------- миграция v4 ----------


async def test_migration_v4_adds_email_verified_at_on_old_schema(tmp_path):
    db_path = str(tmp_path / "old.db")
    conn = await aiosqlite.connect(db_path)
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
            created_at TEXT NOT NULL,
            email TEXT,
            password_hash TEXT
        );
        INSERT INTO users (id, email, created_at)
        VALUES (1, 'old@example.com', '2025-01-01T00:00:00+00:00');
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_migrations VALUES (1, 'users_email_password', '2025-01-01T00:00:00+00:00');
        INSERT INTO schema_migrations VALUES (2, 'user_profiles_minutes_self_level', '2025-01-01T00:00:00+00:00');
        INSERT INTO schema_migrations VALUES (3, 'tutor_sessions', '2025-01-01T00:00:00+00:00');
        """
    )
    await conn.commit()

    applied = await apply_migrations(_SQLiteMigrationDB(conn))
    # v4 добавляет users.email_verified_at, v5 — users.reminders_enabled.
    assert applied == [4, 5]

    cursor = await conn.execute("PRAGMA table_info(users)")
    columns = {row["name"] for row in await cursor.fetchall()}
    assert "email_verified_at" in columns

    # Старая строка цела, флаг по умолчанию NULL.
    cursor = await conn.execute("SELECT email, email_verified_at FROM users WHERE id = 1")
    row = await cursor.fetchone()
    assert row["email"] == "old@example.com"
    assert row["email_verified_at"] is None

    cursor = await conn.execute("SELECT name FROM schema_migrations WHERE version = 4")
    row = await cursor.fetchone()
    assert row is not None and row["name"] == "users_email_verified_at"

    # Повторный прогон идемпотентен.
    assert await apply_migrations(_SQLiteMigrationDB(conn)) == []
    await conn.close()


async def test_repository_reads_and_sets_email_verified_at(tmp_path):
    db_path = str(tmp_path / "repo.db")
    repo = SQLiteRepository(db_path)
    await repo.connect()
    try:
        user = await repo.create_email_user("new@example.com", "hash")
        assert user.email_verified_at is None

        await repo.set_email_verified(user.id, "2026-01-01T00:00:00+00:00")
        loaded = await repo.get_user(user.id)
        assert loaded is not None
        assert loaded.email_verified_at == "2026-01-01T00:00:00+00:00"

        by_email = await repo.get_user_by_email("new@example.com")
        assert by_email is not None
        assert by_email.email_verified_at == "2026-01-01T00:00:00+00:00"
    finally:
        await repo.close()
