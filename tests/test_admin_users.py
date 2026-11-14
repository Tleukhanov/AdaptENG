"""Админ-панель: список пользователей, подписки, блокировки (FastAPI + SQLite)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "superpass1"
USER_EMAIL = "learner@example.com"
USER_PASSWORD = "superpass1"


@pytest.fixture()
def clients(tmp_path):
    settings = Settings(
        jwt_secret="test-secret-admin-0123456789abcdef0123456789",
        database_path=str(tmp_path / "admin.db"),
        session_cookie_secure=0,
        llm_daily_limit=30,
        api_insecure_auth=0,
        admin_emails=ADMIN_EMAIL,
    )
    app = create_app(settings)
    with TestClient(app) as admin:
        response = admin.post(
            "/api/auth/register",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "name": "Admin"},
        )
        assert response.status_code == 200
        with TestClient(app) as learner:
            response = learner.post(
                "/api/auth/register",
                json={"email": USER_EMAIL, "password": USER_PASSWORD, "name": "Learner"},
            )
            assert response.status_code == 200
            yield admin, learner


def _learner(clients) -> dict:
    admin, _ = clients
    response = admin.get("/api/admin/users", params={"search": USER_EMAIL})
    assert response.status_code == 200
    users = response.json()["users"]
    assert len(users) == 1
    return users[0]


def test_non_admin_gets_403(clients) -> None:
    _, learner = clients
    assert learner.get("/api/admin/users").status_code == 403


def test_admin_list_uses_real_user_fields(clients) -> None:
    admin, _ = clients
    response = admin.get("/api/admin/users")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    item = body["users"][0]
    # Поля, которых нет у UserRow, не должны появляться в ответе.
    assert "character" not in item
    assert "interests" not in item
    assert "llm_daily_limit" not in item
    assert "quota_left" not in item
    for field in ("id", "email", "level", "blocked", "subscription_status", "created_at"):
        assert field in item


def test_grant_subscription_activates_status(clients) -> None:
    admin, _ = clients
    learner = _learner(clients)

    response = admin.put(
        f"/api/admin/users/{learner['id']}/subscription", json={"plan_days": 7}
    )
    assert response.status_code == 200
    assert response.json()["plan_days"] == 7

    active = admin.get("/api/admin/users", params={"subscription": "active"})
    assert active.status_code == 200
    assert learner["id"] in {user["id"] for user in active.json()["users"]}

    detail = admin.get(f"/api/admin/users/{learner['id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["user"]["subscription_status"] == "active"
    assert payload["subscription"]["plan_days"] == 7
    assert payload["stats"]["total_turns"] == 0


def test_block_and_soft_delete(clients) -> None:
    admin, _ = clients
    learner = _learner(clients)
    url = f"/api/admin/users/{learner['id']}"

    blocked = admin.put(f"{url}/block", json={"blocked": True})
    assert blocked.status_code == 200
    assert admin.get(url).json()["user"]["blocked"] is True

    unblocked = admin.put(f"{url}/block", json={"blocked": False})
    assert unblocked.status_code == 200
    assert admin.get(url).json()["user"]["blocked"] is False

    deleted = admin.delete(url)
    assert deleted.status_code == 200
    assert admin.get(url).json()["user"]["blocked"] is True


def test_admin_can_open_dashboard_for_unknown_user(clients) -> None:
    admin, _ = clients
    assert admin.get("/api/admin/users/99999").status_code == 404


def test_blocked_user_cannot_login(clients) -> None:
    admin, learner = clients
    user = _learner(clients)
    admin.put(f"/api/admin/users/{user['id']}/block", json={"blocked": True})

    learner.post("/api/auth/logout")
    response = learner.post(
        "/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD}
    )
    assert response.status_code == 403
    assert "заблокирован" in response.json()["detail"].lower()
