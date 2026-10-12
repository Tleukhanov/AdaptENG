"""Интеграционные тесты чата и TTS (Phase B): POST /api/chat и /api/chat/tts."""

from __future__ import annotations

import time
from datetime import date

from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from core.practice import PracticeResult

SECRET = "test-secret-0123456789abcdef0123456789"


class FakePractice:
    async def analyze(self, text, history, profile=None, character_prompt="", weak_areas_prompt=""):
        return PracticeResult(
            is_correct=True,
            corrected_text="",
            issues=[],
            next_question="What about you?",
            spoken_reply="Nice job!",
            tone="friendly",
        )


class FakeTTS:
    async def synthesize(self, text, voice=None):
        return b"fake-mp3-bytes"


def _make_app(tmp_path) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_chat.db"),
        jwt_secret=SECRET,
        api_insecure_auth=1,
        llm_daily_limit=5,
    )
    return TestClient(create_app(settings))


def _tg_user() -> dict:
    return {
        "id": 999,
        "first_name": "T",
        "username": "t",
        "auth_date": int(time.time()),
        "hash": "",
    }


def _auth(client: TestClient) -> str:
    token = client.post("/api/auth/tg", json=_tg_user()).json()["token"]
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_chat_ok(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.practice = FakePractice()
        client.app.state.tts = FakeTTS()
        token = _auth(client)
        response = client.post("/api/chat", json={"text": "Hello!"}, headers=_headers(token))
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "Nice job!"
        assert data["tone"] == "friendly"
        assert data["issues"] == []
        assert data["is_correct"] is True
        assert data["next_question"] == "What about you?"
        assert data["character"]["id"] == "default"


def test_chat_select_character_then_chat(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.practice = FakePractice()
        client.app.state.tts = FakeTTS()
        token = _auth(client)

        select = client.put(
            "/api/me/character",
            json={"character_id": "chill"},
            headers=_headers(token),
        )
        assert select.status_code == 200
        assert select.json()["character"]["id"] == "chill"

        response = client.post("/api/chat", json={"text": "Hello!"}, headers=_headers(token))
        assert response.status_code == 200
        assert response.json()["character"]["id"] == "chill"


async def test_chat_quota_exceeded(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.practice = FakePractice()
        client.app.state.tts = FakeTTS()
        token = _auth(client)
        repo = client.app.state.repo
        row = await repo.get_or_create_user(999)
        await repo.increment_llm_usage(row.id, date.today().isoformat(), 10)
        response = client.post("/api/chat", json={"text": "Hello!"}, headers=_headers(token))
        assert response.status_code == 429
        assert response.json()["detail"] == "Дневной лимит исчерпан"


def test_chat_requires_auth(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        response = client.post("/api/chat", json={"text": "Hello!"})
    assert response.status_code == 401


def test_tts_returns_audio(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.tts = FakeTTS()
        token = _auth(client)
        response = client.post(
            "/api/chat/tts",
            json={"text": "hi", "character_id": "chill"},
            headers=_headers(token),
        )
        assert response.status_code == 200
        assert response.content == b"fake-mp3-bytes"
        assert response.headers["content-type"].startswith("audio/")


def test_tts_missing_provider(tmp_path) -> None:
    client = _make_app(tmp_path)
    with client:
        client.app.state.tts = None
        token = _auth(client)
        response = client.post(
            "/api/chat/tts",
            json={"text": "hi"},
            headers=_headers(token),
        )
        assert response.status_code == 503