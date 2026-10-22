"""Режим «Словарь»: личные слова, проверка перевода и предложения.

Контракт API (список, идемпотентное добавление, удаление, 404 на чужое
слово, 401 без авторизации, 429 при исчерпанной квоте) и устойчивость к
сбоям LLM. Сеть не нужна: LLM везде подменён фейком.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from core.json_utils import JsonParseError
from core.vocab import VocabService, parse_check_response
from storage.repo import SRSWord

SECRET = "test-secret-0123456789abcdef0123456789"

CHECK_JSON = json.dumps(
    {
        "translation_ok": True,
        "sentence_ok": True,
        "score": 92,
        "feedback": "Отличный перевод! Предложение корректное, можно звучать естественнее.",
        "improved": "I would never humiliate you.",
    },
    ensure_ascii=False,
)


class FakeLLM:
    """LLM-фейк: отдаёт заданный ответ и считает вызовы."""

    def __init__(self, response: str = CHECK_JSON) -> None:
        self.response = response
        self.calls = 0
        self.last_messages: list[dict[str, str]] = []

    async def chat(self, messages, temperature=None, json_mode=False) -> str:
        self.calls += 1
        assert json_mode is True
        self.last_messages = messages
        return self.response


class BoomLLM:
    """LLM, который всегда падает (сеть/провайдер недоступны)."""

    async def chat(self, messages, temperature=None, json_mode=False) -> str:
        raise RuntimeError("provider is down")


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "jwt_secret": SECRET,
        "database_path": str(tmp_path / "vocab.db"),
        "session_cookie_secure": 0,
        "api_insecure_auth": 1,
        "llm_daily_limit": 100,
        "api_llm_min_interval_sec": 0.0,
        "llm_api_key": "",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as test_client:
        test_client.app.state.llm = FakeLLM()
        yield test_client


def _register(client: TestClient, email: str = "user@example.com") -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "superpass1", "name": "Student"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _add(
    client: TestClient,
    headers: dict[str, str],
    word: str = "humiliate",
    translation: str = "унижать",
    example: str = "Don't humiliate me.",
    lesson_id: int = 12,
) -> dict:
    response = client.post(
        "/api/vocab",
        json={
            "word": word,
            "translation": translation,
            "example": example,
            "lesson_id": lesson_id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["word"]


# ---------- список ----------


def test_empty_vocab_list(client: TestClient) -> None:
    headers = _register(client)
    response = client.get("/api/vocab", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"words": [], "total": 0, "due": 0}


# ---------- добавление ----------


def test_add_word_and_idempotent_repeat(client: TestClient) -> None:
    headers = _register(client)
    first = _add(client, headers)

    assert first["word"] == "humiliate"
    assert first["translation"] == "унижать"
    assert first["example"] == "Don't humiliate me."
    assert first["status"] == "learning"
    assert first["next_review"]

    again = _add(client, headers, translation="унизить")

    assert again["id"] == first["id"]
    assert again["translation"] == "унижать"  # повтор не перезаписывает слово

    listing = client.get("/api/vocab", headers=headers).json()
    assert listing["total"] == 1
    assert listing["due"] == 1
    assert len(listing["words"]) == 1
    assert listing["words"][0]["id"] == first["id"]


def test_vocab_list_puts_due_words_first(client: TestClient) -> None:
    headers = _register(client)
    older = _add(client, headers, word="alpha", translation="альфа")
    newer = _add(client, headers, word="beta", translation="бета")

    repo = client.app.state.repo
    import asyncio

    async def _make_not_due() -> None:
        user = await repo.get_user_by_email("user@example.com")
        word = await repo.get_srs_word(user.id, "alpha")
        word.next_review = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        await repo.update_srs_word(word)

    asyncio.run(_make_not_due())

    listing = client.get("/api/vocab", headers=headers).json()
    assert listing["total"] == 2
    assert listing["due"] == 1
    assert listing["words"][0]["id"] == newer["id"]
    assert listing["words"][1]["id"] == older["id"]


def test_vocab_list_pagination(client: TestClient) -> None:
    headers = _register(client)
    for index in range(3):
        _add(client, headers, word=f"word{index}", translation=f"слово{index}")

    page = client.get("/api/vocab?limit=2&offset=1", headers=headers).json()
    assert page["total"] == 3
    assert len(page["words"]) == 2


def test_add_word_requires_auth(client: TestClient) -> None:
    response = client.post("/api/vocab", json={"word": "humiliate"})
    assert response.status_code == 401


# ---------- валидация ----------


@pytest.mark.parametrize(
    "payload",
    [
        {"word": ""},
        {"word": "   "},
        {"word": "x" * 81},
        {"word": "ok", "translation": "y" * 201},
        {"word": "ok", "example": "z" * 301},
        {},
    ],
)
def test_add_word_validation_422(client: TestClient, payload: dict) -> None:
    headers = _register(client)
    response = client.post("/api/vocab", json=payload, headers=headers)
    assert response.status_code == 422


# ---------- удаление и чужое слово ----------


def test_delete_own_word(client: TestClient) -> None:
    headers = _register(client)
    word = _add(client, headers)

    response = client.delete(f"/api/vocab/{word['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get("/api/vocab", headers=headers).json()["total"] == 0


def test_delete_unknown_word_404(client: TestClient) -> None:
    headers = _register(client)
    assert client.delete("/api/vocab/9999", headers=headers).status_code == 404


def test_foreign_word_is_hidden(client: TestClient) -> None:
    owner = _register(client, "owner@example.com")
    word = _add(client, owner)

    stranger = _register(client, "stranger@example.com")

    check = client.post(
        "/api/vocab/check",
        json={"word_id": word["id"], "translation": "унижать", "sentence": "I humiliate you"},
        headers=stranger,
    )
    assert check.status_code == 404

    deleted = client.delete(f"/api/vocab/{word['id']}", headers=stranger)
    assert deleted.status_code == 404

    assert client.get("/api/vocab", headers=owner).json()["total"] == 1


# ---------- проверка ИИ ----------


def test_check_returns_ai_feedback(client: TestClient) -> None:
    headers = _register(client)
    word = _add(client, headers)

    response = client.post(
        "/api/vocab/check",
        json={
            "word_id": word["id"],
            "translation": "унижать",
            "sentence": "I humiliate you",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["translation_ok"] is True
    assert body["sentence_ok"] is True
    assert body["score"] == 92
    assert body["feedback"]
    assert body["improved"] == "I would never humiliate you."
    assert client.app.state.llm.calls == 1


def test_check_prompt_contains_word_and_answers(client: TestClient) -> None:
    headers = _register(client)
    word = _add(client, headers)

    client.post(
        "/api/vocab/check",
        json={"word_id": word["id"], "translation": "унижать", "sentence": "I humiliate you"},
        headers=headers,
    )
    messages = client.app.state.llm.last_messages
    assert messages[0]["role"] == "system"
    assert "humiliate" in messages[0]["content"] or "humiliate" in messages[1]["content"]
    assert "I humiliate you" in messages[1]["content"]


def test_check_llm_failure_502(client: TestClient) -> None:
    headers = _register(client)
    word = _add(client, headers)
    client.app.state.llm = BoomLLM()

    response = client.post(
        "/api/vocab/check",
        json={"word_id": word["id"], "translation": "унижать", "sentence": "I humiliate you"},
        headers=headers,
    )
    assert response.status_code == 502
    assert response.json()["detail"]


def test_check_broken_json_502(client: TestClient) -> None:
    headers = _register(client)
    word = _add(client, headers)
    client.app.state.llm = FakeLLM("sorry, no json")

    response = client.post(
        "/api/vocab/check",
        json={"word_id": word["id"], "translation": "унижать", "sentence": "I humiliate you"},
        headers=headers,
    )
    assert response.status_code == 502


def test_check_without_llm_502(client: TestClient) -> None:
    headers = _register(client)
    word = _add(client, headers)
    client.app.state.llm = None

    response = client.post(
        "/api/vocab/check",
        json={"word_id": word["id"], "translation": "унижать", "sentence": "I humiliate you"},
        headers=headers,
    )
    assert response.status_code == 502


def test_check_requires_auth(client: TestClient) -> None:
    response = client.post("/api/vocab/check", json={"word_id": 1})
    assert response.status_code == 401


def test_check_quota_exhausted_429(tmp_path) -> None:
    client = TestClient(create_app(_settings(tmp_path, llm_daily_limit=5)))
    with client:
        client.app.state.llm = FakeLLM()
        headers = _register(client)
        word = _add(client, headers)

        import asyncio

        async def _burn_quota() -> None:
            repo = client.app.state.repo
            user = await repo.get_user_by_email("user@example.com")
            await repo.increment_llm_usage(user.id, date.today().isoformat(), 5)

        asyncio.run(_burn_quota())

        response = client.post(
            "/api/vocab/check",
            json={
                "word_id": word["id"],
                "translation": "унижать",
                "sentence": "I humiliate you",
            },
            headers=headers,
        )
    assert response.status_code == 429
    assert response.json()["detail"] == "Дневной лимит исчерпан"


# ---------- разбор ответа LLM ----------


def test_parse_check_response_defaults_are_safe() -> None:
    result = parse_check_response('{"feedback": "молодец"}')
    assert result.translation_ok is False
    assert result.sentence_ok is False
    assert result.score == 0
    assert result.feedback == "молодец"


def test_parse_check_response_accepts_string_booleans() -> None:
    result = parse_check_response('{"translation_ok": "true", "sentence_ok": "yes", "score": 150}')
    assert result.translation_ok is True
    assert result.sentence_ok is True
    assert result.score == 100


def test_parse_check_response_rejects_garbage() -> None:
    with pytest.raises(JsonParseError):
        parse_check_response("no json here")


# ---------- сервис ----------


async def test_service_add_word_is_idempotent(tmp_path) -> None:
    from storage.sqlite import SQLiteRepository

    repo = SQLiteRepository(str(tmp_path / "service.db"))
    await repo.connect()
    try:
        user = await repo.get_or_create_user(4242)
        service = VocabService(repo)
        first, created = await service.add_word(user.id, "resilient", "устойчивый")
        second, created_again = await service.add_word(user.id, "  resilient ", "другой перевод")
        assert created is True
        assert created_again is False
        assert first.id == second.id
        assert second.translation == "устойчивый"

        page = await service.list_words(user.id)
        assert page.total == 1
        word = await service.get_owned_word(user.id, first.id)
        assert isinstance(word, SRSWord)
    finally:
        await repo.close()


async def test_service_status_known_after_three_reviews(tmp_path) -> None:
    from storage.sqlite import SQLiteRepository

    repo = SQLiteRepository(str(tmp_path / "status.db"))
    await repo.connect()
    try:
        user = await repo.get_or_create_user(4343)
        service = VocabService(repo)
        word, _ = await service.add_word(user.id, "curious", "любопытный")
        word.correct_count = 3
        await repo.update_srs_word(word)

        page = await service.list_words(user.id)
        from core.vocab import word_status

        assert word_status(page.words[0]) == "known"
    finally:
        await repo.close()
