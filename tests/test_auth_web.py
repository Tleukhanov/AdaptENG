"""Web-аутентификация: регистрация по email, вход, выход, cookie-сессия."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    settings = Settings(
        jwt_secret="test-secret",
        database_path=os.path.join(tmp, "auth.db"),
        session_cookie_secure=0,
        llm_daily_limit=30,
        api_insecure_auth=0,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_register_creates_user_and_sets_cookie(client: TestClient):
    response = client.post(
        "/api/auth/register",
        json={"email": "Eraly@Test.com", "password": "superpass1", "name": "Eraly"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "eraly@test.com"  # email нормализуется
    assert body["user"]["tg_id"] is None
    assert "adapteng_session" in response.cookies or "adapteng_session" in client.cookies


def test_registered_user_can_call_protected_endpoint(client: TestClient):
    client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "superpass1"},
    )
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "user@example.com"


def test_login_with_wrong_password_is_rejected(client: TestClient):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "superpass1"})
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": "user@example.com", "password": "wrong-one"}
    )
    assert response.status_code == 401


def test_login_works_after_logout(client: TestClient):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "superpass1"})
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": "user@example.com", "password": "superpass1"}
    )
    assert response.status_code == 200
    assert client.get("/api/me").status_code == 200


def test_logout_clears_session(client: TestClient):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "superpass1"})
    assert client.get("/api/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_duplicate_email_is_rejected(client: TestClient):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "superpass1"})
    response = client.post(
        "/api/auth/register", json={"email": "user@example.com", "password": "superpass1"}
    )
    assert response.status_code == 409


async def test_password_is_stored_as_hash_not_plaintext(client: TestClient):
    """В users лежит хеш, а не сам пароль."""
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "superpass1"})
    repo = client.app.state.repo
    user = await repo.get_user_by_email("user@example.com")
    assert user is not None
    account = await repo.get_auth_account(user.id)
    assert account is not None
    assert "superpass1" not in account.password_hash
    assert account.password_hash.startswith("pbkdf2_sha256$")


def test_protected_endpoint_requires_session(client: TestClient):
    assert client.get("/api/progress").status_code == 401
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 401
