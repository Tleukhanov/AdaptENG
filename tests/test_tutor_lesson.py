"""Персональный урок (``mode="lesson"``) наставника.

Проверяем статический первый ход с повтором прошлой ошибки и темой, выбор
темы из запроса/профиля/weak_areas, лимит ходов, итог с заметкой и записью
новых слов в SRS, а также гостевой режим без прогресса. LLM везде подменён
фейком — сеть в тестах не нужна.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from core.tutor import DEFAULT_LESSON_TOPIC
from storage.repo import UserProfile

SECRET = "test-secret-0123456789abcdef0123456789"

LESSON_TURN_JSON = json.dumps(
    {
        "reply": "Nice example! Now let's talk about coffee.",
        "kind": "teach",
        "question": "How do you usually make coffee at home?",
        "correction": None,
        "interests": [],
        "level_signal": "A2",
        "new_words": ["brew — заваривать", "cupping — каппинг"],
        "should_finish": False,
    },
    ensure_ascii=False,
)

TURN_JSON = json.dumps(
    {
        "reply": "Good job!",
        "kind": "ask",
        "question": "What else do you like about it?",
        "correction": None,
        "interests": [],
        "level_signal": "A2",
        "new_words": [],
        "should_finish": False,
    },
    ensure_ascii=False,
)

SUMMARY_JSON = json.dumps(
    {
        "level": "B1",
        "confidence": 0.6,
        "interests": ["кофе"],
        "strengths": ["хорошо отвечает на вопросы"],
        "weaknesses": ["времена глаголов"],
        "recommendation": "Повтори Present Simple и расскажи о кофе вслух.",
        "praise": "Отличный урок — ты говорил уверенно!",
    },
    ensure_ascii=False,
)


class FakeLLM:
    """LLM-фейк: отдаёт заранее заданные ответы и считает вызовы."""

    def __init__(self) -> None:
        self.responses: list[str] = []
        self.calls = 0

    async def chat(self, messages, temperature=None, json_mode=False) -> str:
        self.calls += 1
        assert json_mode is True
        if self.responses:
            return self.responses.pop(0)
        return TURN_JSON


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "jwt_secret": SECRET,
        "database_path": str(tmp_path / "tutor_lesson.db"),
        "session_cookie_secure": 0,
        "api_insecure_auth": 1,
        "llm_daily_limit": 100,
        "api_llm_min_interval_sec": 0.0,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as test_client:
        test_client.app.state.llm = FakeLLM()
        yield test_client


def _start(client: TestClient, *, mode: str = "lesson", topic: str | None = None) -> dict:
    payload: dict = {"mode": mode}
    if topic is not None:
        payload["topic"] = topic
    response = client.post("/api/tutor/session", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _auth(client: TestClient, tg_id: int = 880002) -> int:
    response = client.post(
        "/api/auth/tg",
        json={
            "id": tg_id,
            "first_name": "Тест",
            "username": f"lesson_user_{tg_id}",
            "auth_date": 1_700_000_000,
            "hash": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


async def _profile_with(client: TestClient, user_id: int, **fields) -> None:
    repo = client.app.state.repo
    profile = await repo.get_profile(user_id) or UserProfile(user_id=user_id)
    for key, value in fields.items():
        setattr(profile, key, value)
    await repo.save_profile(profile)


# ---------- старт урока ----------


async def test_lesson_without_topic_starts_static_with_default_topic(client: TestClient):
    data = _start(client)

    assert data["max_turns"] == 9
    assert data["turn_index"] == 1
    assert client.app.state.llm.calls == 0  # первый ход без LLM

    turn = data["turn"]
    assert turn["kind"] == "ask"
    assert turn["question"]
    assert turn["should_finish"] is False
    assert DEFAULT_LESSON_TOPIC in turn["reply"]

    repo = client.app.state.repo
    session = await repo.get_tutor_session(data["session_id"])
    state = json.loads(session.state_json)
    assert session.mode == "lesson"
    assert state["mode"] == "lesson"
    assert state["topic"] == DEFAULT_LESSON_TOPIC
    assert state["phase"] == "teach"  # повтор уже задан первым ходом
    assert 2 <= len(state["plan"]) <= 4
    assert state["new_words"] == []


async def test_lesson_uses_weak_areas_and_interests_for_review(client: TestClient):
    user_id = _auth(client)
    await _profile_with(
        client,
        user_id,
        interests="шахматы, кофе",
        weak_areas="Present Simple, артикли",
        self_level="A2",
    )

    data = _start(client)
    reply = data["turn"]["reply"]

    assert "Present Simple" in reply
    assert "review" in reply.lower()
    assert "шахматы" in reply
    assert data["turn"]["question"]
    assert client.app.state.llm.calls == 0

    repo = client.app.state.repo
    state = json.loads((await repo.get_tutor_session(data["session_id"])).state_json)
    assert state["topic"] == "шахматы"  # тема из профиля
    assert state["weak_areas"][0] == "Present Simple"
    assert "шахматы" in state["interests"]


async def test_lesson_picks_weak_area_from_tracking_when_profile_is_empty(client: TestClient):
    user_id = _auth(client, tg_id=880003)
    repo = client.app.state.repo
    await repo.upsert_weak_area(user_id, "Past Simple", incorrect_increment=2)

    data = _start(client)
    assert "Past Simple" in data["turn"]["reply"]

    state = json.loads((await repo.get_tutor_session(data["session_id"])).state_json)
    assert "Past Simple" in state["weak_areas"]
    assert state["topic"] == "Practising Past Simple"


async def test_lesson_uses_requested_topic(client: TestClient):
    data = _start(client, topic="Coffee around the world")

    assert "Coffee around the world" in data["turn"]["reply"]
    assert data["turn"]["question"]

    repo = client.app.state.repo
    state = json.loads((await repo.get_tutor_session(data["session_id"])).state_json)
    assert state["topic"] == "Coffee around the world"


async def test_guest_lesson_uses_self_level_from_onboarding(client: TestClient):
    onboarding = client.post(
        "/api/guest/profile",
        json={"goal": "general", "minutes": 20, "level": "A1"},
    )
    assert onboarding.status_code == 200, onboarding.text

    data = _start(client)
    assert "Можно простыми фразами" in data["turn"]["reply"]

    repo = client.app.state.repo
    state = json.loads((await repo.get_tutor_session(data["session_id"])).state_json)
    assert state["self_level"] == "A1"


def test_unknown_mode_is_rejected(client: TestClient):
    response = client.post("/api/tutor/session", json={"mode": "exam"})
    assert response.status_code == 422


# ---------- ходы и лимит ----------


async def test_lesson_turn_returns_new_words_and_finish_writes_progress(client: TestClient):
    user_id = _auth(client, tg_id=880004)
    session_id = _start(client, topic="Coffee around the world")["session_id"]

    client.app.state.llm.responses = [LESSON_TURN_JSON, SUMMARY_JSON]

    turn_response = client.post(
        "/api/tutor/turn",
        json={"session_id": session_id, "text": "I drink coffee every morning."},
    )
    assert turn_response.status_code == 200, turn_response.text
    turn = turn_response.json()
    assert turn["turn_index"] == 2
    assert turn["max_turns"] == 9
    assert turn["turn"]["new_words"] == ["brew — заваривать", "cupping — каппинг"]

    finish = client.post("/api/tutor/finish", json={"session_id": session_id})
    assert finish.status_code == 200, finish.text
    data = finish.json()
    assert data["registered"] is True
    assert data["xp"] > 0
    assert data["summary"]["level"] == "B1"

    repo = client.app.state.repo
    word = await repo.get_srs_word(user_id, "brew")
    assert word is not None
    assert word.translation == "заваривать"
    assert await repo.get_srs_word(user_id, "cupping") is not None

    notes = await repo.get_lesson_notes(user_id, limit=10)
    assert len(notes) == 1
    assert notes[0].topic == "Урок: Coffee around the world"
    assert "brew" in notes[0].vocabulary
    assert "cupping" in notes[0].vocabulary


async def test_lesson_does_not_duplicate_existing_srs_words(client: TestClient):
    from storage.repo import SRSWord

    user_id = _auth(client, tg_id=880005)
    repo = client.app.state.repo
    await repo.add_srs_word(
        SRSWord(user_id=user_id, word="brew", translation="заваривать")
    )

    session_id = _start(client, topic="Coffee around the world")["session_id"]
    client.app.state.llm.responses = [LESSON_TURN_JSON, SUMMARY_JSON]
    client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "I drink coffee."}
    )
    finish = client.post("/api/tutor/finish", json={"session_id": session_id})
    assert finish.status_code == 200, finish.text

    words = await repo.get_srs_words(user_id, limit=50)
    assert [word.word for word in words].count("brew") == 1


async def test_lesson_forces_finish_at_ninth_turn(client: TestClient):
    data = _start(client)
    session_id = data["session_id"]
    client.app.state.llm.responses = [TURN_JSON] * 8

    index = data["turn_index"]
    last: dict | None = None
    while index < data["max_turns"]:
        response = client.post(
            "/api/tutor/turn",
            json={"session_id": session_id, "text": "I like coffee and chess."},
        )
        assert response.status_code == 200, response.text
        last = response.json()
        index = last["turn_index"]

    assert index == 9
    assert last is not None and last["should_finish"] is True
    assert last["turn"]["kind"] == "finish"

    overflow = client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "One more."}
    )
    assert overflow.status_code == 409


# ---------- итог гостя ----------


async def test_guest_lesson_finish_returns_summary_without_progress(client: TestClient):
    session_id = _start(client, topic="Coffee around the world")["session_id"]
    client.app.state.llm.responses = [SUMMARY_JSON]

    response = client.post("/api/tutor/finish", json={"session_id": session_id})
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["registered"] is False
    assert data["xp"] == 10
    assert data["summary"]["praise"]

    repo = client.app.state.repo
    cursor = await repo._conn.execute("SELECT COUNT(*) AS cnt FROM lesson_notes")
    assert (await cursor.fetchone())["cnt"] == 0
    cursor = await repo._conn.execute("SELECT COUNT(*) AS cnt FROM user_vocabulary")
    assert (await cursor.fetchone())["cnt"] == 0
