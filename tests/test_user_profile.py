"""API-тесты профиля-памяти и диагностики уровня (Фаза C: онбординг)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from providers.base import LLMProvider

SECRET = "test-secret-0123456789abcdef0123456789"

TASKS_JSON = """{
  "tasks": [
    {"text": "Introduce yourself: name, job, city.", "level_hint": "A1"},
    {"text": "Describe your typical morning.", "level_hint": "A2"},
    {"text": "What did you do last weekend?", "level_hint": "B1"},
    {"text": "Do you prefer working alone or in a team? Why?", "level_hint": "B1"},
    {"text": "Is it better to rent or buy a home? Explain.", "level_hint": "B2"},
    {"text": "Should governments limit private car use? Argue.", "level_hint": "C1"}
  ]
}"""

ASSESSMENT_JSON = """{
  "level": "B1",
  "confidence": 0.72,
  "explanation_ru": "Уверенный бытовой уровень, сложные темы даются трудно.",
  "strengths": ["Present Simple", "Linking words"],
  "weaknesses": ["Present Perfect"],
  "recommendation": "Тренируй перфектные времена."
}"""


class FakeLLM(LLMProvider):
    """Отдаёт заранее заданные ответы по порядку вызовов."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, temperature=None, json_mode=False):
        self.calls += 1
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


class BrokenLLM(LLMProvider):
    """LLM всегда падает — проверяем эвристический фолбэк."""

    async def chat(self, messages, temperature=None, json_mode=False):
        raise RuntimeError("llm is down")


def _make_app(tmp_path, *, llm_daily_limit: int = 10) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_profile_test.db"),
        jwt_secret=SECRET,
        api_insecure_auth=1,
        llm_daily_limit=llm_daily_limit,
    )
    return TestClient(create_app(settings))


def _auth(client: TestClient) -> dict[str, str]:
    payload = {
        "id": 777000222,
        "first_name": "Тест",
        "auth_date": int(time.time()),
        "hash": "",
    }
    token = client.post("/api/auth/tg", json=payload).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_profile_default_is_empty(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        headers = _auth(client)
        response = client.get("/api/me/profile", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "goal": "",
        "interests": [],
        "weak_areas": [],
        "preferred_format": "",
        "notes": "",
        "level": None,
        "character": "",
        "minutes_per_day": 0,
        "self_level": "",
        "has_profile": False,
    }


def test_profile_update_and_read_back(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        headers = _auth(client)
        response = client.put(
            "/api/me/profile",
            headers=headers,
            json={
                "goal": "Работа в IT",
                "interests": ["chess", "travel", ""],
                "level": "b1",
                "preferred_format": "voice",
                "notes": "4 часа в неделю",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["goal"] == "Работа в IT"
        assert data["interests"] == ["chess", "travel"]
        assert data["level"] == "B1"
        assert data["preferred_format"] == "voice"
        assert data["has_profile"] is True

        stored = client.get("/api/me/profile", headers=headers)
        assert stored.json()["interests"] == ["chess", "travel"]
        assert stored.json()["level"] == "B1"

        me = client.get("/api/me", headers=headers)
        assert me.json()["user"]["level"] == "B1"
        assert me.json()["user"]["interests"] == ["chess", "travel"]


def test_profile_update_rejects_bad_level(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        headers = _auth(client)
        response = client.put("/api/me/profile", headers=headers, json={"level": "Z9"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Уровень должен быть A1..C1"


def test_profile_update_rejects_bad_format(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        headers = _auth(client)
        response = client.put(
            "/api/me/profile", headers=headers, json={"preferred_format": "carrier-pigeon"}
        )
    assert response.status_code == 422


def test_profile_requires_auth(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        assert client.get("/api/me/profile").status_code == 401
        assert client.put("/api/me/profile", json={"goal": "x"}).status_code == 401


def test_diagnostic_start_and_finish(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.llm = FakeLLM(TASKS_JSON, ASSESSMENT_JSON)
        headers = _auth(client)
        start = client.post("/api/diagnostic/start", headers=headers)
        assert start.status_code == 200
        tasks = start.json()["tasks"]
        assert len(tasks) == 6
        assert tasks[0]["level_hint"] == "A1"

        finish = client.post(
            "/api/diagnostic/finish",
            headers=headers,
            json={
                "answers": [
                    "My name is Alex, I work in IT.",
                    "I wake up early and make coffee.",
                    "I visited my parents in the countryside.",
                    "I prefer working alone because I focus better.",
                    "Renting gives more freedom, but buying is an investment.",
                    "Governments should limit cars in city centres.",
                ],
                "tasks": tasks,
            },
        )
    assert finish.status_code == 200
    data = finish.json()
    assert data["level"] == "B1"
    assert data["confidence"] == 0.72
    assert "Present Perfect" in data["weaknesses"]


def test_diagnostic_finish_heuristic_when_llm_fails(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        headers = _auth(client)
        client.app.state.llm = FakeLLM(TASKS_JSON)
        tasks = client.post("/api/diagnostic/start", headers=headers)
        tasks_json = tasks.json()["tasks"]
        long_answers = [
            "I think travelling abroad is wonderful although it can be tiring, however I love it, therefore I go somewhere new every year, moreover it teaches me a lot.",
            "My favourite hobby is reading because it relaxes me, however I also enjoy sports, moreover I try to read every evening although I am often very busy.",
            "Last weekend I visited my grandparents in the countryside although the trip was long, however we cooked together therefore it was really worth it.",
        ]
        # ломаем только оценку: лестница уже сгенерирована
        client.app.state.llm = BrokenLLM()
        finish = client.post(
            "/api/diagnostic/finish",
            headers=headers,
            json={"answers": long_answers, "tasks": tasks_json},
        )
    assert finish.status_code == 200
    data = finish.json()
    assert data["level"] == "B2"
    assert data["confidence"] == 0.3
    assert data["explanation_ru"]


def test_diagnostic_finish_requires_three_answers(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.llm = FakeLLM(ASSESSMENT_JSON)
        headers = _auth(client)
        response = client.post(
            "/api/diagnostic/finish",
            headers=headers,
            json={"answers": ["one", "two", ""]},
        )
    assert response.status_code == 400


def test_diagnostic_without_llm_503(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.llm = None
        headers = _auth(client)
        assert client.post("/api/diagnostic/start", headers=headers).status_code == 503


def test_diagnostic_spends_quota(tmp_path) -> None:
    client = _make_app(tmp_path, llm_daily_limit=1)
    with client:
        client.app.state.llm = FakeLLM(TASKS_JSON)
        headers = _auth(client)
        client.post("/api/diagnostic/start", headers=headers)
        second = client.post("/api/diagnostic/start", headers=headers)
    assert second.status_code == 429
