"""Тесты метрик обучения и воронки (core/learning_metrics.py + api)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from core.learning_metrics import (
    TurnSample,
    UserLearningData,
    WordSample,
    learning_report,
)
from storage.repo import SRSWord

SECRET = "test-secret-0123456789abcdef0123456789"


def _app(tmp_path, *, admin_tg_id: int = 0) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "analytics_test.db"),
        jwt_secret=SECRET,
        api_insecure_auth=1,
        llm_daily_limit=0,
        admin_tg_id=admin_tg_id,
    )
    return TestClient(create_app(settings))


def _token(client: TestClient, tg_id: int) -> str:
    return client.post(
        "/api/auth/tg",
        json={
            "id": tg_id,
            "first_name": "T",
            "auth_date": int(time.time()),
            "hash": "",
        },
    ).json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- чистая логика отчёта ----------


def test_report_counts_and_accuracy() -> None:
    now = datetime.now(timezone.utc)
    data = UserLearningData(user_id=1)
    data.turns = [
        TurnSample(at=now - timedelta(days=10), correct=True),
        TurnSample(at=now - timedelta(days=9), correct=False),
        TurnSample(at=now - timedelta(days=2), correct=True),
        TurnSample(at=now - timedelta(days=1), correct=True),
    ]
    report = learning_report(data)
    assert report["totals"]["turns"] == 4
    assert report["totals"]["correct"] == 3
    assert report["totals"]["accuracy"] == 75.0
    # неделя: только 2 последние реплики, обе верные
    assert report["trend"]["week"]["turns"] == 2
    assert report["trend"]["week"]["accuracy"] == 100.0


def test_report_trend_delta_shows_growth() -> None:
    now = datetime.now(timezone.utc)
    data = UserLearningData(user_id=1)
    data.turns = [TurnSample(at=now - timedelta(days=9, hours=i), correct=False) for i in range(4)]
    data.turns += [TurnSample(at=now - timedelta(days=1, hours=i), correct=True) for i in range(4)]
    report = learning_report(data)
    delta = report["trend"]["week"]["delta"]
    assert delta == 100.0
    assert "выросла" in report["insight"]


def test_report_retention_by_interval() -> None:
    data = UserLearningData(user_id=1)
    data.words = [
        WordSample(None, None, interval_days=1, ease=2.5, reviews=1),
        WordSample(None, None, interval_days=7, ease=2.6, reviews=2),
        WordSample(None, None, interval_days=30, ease=2.7, reviews=4),
        WordSample(None, None, interval_days=0, ease=2.0, reviews=0),
    ]
    report = learning_report(data)
    assert report["retention"]["day1"]["words"] == 3
    assert report["retention"]["day1"]["percent"] == 75.0
    assert report["retention"]["day7"]["words"] == 2
    assert report["retention"]["day30"]["words"] == 1
    assert report["retention"]["day30"]["percent"] == 25.0


def test_report_predicts_level_after_enough_data() -> None:
    now = datetime.now(timezone.utc)
    data = UserLearningData(user_id=1)
    data.turns = [TurnSample(at=now, correct=True) for _ in range(20)]
    report = learning_report(data)
    assert report["level"]["predicted"] is not None
    empty = learning_report(UserLearningData(user_id=2))
    assert empty["level"]["predicted"] is None


def test_report_growth_diagnostic_to_current() -> None:
    data = UserLearningData(user_id=1, diagnostic_level="A2", level="B1")
    report = learning_report(data)
    assert report["level"]["growth"]["steps"] == 1


# ---------- API ----------


def test_analytics_me_requires_auth(tmp_path) -> None:
    client = _app(tmp_path)
    with client:
        assert client.get("/api/analytics/me").status_code == 401


def test_analytics_me_returns_report(tmp_path) -> None:
    client = _app(tmp_path)
    with client:
        headers = _headers(_token(client, 4242))
        response = client.get("/api/analytics/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert set(data) >= {"totals", "trend", "retention", "level", "weak_areas", "insight"}
    assert data["totals"]["turns"] == 0
    assert data["totals"]["accuracy"] == 0.0


async def test_analytics_me_counts_real_turns_and_words(tmp_path) -> None:
    client = _app(tmp_path)
    with client:
        headers = _headers(_token(client, 5151))
        repo = client.app.state.repo
        user = await repo.get_or_create_user(5151)

        await repo.add_user_message(user.id, "Hello there", is_correct=True)
        await repo.add_user_message(user.id, "Yesterday I goed home", is_correct=False)
        past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        for word in ("brew", "roast"):
            await repo.add_srs_word(
                SRSWord(
                    user_id=user.id,
                    word=word,
                    translation="x",
                    example="e",
                    next_review=past,
                    interval_days=7,
                    ease_factor=2.5,
                    created_at=past,
                )
            )

        data = client.get("/api/analytics/me", headers=headers).json()

    assert data["totals"]["turns"] == 2
    assert data["totals"]["correct"] == 1
    assert data["totals"]["accuracy"] == 50.0
    assert data["totals"]["words"] == 2
    assert data["retention"]["day7"]["percent"] == 100.0


def test_admin_analytics_requires_admin(tmp_path) -> None:
    client = _app(tmp_path, admin_tg_id=999)
    with client:
        other = _headers(_token(client, 111))
        assert client.get("/api/admin/analytics", headers=other).status_code == 403


def test_admin_analytics_ok_for_admin(tmp_path) -> None:
    client = _app(tmp_path, admin_tg_id=999)
    with client:
        headers = _headers(_token(client, 999))
        response = client.get("/api/admin/analytics", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "funnel" in data
    assert "cohorts" in data
    assert data["funnel"]["total_users"] >= 1
    assert set(data["funnel"]["conversion"]) >= {"register_to_onboarding", "onboarding_to_lesson"}


def test_admin_analytics_disabled_without_admin_id(tmp_path) -> None:
    client = _app(tmp_path, admin_tg_id=0)
    with client:
        headers = _headers(_token(client, 1))
        assert client.get("/api/admin/analytics", headers=headers).status_code == 404


async def test_profile_update_tracks_onboarding_event(tmp_path) -> None:
    """Заполнение профиля через api порождает событие воронки."""
    client = _app(tmp_path)
    with client:
        headers = _headers(_token(client, 606))
        response = client.put(
            "/api/me/profile",
            headers=headers,
            json={"goal": "Работа", "interests": ["chess"], "level": "B1"},
        )
        assert response.status_code == 200
        repo = client.app.state.repo
        user = await repo.get_or_create_user(606)
        events = await repo.get_events(user.id, "onboarding_completed")
    assert len(events) == 1