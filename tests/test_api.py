"""Интеграционные тесты REST API AdaptENG (FastAPI TestClient + SQLite)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from core.tg_auth import sign_login_widget

SECRET = "test-secret-0123456789abcdef0123456789"


def _make_app(tmp_path) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_test.db"),
        jwt_secret=SECRET,
        # insecure-auth: не проверяем подпись виджета, но в тестах ниже есть
        # и «честный» прогон через sign_login_widget.
        api_insecure_auth=1,
        llm_daily_limit=5,
    )
    return TestClient(create_app(settings))


def _bot_token() -> str:
    return "123456:TEST-BOT-TOKEN"


def _tg_user(patch: dict | None = None) -> dict:
    payload: dict = {
        "id": 555000111,
        "first_name": "Тест",
        "last_name": "Юзеров",
        "username": "test_user",
        "auth_date": int(time.time()),
        "photo_url": "https://t.me/photo.png",
    }
    if patch:
        payload.update(patch)
    return payload


def test_health(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_characters_localized_ru_by_default(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        response = client.get("/api/characters")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 6
    first = items[0]
    assert first["id"] == "default"
    assert first["name"] == "Обычный учитель"
    assert first["tagline"]
    assert first["backstory"]
    assert len(first["palette"]) == 2


def test_characters_localized_en(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        response = client.get("/api/characters?lang=en")
    items = response.json()
    assert items[0]["name"] == "Standard Tutor"
    assert items[0]["tagline"]


def test_auth_tg_insecure_creates_user_and_issue_token(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        response = client.post("/api/auth/tg", json=_tg_user())
    assert response.status_code == 200
    data = response.json()
    assert data["token"]
    assert data["user"]["tg_id"] == 555000111
    assert data["user"]["username"] == "test_user"
    assert data["user"]["quota_left"] == 5
    assert data["user"]["quota_total"] == 5


def test_auth_tg_verified_signature(tmp_path) -> None:
    # Честный прогон: подпись валидна — доступ есть даже при insecure=0.
    settings = Settings(
        database_path=str(tmp_path / "adapteng_verify.db"),
        jwt_secret=SECRET,
        api_insecure_auth=0,
        telegram_bot_token=_bot_token(),
        llm_daily_limit=0,
    )
    with TestClient(create_app(settings)) as client:
        user = _tg_user()
        signed = sign_login_widget(_bot_token(), user)
        response = client.post("/api/auth/tg", json=signed)
        assert response.status_code == 200
        assert response.json()["user"]["tg_id"] == user["id"]


def test_auth_tg_rejects_bad_signature(tmp_path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_reject.db"),
        jwt_secret=SECRET,
        api_insecure_auth=0,
        telegram_bot_token=_bot_token(),
    )
    with TestClient(create_app(settings)) as client:
        user = _tg_user()
        signed = sign_login_widget(_bot_token(), user)
        signed["username"] = "evil"
        response = client.post("/api/auth/tg", json=signed)
        assert response.status_code == 401


def test_auth_tg_requires_secret(tmp_path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_nosecret.db"),
        jwt_secret="",
        api_insecure_auth=1,
    )
    with pytest.raises(RuntimeError):
        with TestClient(create_app(settings)):
            pass


def test_me_without_token_401(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        response = client.get("/api/me")
    assert response.status_code == 401


def test_me_with_garbage_token_401(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        response = client.get("/api/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_me_authenticated(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        auth = client.post("/api/auth/tg", json=_tg_user()).json()
        token = auth["token"]
        response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["tg_id"] == 555000111
    assert payload["user"]["level"] is None
    assert payload["user"]["interests"] == []
    assert payload["character"]["id"] == "default"


async def test_me_reports_usage_after_llm_consumption(tmp_path) -> None:
    from datetime import date

    client = _make_app(tmp_path)
    with client:
        token = client.post("/api/auth/tg", json=_tg_user()).json()["token"]
        repo = client.app.state.repo
        row = await repo.get_or_create_user(555000111)
        await repo.increment_llm_usage(row.id, date.today().isoformat(), 2)
        response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["user"]["quota_left"] == 3