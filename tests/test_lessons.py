import json

import pytest

from bot.lessons import LESSON_STEPS, next_lesson_position
from core.lessons import (
    LESSON_TYPES,
    LessonParseError,
    LessonService,
    VocabWord,
    build_lesson_prompt,
    lesson_content_from_json,
    lesson_content_to_json,
    parse_lesson_response,
    parse_proposals_response,
)
from core.practice import PracticeParseError, parse_practice_response
from providers.base import LLMProvider

VALID_LESSON_JSON = """
```json
{
  "topic": "Travelling",
  "intro": "Let's talk about travelling!",
  "vocabulary": [
    {"word": "luggage", "translation": "багаж", "example": "I packed my luggage yesterday."},
    {"word": "flight", "translation": "перелёт", "example": "The flight was long."}
  ],
  "slides": ["Book flights early.", "Pack light."],
  "grammar": {
    "rule": "Past Simple",
    "explanation_ru": "используется для завершённых действий в прошлом",
    "examples": ["I flew to Spain last year."]
  },
  "tasks": ["What did you pack for your last trip?", "Describe your best holiday."]
}
```
"""


def test_parse_lesson_response():
    content = parse_lesson_response(VALID_LESSON_JSON)
    assert content.topic == "Travelling"
    assert content.intro == "Let's talk about travelling!"
    assert len(content.vocabulary) == 2
    assert content.vocabulary[0].word == "luggage"
    assert content.vocabulary[0].translation == "багаж"
    assert content.slides == ["Book flights early.", "Pack light."]
    assert content.grammar is not None
    assert content.grammar.rule == "Past Simple"
    assert content.grammar.examples == ["I flew to Spain last year."]
    assert len(content.tasks) == 2


def test_parse_lesson_response_missing_fields():
    content = parse_lesson_response('{"topic": "Chess"}')
    assert content.topic == "Chess"
    assert content.vocabulary == []
    assert content.slides == []
    assert content.grammar is None
    assert content.tasks == []
    assert content.lesson_type == "standard"


def test_parse_lesson_response_unknown_type_falls_back_to_standard():
    content = parse_lesson_response('{"topic": "Chess", "lesson_type": "weird"}')
    assert content.lesson_type == "standard"

    content = parse_lesson_response('{"topic": "Chess", "lesson_type": "STORY"}')
    assert content.lesson_type == "story"


def test_parse_lesson_response_invalid_raises():
    with pytest.raises(LessonParseError):
        parse_lesson_response("no json here")


def test_build_prompt_with_topic():
    messages = build_lesson_prompt("Chess")
    assert messages[0]["role"] == "system"
    assert "Chess" in messages[2]["content"]


def test_build_prompt_without_topic():
    messages = build_lesson_prompt(None)
    assert "choice" in messages[2]["content"]


def test_build_prompt_defaults_to_a1_level():
    messages = build_lesson_prompt("Chess")
    assert "beginner (A1)" in messages[0]["content"]


def test_build_prompt_with_level_a1():
    messages = build_lesson_prompt("Chess", level="A1")
    assert "beginner (A1)" in messages[0]["content"]
    assert "simple answers" in messages[0]["content"]


def test_build_prompt_with_level_c1():
    messages = build_lesson_prompt("Chess", level="C1")
    assert "advanced (C1)" in messages[0]["content"]
    assert "argue and explain" in messages[0]["content"]


def test_build_prompt_with_unknown_level_falls_back_to_a1():
    messages = build_lesson_prompt("Chess", level="X9")
    assert "beginner (A1)" in messages[0]["content"]


def test_build_prompt_with_profile():
    messages = build_lesson_prompt(None, profile="Student profile: Interests: chess; Weak areas: Present Perfect.")
    system = messages[0]["content"]
    assert "Interests: chess" in system
    assert "weak areas" in system.lower()


def test_lesson_content_json_roundtrip():
    content = parse_lesson_response(VALID_LESSON_JSON)
    restored = lesson_content_from_json(lesson_content_to_json(content))
    assert restored == content
    assert restored.vocabulary[1].word == "flight"


def test_lesson_content_from_json_invalid_returns_none():
    for raw in ["", "not json", "42", "null", "[1, 2, 3]", '{"topic": "x"} junk', None]:
        assert lesson_content_from_json(raw) is None


def test_lesson_content_from_json_partial_fields_are_safe():
    raw = json.dumps({
        "topic": "Chess",
        "intro": "Play!",
        "vocabulary": [
            {"word": "check", "translation": "шах", "example": "Check!"},
            "junk-string",
            42,
            {"word": "mate", "translation": "мат"},
        ],
        "slides": "not-a-list",
        "grammar": {"rule": "Past Simple", "examples": ["I went.", 5]},
        "tasks": ["ok", {"bad": True}],
        "lesson_type": None,
    })
    content = lesson_content_from_json(raw)
    assert content is not None
    assert content.topic == "Chess"
    assert [w.word for w in content.vocabulary] == ["check", "mate"]
    assert content.vocabulary[1].example == ""  # дефолт у неполного элемента
    assert content.slides == []  # не-список -> пусто
    assert content.tasks == ["ok"]  # битые элементы пропущены
    assert content.grammar is not None
    assert content.grammar.examples == ["I went."]
    assert content.lesson_type == "standard"  # None -> дефолт


def test_lesson_content_from_json_ignores_extra_keys_in_vocab():
    raw = json.dumps({
        "topic": "T",
        "vocabulary": [
            {"word": "w", "translation": "t", "example": "e", "extra": 1, "nested": {"a": 1}}
        ],
    })
    content = lesson_content_from_json(raw)
    assert content is not None
    assert content.vocabulary == [VocabWord(word="w", translation="t", example="e")]


class FakeLLM(LLMProvider):
    def __init__(self, response: str):
        self._response = response
        self.last_temperature = None

    async def chat(self, messages, temperature=None, **kwargs):
        self.last_temperature = temperature
        return self._response


async def test_lesson_service_generates_and_parses():
    llm = FakeLLM(VALID_LESSON_JSON)
    service = LessonService(llm)
    content = await service.generate("Travelling")
    assert content.topic == "Travelling"
    assert len(content.tasks) == 2
    assert llm.last_temperature == 0.7


class CallCountingLLM(LLMProvider):
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.temperatures = []

    async def chat(self, messages, temperature=None, **kwargs):
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        self.temperatures.append(temperature)
        response = self.responses[idx]
        if isinstance(response, Exception):
            raise response
        return response


async def test_generate_calls_three_llm_steps_in_order():
    llm = CallCountingLLM(
        [
            '{"topic": "Cooking", "intro": "Let us cook!", "lesson_type": "standard"}',
            '{"slides": ["Buy fresh herbs.", "Season lightly."]}',
            '["Say your recipe.", "Name your favourite dish."]',
        ]
    )
    content = await LessonService(llm).generate("Cooking")
    assert llm.calls == 3
    assert content.topic == "Cooking"
    assert content.slides == ["Buy fresh herbs.", "Season lightly."]
    assert content.tasks == ["Say your recipe.", "Name your favourite dish."]
    assert content.lesson_type == "standard"
    assert llm.temperatures == [0.7, 0.7, 0.7]


async def test_generate_degrades_when_side_steps_fail():
    llm = CallCountingLLM(
        [
            '{"topic": "Chess", "intro": "Play the game!", "lesson_type": "standard"}',
            RuntimeError("slides step failed"),
            '{"tasks": ["Explain your move.", "Describe the board."]}',
        ]
    )
    content = await LessonService(llm).generate("Chess")
    assert content.topic == "Chess"
    assert content.slides == []
    assert len(content.tasks) == 2
    assert llm.calls == 3


async def test_generate_keeps_core_slides_when_steps_empty():
    llm = CallCountingLLM(
        [
            '{"topic": "Travelling", "intro": "Go!", "slides": ["Book early."], "tasks": ["Where to?"], "lesson_type": "standard"}',
            '{"slides": []}',
            '{"tasks": []}',
        ]
    )
    content = await LessonService(llm).generate("Travelling")
    assert content.slides == ["Book early."]
    assert content.tasks == ["Where to?"]


async def test_lesson_service_generates_with_lesson_type():
    llm = FakeLLM(VALID_LESSON_JSON.replace('"topic": "Travelling"', '"topic": "Travelling", "lesson_type": "story"'))
    service = LessonService(llm)
    content = await service.generate("Travelling", lesson_type="story")
    assert content.lesson_type == "story"


def test_build_prompt_injects_lesson_type():
    messages = build_lesson_prompt("Chess", lesson_type="quiz")
    system = messages[0]["content"]
    assert "Quiz-style lesson" in system
    assert '"quiz"' in system

    messages = build_lesson_prompt("Chess", lesson_type="story")
    assert "Build the lesson around a tiny story" in messages[0]["content"]

    assert set(LESSON_TYPES) == {"standard", "story", "dialogue", "quiz", "ideas"}


def test_lesson_type_json_roundtrip():
    content = parse_lesson_response('{"topic": "Travelling", "lesson_type": "story"}')
    restored = lesson_content_from_json(lesson_content_to_json(content))
    assert restored.lesson_type == "story"

    legacy = lesson_content_from_json('{"topic": "Travelling", "intro": "hi"}')
    assert legacy.lesson_type == "standard"


def test_practice_parse_error_alias_compat():
    with pytest.raises(PracticeParseError):
        parse_practice_response("garbage")


def test_next_position_advances_steps():
    assert LESSON_STEPS[0] == "intro"
    assert next_lesson_position(0, 0, 0) == (1, 0, False)
    assert next_lesson_position(1, 0, 0) == (2, 0, False)
    assert next_lesson_position(2, 0, 0) == (3, 0, False)


def test_next_position_tasks_sequence():
    assert LESSON_STEPS[4] == "tasks"
    assert next_lesson_position(4, 0, 2) == (4, 1, False)
    assert next_lesson_position(4, 1, 2) == (5, 0, False)


def test_next_position_last_step_finishes():
    assert LESSON_STEPS[5] == "recap"
    assert next_lesson_position(5, 0, 0) == (6, 0, True)


def test_build_prompt_with_recent_topics():
    messages = build_lesson_prompt(
        None,
        recent_topics=["Daily Routine", "Cooking", "Travelling"],
    )
    system = messages[0]["content"]
    assert "Daily Routine" in system
    assert "DO NOT repeat" in system
    assert "DIFFERENT" in system


def test_build_prompt_without_recent_topics():
    messages = build_lesson_prompt(None)
    system = messages[0]["content"]
    assert "DO NOT repeat" not in system


def test_build_prompt_profile_and_recent_topics():
    messages = build_lesson_prompt(
        None,
        profile="Student profile: Weak areas: Present Perfect.",
        recent_topics=["Daily Routine", "Cooking"],
    )
    system = messages[0]["content"]
    assert "Weak areas: Present Perfect" in system
    assert "Daily Routine" in system
    assert "DO NOT repeat" in system


def test_parse_proposals_response():
    raw = '[{"topic": "Cooking", "description": "Learn food vocabulary"}, {"topic": "Travel", "description": "Explore travel phrases"}, {"topic": "Sports", "description": "Sports vocabulary"}]'
    proposals = parse_proposals_response(raw)
    assert len(proposals) == 3
    assert proposals[0]["topic"] == "Cooking"
    assert proposals[1]["description"] == "Explore travel phrases"


def test_parse_proposals_response_with_markdown():
    raw = '```json\n[{"topic": "Chess", "description": "Шахматы на английском"}, {"topic": "Music", "description": "Музыкальная лексика"}]\n```'
    proposals = parse_proposals_response(raw)
    assert len(proposals) == 2
    assert proposals[0]["topic"] == "Chess"


def test_parse_proposals_response_invalid():
    with pytest.raises(LessonParseError):
        parse_proposals_response("not json")


async def test_lesson_service_generate_proposals():
    response = '[{"topic": "AI", "description": "Обсудим будущее ИИ"}, {"topic": "Cooking", "description": "Кулинарная лексика"}, {"topic": "Space", "description": "Космос и звёзды"}]'
    llm = FakeLLM(response)
    service = LessonService(llm)
    proposals = await service.generate_proposals(level="B1")
    assert len(proposals) == 3
    assert proposals[0]["topic"] == "AI"
    assert llm.last_temperature == 0.8


class RecordingLLM(LLMProvider):
    def __init__(self):
        self.messages_by_call = []

    async def chat(self, messages, temperature=None, **kwargs):
        self.messages_by_call.append(messages)
        return '{"topic": "Chess", "intro": "Play the game!", "lesson_type": "standard"}'


async def test_generate_passes_plan_hint_to_llm():
    llm = RecordingLLM()
    await LessonService(llm).generate("Chess", plan_hint="Practice small talk phrases")
    assert len(llm.messages_by_call) == 3
    for messages in llm.messages_by_call:
        text = " ".join(m["content"] for m in messages)
        assert "LESSON PLAN CONTEXT" in text
        assert "Practice small talk phrases" in text


async def test_generate_without_plan_hint_has_no_plan_block():
    llm = RecordingLLM()
    await LessonService(llm).generate("Chess")
    assert len(llm.messages_by_call) == 3
    for messages in llm.messages_by_call:
        text = " ".join(m["content"] for m in messages)
        assert "LESSON PLAN CONTEXT" not in text


# ---------------------------------------------------------------------------
# Phase C: API уроков Mini App (api/routers/lessons.py) + progress/SRS.
#
# Порт bot/mini_api.py в FastAPI. Проверяем контракт ответов, квоту, SRS,
# заметки/XP и голосовую реплику (STT и to_wav подменяются).
# ---------------------------------------------------------------------------

import base64
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from core.deck import (
    DECK_PRESETS,
    Deck,
    DialogueScene,
    QuizItem,
    Slide,
    VocabCard,
)
from storage.repo import LessonNote, SRSWord, UserProfile

LESSONS_SECRET = "test-secret-0123456789abcdef0123456789"

DECK_CALLS: list[dict[str, Any]] = []
TG_ID = 999


class FakeSTT:
    """STT-заглушка: возвращает заранее заданный транскрипт."""

    def __init__(self, transcript: str):
        self.transcript = transcript

    async def transcribe(self, audio_path: str) -> str:
        return self.transcript


async def _fake_to_wav(src: str, dst: str, sample_rate: int = 16000) -> None:
    """to_wav без ffmpeg: пишем заглушку во временный wav-файл."""
    Path(dst).write_bytes(b"RIFF")


def _make_deck(topic: str = "Coffee") -> Deck:
    return Deck(
        title=topic,
        subtitle_ru="Про кофе",
        preset="mixed",
        emoji="☕",
        slides=[Slide(headline="Coffee", body="Coffee is great.", emoji="☕")],
        vocabulary=[
            VocabCard(
                word="brew",
                translation="заваривать",
                example="I brew coffee.",
                transcription="bruː",
            )
        ],
        quiz=[
            QuizItem(
                question="Pick?",
                options=["Tea", "Coffee"],
                answer_index=1,
                explanation_ru="Кофе",
            )
        ],
        dialogue=DialogueScene(
            scene_ru="Кафе",
            lines=[{"character": "Barista", "line": "Hi!"}],
            choices=[{"line": "Coffee", "next": -1}],
        ),
    )


def _patch_deck(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_generate_deck(
        llm,
        topic=None,
        level=None,
        profile=None,
        recent_topics=None,
        character_prompt=None,
        plan_hint=None,
        preset="mixed",
        weak_areas_prompt=None,
    ):
        captured.update(
            {
                "topic": topic,
                "level": level,
                "profile": profile,
                "character_prompt": character_prompt,
                "weak_areas_prompt": weak_areas_prompt,
                "preset": preset,
            }
        )
        return _make_deck(topic or "Coffee")

    captured["deck"] = _make_deck()
    DECK_CALLS.append(captured)
    monkeypatch.setattr("api.routers.lessons.generate_deck", fake_generate_deck)


def _lessons_app(tmp_path, *, llm_daily_limit: int = 1000) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_lessons.db"),
        jwt_secret=LESSONS_SECRET,
        api_insecure_auth=1,
        llm_daily_limit=llm_daily_limit,
        stt_provider="openai",
        stt_api_key="",
        llm_api_key="",  # чтобы STT не подхватил ключ из .env
    )
    return TestClient(create_app(settings))


def _lessons_auth(client: TestClient) -> str:
    payload = {
        "id": TG_ID,
        "first_name": "T",
        "username": "t",
        "auth_date": int(time.time()),
        "hash": "",
    }
    return client.post("/api/auth/tg", json=payload).json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_lesson_new_ok(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        response = client.post(
            "/api/lesson/new",
            json={"topic": "Coffee", "preset": "cards"},
            headers=_headers(token),
        )
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"deck", "session_id", "preset", "topic", "plan_hint"}
    assert isinstance(data["session_id"], int)
    assert data["topic"] == "Coffee"
    assert data["deck"]["title"] == "Coffee"
    assert data["deck"]["slides"][0]["headline"] == "Coffee"
    assert data["deck"]["quiz"][0]["answer_index"] == 1
    assert data["preset"] in DECK_PRESETS
    assert data["plan_hint"] is None


def test_lesson_new_requires_auth(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        response = client.post("/api/lesson/new", json={"topic": "Coffee"})
    assert response.status_code == 401


async def test_lesson_new_quota_exceeded_429(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path, llm_daily_limit=5)
    with client:
        token = _lessons_auth(client)
        repo = client.app.state.repo
        user = await repo.get_or_create_user(TG_ID)
        await repo.increment_llm_usage(user.id, date.today().isoformat(), 10)
        response = client.post(
            "/api/lesson/new",
            json={"topic": "Coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 429
    assert response.json()["detail"] == "Дневной лимит исчерпан"


def test_lesson_new_without_llm_503(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        client.app.state.llm = None
        token = _lessons_auth(client)
        response = client.post(
            "/api/lesson/new",
            json={"topic": "Coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "LLM не настроен"


def test_lesson_answer_correct_and_incorrect(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        client.post("/api/lesson/new", json={"topic": "Coffee"}, headers=_headers(token))

        good = client.post(
            "/api/lesson/answer",
            json={"quiz_index": 0, "chosen": 1},
            headers=_headers(token),
        )
        bad = client.post(
            "/api/lesson/answer",
            json={"quiz_index": 0, "chosen": 0},
            headers=_headers(token),
        )
    assert good.status_code == 200
    assert good.json() == {
        "correct": True,
        "answer_index": 1,
        "explanation": "Кофе",
        "explanation_ru": "Кофе",
    }
    assert bad.status_code == 200
    assert bad.json()["correct"] is False
    assert bad.json()["answer_index"] == 1


def test_lesson_answer_without_session_404(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        response = client.post(
            "/api/lesson/answer",
            json={"quiz_index": 0, "chosen": 1},
            headers=_headers(token),
        )
    assert response.status_code == 404


async def test_lesson_finish_ok_and_can_start_new(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        client.post("/api/lesson/new", json={"topic": "Coffee"}, headers=_headers(token))

        response = client.post(
            "/api/lesson/finish",
            json={
                "score": 1,
                "preset": "cards",
                "quiz_answers": [{"quiz_index": 0, "chosen": 1, "correct": True}],
                "flashcards": {"brew": False, "coffee": True},
            },
            headers=_headers(token),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["score"] == 1
        assert data["xp"] == 10
        assert data["next_topic"] == ""
        assert data["repeat_words"] == ["brew"]

        repo = client.app.state.repo
        user = await repo.get_or_create_user(TG_ID)
        notes = await repo.get_lesson_notes(user.id, limit=10)
        assert len(notes) == 1
        assert notes[0].lesson_id >= 0
        assert "brew" in notes[0].vocabulary
        words = await repo.get_srs_words(user.id, limit=10)
        assert any(w.word == "brew" for w in words)
        assert await repo.get_active_mini_lesson(user.id) is None

        again = client.post("/api/lesson/new", json={"topic": "Travel"}, headers=_headers(token))
    assert again.status_code == 200
    assert again.json()["topic"] == "Travel"


async def test_lesson_passes_profile_and_weak_areas_to_generation(tmp_path, monkeypatch) -> None:
    DECK_CALLS.clear()
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        repo = client.app.state.repo
        user = await repo.get_or_create_user(TG_ID)
        await repo.save_profile(
            UserProfile(
                user_id=user.id,
                goal="Работа в IT",
                interests="chess, travel",
                character="chill",
            )
        )
        now = datetime.now(timezone.utc).isoformat()
        await repo.upsert_weak_area(user.id, "Present Perfect", incorrect_increment=1, last_seen=now)

        response = client.post("/api/lesson/new", json={"topic": "Coffee"}, headers=_headers(token))

    assert response.status_code == 200
    assert DECK_CALLS
    context = DECK_CALLS[-1]
    assert context["profile"]
    assert "Работа в IT" in context["profile"]
    assert "chess" in context["profile"]
    assert context["weak_areas_prompt"]
    assert "Present Perfect" in context["weak_areas_prompt"]


def test_lesson_voice_ok(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    monkeypatch.setattr("api.routers.lessons.to_wav", _fake_to_wav)
    client = _lessons_app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _lessons_auth(client)
        client.post("/api/lesson/new", json={"topic": "Coffee"}, headers=_headers(token))
        audio = base64.b64encode(b"fake-audio-bytes").decode()
        response = client.post(
            "/api/lesson/voice",
            json={"audio_base64": audio, "expected_line": "brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["transcript"] == "I brew coffee"
    assert data["rating"] == 100
    assert data["tip"] == "Отлично произнесено!"
    assert data["expected_line"] == "brew coffee"


def test_lesson_voice_without_stt_503(tmp_path, monkeypatch) -> None:
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        client.app.state.stt = None
        token = _lessons_auth(client)
        client.post("/api/lesson/new", json={"topic": "Coffee"}, headers=_headers(token))
        audio = base64.b64encode(b"fake-audio-bytes").decode()
        response = client.post(
            "/api/lesson/voice",
            json={"audio_base64": audio, "expected_line": "brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "STT не настроен"


def test_progress_ok(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        response = client.get("/api/progress", headers=_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert data["level"] == "—"
    assert data["total_lessons"] == 0
    assert data["xp"] == 0
    assert data["character"] == "default"
    assert data["next_topic"] == ""
    assert data["due_words"] == 0


def test_progress_requires_auth(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        response = client.get("/api/progress")
    assert response.status_code == 401


async def test_review_due_and_answer(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        repo = client.app.state.repo
        user = await repo.get_or_create_user(TG_ID)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        word_id = await repo.add_srs_word(
            SRSWord(
                user_id=user.id,
                word="brew",
                translation="заваривать",
                example="I brew coffee.",
                next_review=past,
                interval_days=1,
                ease_factor=2.5,
                created_at=past,
            )
        )

        due = client.get("/api/review/due", headers=_headers(token))
        assert due.status_code == 200
        items = due.json()
        assert len(items) == 1
        assert items[0] == {
            "id": word_id,
            "word": "brew",
            "translation": "заваривать",
            "example": "I brew coffee.",
        }

        answer = client.post(
            "/api/review/answer",
            json={"word_id": word_id, "quality": 5},
            headers=_headers(token),
        )
        assert answer.status_code == 200
        assert answer.json() == {"ok": True}

        due_after = client.get("/api/review/due", headers=_headers(token))
        assert due_after.json() == []


def test_review_answer_missing_word_404(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        response = client.post(
            "/api/review/answer",
            json={"word_id": 123456, "quality": 5},
            headers=_headers(token),
        )
    assert response.status_code == 404


def test_achievements_fresh_user(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        response = client.get("/api/achievements", headers=_headers(token))
    assert response.status_code == 200
    data = response.json()
    assert data["level"]["name"] == "Новичок"
    assert data["level"]["emoji"] == "🌱"
    assert data["level"]["xp"] == 0
    assert data["level"]["next_level"] == "Ученик"
    assert data["level"]["xp_needed"] == 50
    assert len(data["achievements"]) == 15
    assert all(a["earned"] is False for a in data["achievements"])


async def test_achievements_earned_after_lesson(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        repo = client.app.state.repo
        user = await repo.get_or_create_user(TG_ID)
        await repo.add_lesson_note(
            LessonNote(user_id=user.id, lesson_id=1, topic="Coffee", vocabulary="brew")
        )
        response = client.get("/api/achievements", headers=_headers(token))
    assert response.status_code == 200
    by_id = {a["id"]: a["earned"] for a in response.json()["achievements"]}
    assert by_id["first_lesson"] is True
    assert by_id["first_correct"] is False


def test_leaderboard_ok(tmp_path) -> None:
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        response = client.get("/api/leaderboard", headers=_headers(token))
    assert response.status_code == 200
    rows = response.json()
    assert isinstance(rows, list)
    assert all("user_id" in r and "xp" in r for r in rows)


def test_lesson_new_reuses_recent_session_without_llm(tmp_path, monkeypatch) -> None:
    """Повторный клик «начать урок» не зовёт LLM ещё раз — возвращается та же сессия."""
    DECK_CALLS.clear()
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        first = client.post("/api/lesson/new", json={"topic": "Coffee"}, headers=_headers(token))
        assert first.status_code == 200
        calls_after_first = len(DECK_CALLS)

        second = client.post("/api/lesson/new", json={"topic": "Travel"}, headers=_headers(token))

    assert second.status_code == 200
    assert second.json()["session_id"] == first.json()["session_id"]
    assert second.json()["topic"] == first.json()["topic"]
    assert len(DECK_CALLS) == calls_after_first, "LLM не должен зваться повторно"


def test_lesson_new_after_finish_generates_new_deck(tmp_path, monkeypatch) -> None:
    """После завершения урока следующий клик генерирует новую деку."""
    DECK_CALLS.clear()
    _patch_deck(monkeypatch)
    client = _lessons_app(tmp_path)
    with client:
        token = _lessons_auth(client)
        first = client.post("/api/lesson/new", json={"topic": "Coffee"}, headers=_headers(token))
        client.post(
            "/api/lesson/finish",
            json={"session_id": first.json()["session_id"], "score": 1, "flashcards": {}},
            headers=_headers(token),
        )
        second = client.post("/api/lesson/new", json={"topic": "Travel"}, headers=_headers(token))

    assert second.status_code == 200
    assert second.json()["session_id"] != first.json()["session_id"]
    assert second.json()["topic"] == "Travel"
