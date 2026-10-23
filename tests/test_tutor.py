"""«Урок 0» — разговор-знакомство с наставником (backend).

Проверяем контракт API, гостевую cookie, защиту от спама, лимиты, итог для
гостя и залогиненного, устойчивость к битому JSON LLM и миграцию v3.
LLM везде подменён фейком — сеть в тестах не нужна.
"""

from __future__ import annotations

import json
import os
import tempfile

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from core.tutor import TutorService, TutorTurn, parse_turn
from storage.repo import UserProfile
from storage.sqlite import SQLiteRepository, _SQLiteMigrationDB
from storage.migrations import apply_migrations

SECRET = "test-secret-0123456789abcdef0123456789"

GREETING_JSON = json.dumps(
    {
        "reply": "Hi! I'm Alex, your English tutor. Lovely to meet you!",
        "kind": "ask",
        "question": "Tell me a bit about yourself and what you love doing.",
        "correction": None,
        "interests": [],
        "level_signal": "",
        "should_finish": False,
    },
    ensure_ascii=False,
)

TURN_JSON = json.dumps(
    {
        "reply": "That sounds fun! Chess needs a lot of focus.",
        "kind": "correct",
        "question": "How often do you play chess?",
        "correction": {
            "corrected_text": "I play chess every weekend.",
            "issues": [
                {
                    "problem": "Нужно Present Simple с наречием частоты",
                    "suggestion": "I play chess every weekend.",
                }
            ],
        },
        "interests": ["шахматы"],
        "level_signal": "A2",
        "should_finish": False,
    },
    ensure_ascii=False,
)

SUMMARY_JSON = json.dumps(
    {
        "level": "B1",
        "confidence": 0.6,
        "interests": ["шахматы"],
        "strengths": ["хорошо выражает мысли"],
        "weaknesses": ["времена глаголов"],
        "recommendation": "Повтори Present Simple и расскажи о хобби вслух.",
        "praise": "Отличное начало — ты говорил смело и с интересом!",
    },
    ensure_ascii=False,
)


class FakeLLM:
    """LLM-фейк: отдаёт заранее заданные ответы и считает вызовы."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls = 0

    async def chat(self, messages, temperature=None, json_mode=False) -> str:
        self.calls += 1
        assert json_mode is True
        if self.responses:
            return self.responses.pop(0)
        return GREETING_JSON


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "jwt_secret": SECRET,
        "database_path": str(tmp_path / "tutor.db"),
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


def _start(client: TestClient, mode: str = "intro") -> dict:
    response = client.post("/api/tutor/session", json={"mode": mode})
    assert response.status_code == 200, response.text
    return response.json()


def _turn(client: TestClient, session_id: int, text: str = "I like chess.") -> dict:
    return client.post("/api/tutor/turn", json={"session_id": session_id, "text": text}).json()


def _auth(client: TestClient) -> int:
    response = client.post(
        "/api/auth/tg",
        json={
            "id": 880001,
            "first_name": "Тест",
            "username": "tutor_user",
            "auth_date": 1_700_000_000,
            "hash": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


# ---------- старт сессии и cookie ----------


async def test_guest_start_session_sets_cookie_and_first_turn(client: TestClient):
    response = client.post("/api/tutor/session", json={"mode": "intro"})
    assert response.status_code == 200
    data = response.json()

    assert data["session_id"] > 0
    assert data["turn_index"] == 1
    assert data["max_turns"] == 7
    turn = data["turn"]
    assert turn["reply"]
    assert turn["question"]
    assert turn["kind"] in {"ask", "teach", "praise"}
    assert turn["should_finish"] is False
    assert turn["correction"] is None

    header = response.headers.get("set-cookie", "")
    assert "adapteng_tutor=" in header
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert "Max-Age=2592000" in header  # 30 дней
    assert "Secure" not in header  # session_cookie_secure=0

    repo = client.app.state.repo
    session = await repo.get_tutor_session(data["session_id"])
    assert session is not None
    assert session.status == "active"
    assert session.user_id is None
    assert session.guest_token and len(session.guest_token) == 32
    assert all(char in "0123456789abcdef" for char in session.guest_token)


async def test_guest_second_start_returns_same_session(client: TestClient):
    first = _start(client)
    calls_after_first = client.app.state.llm.calls

    second = _start(client)
    assert second["session_id"] == first["session_id"]
    assert second["turn_index"] == first["turn_index"]
    assert second["turn"]["reply"] == first["turn"]["reply"]
    # LLM повторно не звали — защита от спама повторными нажатиями.
    assert client.app.state.llm.calls == calls_after_first

    repo = client.app.state.repo
    active = await repo.get_active_tutor_session(
        guest_token=(await repo.get_tutor_session(first["session_id"])).guest_token
    )
    assert active is not None and active.id == first["session_id"]


# ---------- ходы и валидация ----------


async def test_turn_on_foreign_session_is_404(tmp_path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as owner:
        owner.app.state.llm = FakeLLM([GREETING_JSON])
        owner_session = _start(owner)

        with TestClient(create_app(settings)) as stranger:
            stranger.app.state.llm = FakeLLM([GREETING_JSON])
            _start(stranger)  # у «чужака» своя гостевая cookie
            response = stranger.post(
                "/api/tutor/turn",
                json={"session_id": owner_session["session_id"], "text": "Hello"},
            )
    assert response.status_code == 404


async def test_turn_text_validation(client: TestClient):
    session_id = _start(client)["session_id"]

    too_long = client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "x" * 601}
    )
    assert too_long.status_code == 422

    empty = client.post("/api/tutor/turn", json={"session_id": session_id, "text": ""})
    assert empty.status_code == 422

    blank = client.post("/api/tutor/turn", json={"session_id": session_id, "text": "   "})
    assert blank.status_code == 422


async def test_turn_is_saved_and_returns_turn_data(client: TestClient):
    session_id = _start(client)["session_id"]
    client.app.state.llm.responses = [TURN_JSON]

    response = client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "I play chess every weekend."}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["turn_index"] == 2
    assert data["should_finish"] is False
    assert data["turn"]["kind"] == "correct"
    assert data["turn"]["correction"]["issues"][0]["problem"]

    repo = client.app.state.repo
    session = await repo.get_tutor_session(session_id)
    state = json.loads(session.state_json)
    assert state["turn_index"] == 2
    assert state["interests"] == ["шахматы"]
    assert state["level_signals"] == ["A2"]
    assert state["asked"]
    assert [item["role"] for item in state["turns"]] == ["tutor", "student", "tutor"]


async def test_max_turns_returns_409(client: TestClient):
    data = _start(client)
    session_id = data["session_id"]
    client.app.state.llm.responses = [TURN_JSON] * 10

    index = data["turn_index"]
    last = None
    while index < data["max_turns"]:
        response = client.post(
            "/api/tutor/turn",
            json={"session_id": session_id, "text": "I like chess and football."},
        )
        assert response.status_code == 200, response.text
        last = response.json()
        index = last["turn_index"]

    assert index == data["max_turns"]
    assert last is not None and last["should_finish"] is True

    overflow = client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "One more answer."}
    )
    assert overflow.status_code == 409


# ---------- устойчивость к LLM ----------


async def test_broken_json_from_llm_is_502_and_session_stays_active(client: TestClient):
    session_id = _start(client)["session_id"]
    client.app.state.llm.responses = ["I am not JSON, sorry", TURN_JSON]

    broken = client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "Hello there!"}
    )
    assert broken.status_code == 502
    assert broken.json()["detail"]

    repo = client.app.state.repo
    session = await repo.get_tutor_session(session_id)
    assert session.status == "active"
    assert json.loads(session.state_json)["turn_index"] == 1  # ход не записался

    retry = client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "Hello there!"}
    )
    assert retry.status_code == 200
    assert retry.json()["turn_index"] == 2


async def test_llm_exception_is_502_and_session_stays_active(client: TestClient):
    session_id = _start(client)["session_id"]

    class BrokenLLM:
        async def chat(self, messages, temperature=None, json_mode=False):
            raise TimeoutError("LLM timeout")

    client.app.state.llm = BrokenLLM()
    response = client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "Hello!"}
    )
    assert response.status_code == 502

    repo = client.app.state.repo
    session = await repo.get_tutor_session(session_id)
    assert session.status == "active"


# ---------- итог: гость ----------


async def test_finish_as_guest_returns_summary_without_progress(client: TestClient):
    session_id = _start(client)["session_id"]
    client.app.state.llm.responses = [TURN_JSON, SUMMARY_JSON]

    client.post("/api/tutor/turn", json={"session_id": session_id, "text": "I love chess."})
    response = client.post("/api/tutor/finish", json={"session_id": session_id})
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["registered"] is False
    assert data["turns"] == 2
    assert data["xp"] == 10  # показываем «заработал бы», но не пишем
    assert data["streak_days"] == 1
    summary = data["summary"]
    assert summary["level"] == "B1"
    assert summary["confidence"] == pytest.approx(0.6)
    assert summary["interests"] == ["шахматы"]
    assert summary["matches_self_level"] is False  # самооценки у гостя нет
    assert summary["praise"]
    assert summary["recommendation"]

    repo = client.app.state.repo
    session = await repo.get_tutor_session(session_id)
    assert session.status == "finished"

    cursor = await repo._conn.execute("SELECT COUNT(*) AS cnt FROM lesson_notes")
    row = await cursor.fetchone()
    assert row["cnt"] == 0
    cursor = await repo._conn.execute("SELECT COUNT(*) AS cnt FROM messages")
    row = await cursor.fetchone()
    assert row["cnt"] == 0


async def test_finish_twice_returns_409(client: TestClient):
    session_id = _start(client)["session_id"]
    client.app.state.llm.responses = [SUMMARY_JSON]
    assert client.post("/api/tutor/finish", json={"session_id": session_id}).status_code == 200
    again = client.post("/api/tutor/finish", json={"session_id": session_id})
    assert again.status_code == 409


# ---------- итог: залогиненный ----------


async def test_finish_as_registered_user_updates_profile_progress_and_xp(client: TestClient):
    user_id = _auth(client)
    repo = client.app.state.repo

    profile = await repo.get_profile(user_id) or UserProfile(user_id=user_id)
    profile.self_level = "A2"
    profile.interests = "футбол"
    await repo.save_profile(profile)

    session_id = _start(client)["session_id"]
    client.app.state.llm.responses = [TURN_JSON, SUMMARY_JSON]
    client.post(
        "/api/tutor/turn", json={"session_id": session_id, "text": "I play chess on Sundays."}
    )
    response = client.post("/api/tutor/finish", json={"session_id": session_id})
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["registered"] is True
    assert data["xp"] > 0
    assert data["streak_days"] >= 1
    assert data["summary"]["level"] == "B1"
    assert data["summary"]["matches_self_level"] is False  # A2 -> B1
    assert data["summary"]["interests"] == ["шахматы"]

    updated_profile = await repo.get_profile(user_id)
    assert updated_profile is not None
    assert "футбол" in updated_profile.interests
    assert "шахматы" in updated_profile.interests

    user = await repo.get_user(user_id)
    assert user.level == "B1"

    notes = await repo.get_lesson_notes(user_id, limit=10)
    assert len(notes) == 1
    assert notes[0].topic == "Урок 0: знакомство"
    assert notes[0].recommendation
    assert notes[0].mistakes  # из corrections

    events = await repo.get_events(user_id, "tutor_session_finished")
    assert len(events) == 1
    started = await repo.get_events(user_id, "tutor_session_started")
    assert len(started) == 1
    turns = await repo.get_events(user_id, "tutor_turn")
    assert len(turns) == 1


async def test_registered_second_start_returns_same_active_session(client: TestClient):
    _auth(client)
    first = _start(client)
    calls = client.app.state.llm.calls
    second = _start(client)
    assert second["session_id"] == first["session_id"]
    assert client.app.state.llm.calls == calls


# ---------- миграция v3 ----------


async def test_migration_v3_creates_tutor_sessions_on_old_schema(tmp_path):
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
        CREATE TABLE user_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            goal TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            weak_areas TEXT NOT NULL DEFAULT '',
            preferred_format TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            character TEXT NOT NULL DEFAULT '',
            minutes_per_day INTEGER NOT NULL DEFAULT 0,
            self_level TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        INSERT INTO users (id, created_at) VALUES (1, '2025-01-01T00:00:00+00:00');
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_migrations VALUES (1, 'users_email_password', '2025-01-01T00:00:00+00:00');
        INSERT INTO schema_migrations VALUES (2, 'user_profiles_minutes_self_level', '2025-01-01T00:00:00+00:00');
        """
    )
    cursor = await conn.execute("SELECT name FROM sqlite_master WHERE name = 'tutor_sessions'")
    assert await cursor.fetchone() is None
    await conn.commit()

    applied = await apply_migrations(_SQLiteMigrationDB(conn))
    # v3 создаёт tutor_sessions, v4 добавляет users.email_verified_at.
    assert applied == [3, 4]

    cursor = await conn.execute("PRAGMA table_info(tutor_sessions)")
    columns = {row["name"] for row in await cursor.fetchall()}
    assert {
        "id",
        "user_id",
        "guest_token",
        "character",
        "mode",
        "state_json",
        "status",
        "created_at",
        "updated_at",
    } <= columns

    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_tutor%'"
    )
    indexes = {row["name"] for row in await cursor.fetchall()}
    assert indexes == {"idx_tutor_user", "idx_tutor_guest"}

    cursor = await conn.execute("SELECT name FROM schema_migrations WHERE version = 3")
    row = await cursor.fetchone()
    assert row is not None and row["name"] == "tutor_sessions"

    # Повторный прогон идемпотентен.
    assert await apply_migrations(_SQLiteMigrationDB(conn)) == []

    cursor = await conn.execute("SELECT COUNT(*) AS cnt FROM users")
    assert (await cursor.fetchone())["cnt"] == 1
    await conn.close()

    # Репозиторий поверх старой базы тоже поднимается и умеет урок 0.
    repo = SQLiteRepository(db_path)
    await repo.connect()
    try:
        session = await repo.create_tutor_session(guest_token="a" * 32, state_json="{}")
        assert session.id > 0
        assert (await repo.get_tutor_session(session.id)).guest_token == "a" * 32
        await repo.finish_tutor_session(session.id)
        assert (await repo.get_active_tutor_session(guest_token="a" * 32)) is None
    finally:
        await repo.close()


# ---------- core: парсер и нормализация ----------


def test_parse_turn_tolerates_fences_and_bad_json():
    fenced = "```json\n" + TURN_JSON + "\n```"
    turn = parse_turn(fenced)
    assert turn is not None
    assert turn.question == "How often do you play chess?"
    assert turn.level_signal == "A2"
    assert turn.correction is not None and turn.correction.issues

    assert parse_turn("not json at all") is None
    assert parse_turn('{"reply": ""}') is None


def test_service_forces_finish_on_last_turn():
    service = TutorService(max_turns=7, min_turns=4)
    state = {"turn_index": 6, "max_turns": 7}
    turn = service._normalize(TutorTurn(reply="Nice!", question="And you?"), state)
    assert turn.should_finish is True
    assert turn.kind == "finish"

    early = service._normalize(TutorTurn(reply="Nice!", question="And you?"), {"turn_index": 1})
    assert early.should_finish is False

    # Приветствие + 3 ответа — ещё рано заканчивать (минимум 5 ходов).
    too_early = service._normalize(TutorTurn(reply="Nice!", should_finish=True), {"turn_index": 3})
    assert too_early.should_finish is False
    assert too_early.kind == "ask"

    # Пятый ход уже может завершать урок.
    allowed = service._normalize(TutorTurn(reply="Nice!", should_finish=True), {"turn_index": 4})
    assert allowed.should_finish is True
    assert allowed.kind == "finish"


# ---------- первый ход без LLM + фолбэк моделей ----------


def test_first_turn_is_static_and_asks_about_hobbies() -> None:
    """Первый ход не зовёт LLM: сессия стартует мгновенно даже при 429 у провайдера."""
    from core.tutor import first_turn

    turn = first_turn("default", "A1")
    assert turn.kind == "ask"
    assert turn.question
    assert "yourself" in turn.reply.lower()
    assert turn.should_finish is False


def test_first_turn_language_depends_on_self_level() -> None:
    from core.tutor import first_turn

    simple = first_turn("default", "A1")
    advanced = first_turn("default", "B2")
    assert "Можно простыми фразами" in simple.reply
    assert "Можно простыми фразами" not in advanced.reply
    assert advanced.level_signal == "B2"


def test_llm_provider_falls_back_to_second_model(monkeypatch) -> None:
    """429 на основной модели → сразу пробуем запасную (без ожидания backoff)."""
    import asyncio
    from types import SimpleNamespace

    from providers.llm_openai import OpenAIChatProvider

    provider = OpenAIChatProvider(
        base_url="https://example.com/v1",
        api_key="k",
        model="primary",
        fallback_models=("backup",),
        retries=1,
        backoff=(0.0,),
        timeout=5.0,
        total_budget=10.0,
    )
    seen: list[str] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            seen.append(kwargs["model"])
            if kwargs["model"] == "primary":
                raise RuntimeError("429 rate limited")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" fallback "))])

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    # RuntimeError с текстом 429 не считается retryable по типу — подменяем
    # проверку, чтобы тест проверял именно фолбэк по ретраибельной ошибке.
    import providers.llm_openai as mod

    monkeypatch.setattr(mod, "_is_retryable", lambda exc: True)

    result = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    assert result == "fallback"
    assert seen == ["primary", "backup"]
