"""Стриминг хода наставника (SSE): ``POST /api/tutor/turn/stream``.

Проверяем контракт событий (``delta`` → ``meta``), сохранение состояния
ПОСЛЕ стрима, фолбэк для провайдера без стриминга, старый формат чистого
JSON, 404/422 до открытия потока и событие ``error`` при обрыве модели.
LLM везде подменён фейком — сеть в тестах не нужна.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError, RateLimitError

from api.main import create_app
from core.config import Settings
from core.tutor import META_MARKER, build_stream_prompt, new_state, split_stream_text
from providers.base import LLMProvider
from providers.llm_openai import OpenAIChatProvider

SECRET = "test-secret-0123456789abcdef0123456789"

STREAM_META = {
    "kind": "ask",
    "question": "What did you do at the weekend?",
    "correction": None,
    "interests": ["chess"],
    "new_words": [],
    "level_signal": "A2",
    "should_finish": False,
}


def _stream_body(reply: str, meta: dict | None = None) -> str:
    payload = json.dumps(meta or STREAM_META, ensure_ascii=False)
    return f"{reply}\n{META_MARKER}\n{payload}"


class FakeStreamLLM:
    """Фейк со стримингом: отдаёт заранее заданные чанки."""

    def __init__(self, chunks: list[str] | None = None, error_after: bool = False) -> None:
        self.chunks = list(chunks or [])
        self.error_after = error_after
        self.calls = 0
        self.json_mode: bool | None = None

    async def chat(self, messages, temperature=None, json_mode=False) -> str:
        raise AssertionError("chat() не должен вызываться при стриминге")

    async def chat_stream(self, messages, temperature=None, json_mode=False):
        self.calls += 1
        self.json_mode = json_mode
        for chunk in self.chunks:
            yield chunk
        if self.error_after:
            raise TimeoutError("LLM stream broke")


class ChatOnlyLLM:
    """Провайдер без стриминга: только ``chat()`` (старый интерфейс)."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    async def chat(self, messages, temperature=None, json_mode=False) -> str:
        self.calls += 1
        assert json_mode is False
        return self.response


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "jwt_secret": SECRET,
        "database_path": str(tmp_path / "tutor_stream.db"),
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
        test_client.app.state.llm = FakeStreamLLM()
        yield test_client


def _start(client: TestClient) -> int:
    response = client.post("/api/tutor/session", json={"mode": "intro"})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _stream(client: TestClient, session_id: int, text: str = "I played chess."):
    return client.post(
        "/api/tutor/turn/stream",
        json={"session_id": session_id, "text": text},
    )


def _events(response) -> list[tuple[str, dict]]:
    """Разбирает SSE-тело в список ``(event, data)``."""
    events: list[tuple[str, dict]] = []
    name = ""
    for line in response.text.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line.split(":", 1)[1].strip())))
    return events


# ---------- контракт событий ----------


async def test_stream_sends_delta_chunks_then_meta(client: TestClient):
    session_id = _start(client)
    llm = FakeStreamLLM(
        [
            "Hi! ",
            "Nice to meet you. ",
            "What did you do at the weekend?\n<<<ME",
            "TA>>>\n",
            json.dumps(STREAM_META, ensure_ascii=False),
        ]
    )
    client.app.state.llm = llm

    response = _stream(client, session_id)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    events = _events(response)
    names = [name for name, _ in events]
    assert names == ["delta", "delta", "delta", "meta"]

    reply = "".join(data["text"] for name, data in events if name == "delta")
    assert reply.strip() == "Hi! Nice to meet you. What did you do at the weekend?"

    meta = events[-1][1]
    assert meta["kind"] == "ask"
    assert meta["question"] == "What did you do at the weekend?"
    assert meta["correction"] is None
    assert meta["interests"] == ["chess"]
    assert meta["new_words"] == []
    assert meta["level_signal"] == "A2"
    assert meta["should_finish"] is False
    assert meta["turn_index"] == 2
    assert meta["max_turns"] == 7

    assert llm.calls == 1
    assert llm.json_mode is False  # JSON mode несовместим со стримингом текста


async def test_stream_saves_state_after_finish(client: TestClient):
    session_id = _start(client)
    client.app.state.llm = FakeStreamLLM(["Well done! ", "How often do you play?\n", META_MARKER, "\n", json.dumps(STREAM_META)])

    response = _stream(client, session_id, text="I played chess yesterday.")
    assert response.status_code == 200, response.text
    assert [name for name, _ in _events(response)][-1] == "meta"

    repo = client.app.state.repo
    session = await repo.get_tutor_session(session_id)
    state = json.loads(session.state_json)
    assert state["turn_index"] == 2
    assert [item["role"] for item in state["turns"]] == ["tutor", "student", "tutor"]
    assert state["turns"][-1]["reply"] == "Well done! How often do you play?"
    assert state["turns"][-1]["kind"] == "ask"
    assert state["interests"] == ["chess"]
    assert state["level_signals"] == ["A2"]
    assert "What did you do at the weekend?" in state["asked"]
    assert session.status == "active"


# ---------- фолбэки ----------


async def test_stream_falls_back_to_chat_without_streaming(client: TestClient):
    session_id = _start(client)
    llm = ChatOnlyLLM(_stream_body("Hello there! Nice to see you."))
    client.app.state.llm = llm

    response = _stream(client, session_id)
    assert response.status_code == 200, response.text
    events = _events(response)

    assert [name for name, _ in events] == ["delta", "meta"]
    assert events[0][1]["text"].strip() == "Hello there! Nice to see you."
    assert events[1][1]["kind"] == "ask"
    assert events[1][1]["turn_index"] == 2
    assert llm.calls == 1


async def test_stream_accepts_legacy_pure_json(client: TestClient):
    session_id = _start(client)
    legacy = json.dumps(
        {
            "reply": "Good job! Let's keep going.",
            "kind": "praise",
            "question": "What else do you like?",
            "correction": None,
            "interests": [],
            "level_signal": "B1",
            "should_finish": False,
        },
        ensure_ascii=False,
    )
    client.app.state.llm = ChatOnlyLLM(legacy)

    response = _stream(client, session_id)
    assert response.status_code == 200, response.text
    events = _events(response)

    assert [name for name, _ in events] == ["delta", "meta"]
    assert events[0][1]["text"] == "Good job! Let's keep going."
    assert events[1][1]["kind"] == "praise"
    assert events[1][1]["question"] == "What else do you like?"
    assert events[1][1]["level_signal"] == "B1"


# ---------- проверки до открытия потока ----------


async def test_stream_foreign_session_is_404(tmp_path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as owner:
        owner.app.state.llm = FakeStreamLLM()
        owner_session = _start(owner)

        with TestClient(create_app(settings)) as stranger:
            stranger.app.state.llm = FakeStreamLLM()
            _start(stranger)  # у «чужака» своя гостевая cookie
            response = _stream(stranger, owner_session)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


async def test_stream_text_validation(client: TestClient):
    session_id = _start(client)

    too_long = _stream(client, session_id, "x" * 601)
    assert too_long.status_code == 422

    empty = _stream(client, session_id, "")
    assert empty.status_code == 422

    blank = _stream(client, session_id, "   ")
    assert blank.status_code == 422

    assert client.app.state.llm.calls == 0  # до LLM дело не дошло


# ---------- сбой модели ----------


async def test_stream_error_event_after_first_chunk(client: TestClient):
    session_id = _start(client)
    client.app.state.llm = FakeStreamLLM(["Partial answer"], error_after=True)

    response = _stream(client, session_id)
    assert response.status_code == 200, response.text
    events = _events(response)

    assert [name for name, _ in events] == ["delta", "error"]
    assert events[0][1]["text"] == "Partial answer"
    assert events[1][1]["detail"]

    repo = client.app.state.repo
    session = await repo.get_tutor_session(session_id)
    state = json.loads(session.state_json)
    assert state["turn_index"] == 1  # ход не записался
    assert session.status == "active"


async def test_stream_broken_meta_event_does_not_save_state(client: TestClient):
    session_id = _start(client)
    client.app.state.llm = FakeStreamLLM(["Hello! ", META_MARKER, "not a json at all"])

    response = _stream(client, session_id)
    events = _events(response)
    assert [name for name, _ in events] == ["delta", "error"]

    repo = client.app.state.repo
    session = await repo.get_tutor_session(session_id)
    assert json.loads(session.state_json)["turn_index"] == 1


# ---------- чистые функции ----------


def test_split_stream_text_holds_partial_marker():
    assert split_stream_text("Hello there") == ("Hello there", "")
    assert split_stream_text("Hello <<") == ("Hello ", "<<")
    assert split_stream_text("Hello <<<META") == ("Hello ", "<<<META")
    assert split_stream_text("Hello <<<META>>>{}") == ("Hello ", "<<<META>>>{}")


def test_build_stream_prompt_asks_for_meta_block():
    state = new_state(mode="intro", self_level="A2", max_turns=7)
    messages = build_stream_prompt(state, "I like chess.")

    combined = "\n".join(item["content"] for item in messages)
    assert META_MARKER in combined
    assert "Respond ONLY with a single valid JSON object" not in combined
    assert messages[-1] == {"role": "user", "content": "I like chess."}


async def test_base_provider_chat_stream_yields_single_chunk():
    class MinimalLLM(LLMProvider):
        async def chat(self, messages, temperature=None, json_mode=False) -> str:
            return "one shot"

    chunks = [
        chunk
        async for chunk in MinimalLLM().chat_stream(
            [{"role": "user", "content": "hi"}], temperature=0.5
        )
    ]
    assert chunks == ["one shot"]


# ---------- OpenAI-адаптер: стрим, бюджет и фолбэк ----------


def _chunk(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class FakeOpenAIStream:
    """Асинхронный итератор чанков в форме OpenAI SDK."""

    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        self._chunks = [_chunk(text) for text in chunks]
        self._error = error
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


def _stream_provider() -> OpenAIChatProvider:
    return OpenAIChatProvider(
        base_url="https://x.test",
        api_key="k",
        model="m",
        fallback_models=("m-fallback",),
        retries=0,
        backoff=(0.01,),
    )


async def test_openai_chat_stream_falls_back_before_first_chunk():
    provider = _stream_provider()
    calls: list[str] = []
    fallback = FakeOpenAIStream(["Hel", "lo"])

    async def create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "m":
            raise RateLimitError("rate limited", response=MagicMock(), body=None)
        return fallback

    provider._client.chat.completions.create = create

    chunks = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "hi"}], temperature=0.5
        )
    ]
    assert chunks == ["Hel", "lo"]
    assert calls == ["m", "m-fallback"]
    assert fallback.closed


async def test_openai_chat_stream_stops_after_error_following_first_chunk():
    provider = _stream_provider()
    calls: list[str] = []
    stream = FakeOpenAIStream(["Hi"], error=APITimeoutError(request=MagicMock()))

    async def create(**kwargs):
        calls.append(kwargs["model"])
        return stream

    provider._client.chat.completions.create = create

    received: list[str] = []
    with pytest.raises(APITimeoutError):
        async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}]):
            received.append(chunk)

    assert received == ["Hi"]
    assert calls == ["m"]  # после первого чанка не повторяем и не меняем модель
    assert stream.closed
