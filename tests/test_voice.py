"""Тесты облачного STT и универсального эндпоинта распознавания /api/voice.

Без сети: HTTP-клиент провайдера подменяется, ffmpeg — либо заглушкой
(обычные тесты), либо реальным бинарником (тест на битое аудио).
"""

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from providers.factory import create_stt
from providers.stt_openai import OpenAIWhisperProvider, normalize_base_url

SECRET = "voice-secret-0123456789abcdef0123456789"
EMAIL = "student@example.com"
PASSWORD = "supersecret1"


class FakeSTT:
    """STT-заглушка: возвращает заранее заданный транскрипт."""

    def __init__(self, transcript: str = "I brew coffee"):
        self.transcript = transcript
        self.calls = 0

    async def transcribe(self, audio_path: str) -> str:
        self.calls += 1
        return self.transcript


async def _fake_to_wav(src: str, dst: str, sample_rate: int = 16000) -> None:
    """to_wav без ffmpeg: пишем заглушку во временный wav-файл."""
    Path(dst).write_bytes(b"RIFF")


def _app(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_voice.db"),
        jwt_secret=SECRET,
        stt_provider="openai",
        stt_api_key="",
        llm_api_key="",
        **overrides,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient) -> str:
    """Регистрируем пользователя по email и получаем токен."""
    response = client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload(name: str = "voice.webm", payload: bytes = b"fake-audio") -> dict:
    return {"file": (name, payload, "audio/webm")}


# ---------- облачный провайдер ----------


def test_normalize_base_url_defaults_to_openai():
    assert normalize_base_url("") == "https://api.openai.com/v1"
    assert normalize_base_url("https://api.openai.com/v1/") == "https://api.openai.com/v1"
    assert normalize_base_url("https://api.openai.com") == "https://api.openai.com/v1"


def test_normalize_base_url_groq():
    assert normalize_base_url("https://api.groq.com/openai/v1") == "https://api.groq.com/openai/v1"
    assert normalize_base_url("https://api.groq.com/openai") == "https://api.groq.com/openai/v1"
    assert normalize_base_url("https://api.groq.com") == "https://api.groq.com/openai/v1"


def test_stt_provider_uses_groq_endpoint():
    provider = OpenAIWhisperProvider(
        api_key="groq-key",
        model="whisper-large-v3-turbo",
        base_url="https://api.groq.com/openai/v1",
    )
    assert provider.endpoint == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert provider.model == "whisper-large-v3-turbo"
    assert provider.language == "en"


def test_stt_provider_requires_api_key():
    with pytest.raises(ValueError, match="STT_API_KEY"):
        OpenAIWhisperProvider(api_key="")


async def test_stt_provider_sends_file_and_parses_text(tmp_path):
    provider = OpenAIWhisperProvider(
        api_key="cloud-key",
        model="whisper-1",
        base_url="https://api.openai.com/v1",
        language="en",
        timeout=30.0,
    )
    captured: dict = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="  I brew coffee  ")

    provider._client.audio.transcriptions.create = create
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFFfake")

    assert await provider.transcribe(str(audio)) == "I brew coffee"
    assert captured["model"] == "whisper-1"
    assert captured["language"] == "en"
    assert captured["file"] is not None
    assert provider.timeout == 30.0


def test_create_stt_cloud_uses_settings():
    settings = Settings(
        stt_provider="openai",
        stt_api_key="cloud-key",
        stt_base_url="https://api.groq.com/openai/v1",
        stt_model="whisper-large-v3-turbo",
        stt_language="en",
        stt_timeout_sec=30.0,
        llm_api_key="",
    )
    provider = create_stt(settings)
    assert provider.endpoint == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert provider.model == "whisper-large-v3-turbo"
    assert provider.timeout == 30.0


def test_create_stt_requires_explicit_key():
    """LLM_API_KEY намеренно не используется как ключ STT (см. core.config)."""
    settings = Settings(stt_provider="openai", stt_api_key="", llm_api_key="llm-key")
    with pytest.raises(ValueError, match="STT_API_KEY"):
        create_stt(settings)


def test_create_stt_without_any_key_raises():
    settings = Settings(stt_provider="openai", stt_api_key="", llm_api_key="")
    with pytest.raises(ValueError, match="STT_API_KEY"):
        create_stt(settings)


def test_resolved_stt_model_defaults_per_provider():
    assert Settings(stt_provider="openai", stt_model="").resolved_stt_model == "whisper-1"
    assert Settings(stt_provider="faster-whisper", stt_model="").resolved_stt_model == "small"
    assert Settings(stt_provider="openai", stt_model="whisper-large-v3-turbo").resolved_stt_model == (
        "whisper-large-v3-turbo"
    )


# ---------- POST /api/voice ----------


def test_voice_requires_auth(tmp_path):
    client = _app(tmp_path)
    with client:
        response = client.post("/api/voice", files=_upload())
    assert response.status_code == 401


def test_voice_ok_without_lesson_session(tmp_path, monkeypatch):
    monkeypatch.setattr("api.voice.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice",
            files=_upload(),
            data={"expected_line": "brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["transcript"] == "I brew coffee"
    assert data["rating"] == 100
    assert data["tip"] == "Отлично произнесено!"
    assert data["duration"] == 0.0


def test_voice_free_mode_has_no_rating(tmp_path, monkeypatch):
    monkeypatch.setattr("api.voice.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice",
            files=_upload(),
            data={"mode": "free"},
            headers=_headers(token),
        )
    assert response.status_code == 200
    assert response.json()["rating"] is None
    assert response.json()["tip"] == ""


def test_voice_without_stt_503(tmp_path):
    client = _app(tmp_path)
    with client:
        client.app.state.stt = None
        token = _register(client)
        response = client.post("/api/voice", files=_upload(), headers=_headers(token))
    assert response.status_code == 503
    assert response.json()["detail"] == "STT не настроен"


def test_voice_too_large_file_413(tmp_path):
    client = _app(tmp_path, max_audio_bytes=1024)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice",
            files=_upload(payload=b"x" * 4096),
            headers=_headers(token),
        )
    assert response.status_code == 413
    assert "слишком большое" in response.json()["detail"].lower()


def test_voice_broken_audio_is_400_not_500(tmp_path):
    """Битое аудио -> понятная ошибка 400 (реальный ffmpeg падает на мусоре)."""
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice",
            files=_upload(payload=b"not-audio-at-all"),
            headers=_headers(token),
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Не удалось прочитать аудио — файл повреждён или не поддерживается"


def test_voice_unsupported_format_400(tmp_path):
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice",
            files=_upload(name="voice.txt"),
            headers=_headers(token),
        )
    assert response.status_code == 400
    assert "txt" in response.json()["detail"]


def test_voice_rate_limited_429(tmp_path, monkeypatch):
    monkeypatch.setattr("api.voice.to_wav", _fake_to_wav)
    client = _app(tmp_path, stt_max_per_min=1)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        first = client.post("/api/voice", files=_upload(), headers=_headers(token))
        second = client.post("/api/voice", files=_upload(), headers=_headers(token))
    assert first.status_code == 200
    assert second.status_code == 429
    assert "минуту" in second.json()["detail"]


# ---------- POST /api/lesson/voice ----------


def test_lesson_voice_without_session_404(tmp_path, monkeypatch):
    """Без активной уроки-сессии уроковый голосовой даёт 404 (не 500).

    Реплика пишется в audio_answers сессии, поэтому сессия обязательна.
    Универсальное распознавание без урока — POST /api/voice.
    """
    monkeypatch.setattr("api.routers.lessons.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/lesson/voice",
            json={"audio_base64": base64.b64encode(b"fake-audio").decode()},
            headers=_headers(token),
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "Активный урок не найден"


async def test_lesson_voice_keeps_response_contract(tmp_path, monkeypatch):
    monkeypatch.setattr("api.routers.lessons.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        repo = client.app.state.repo
        user = await repo.get_user_by_email(EMAIL)
        await repo.start_mini_lesson(user.id, "Coffee", "{}", "mixed")
        response = client.post(
            "/api/lesson/voice",
            json={
                "audio_base64": base64.b64encode(b"fake-audio").decode(),
                "expected_line": "brew coffee",
            },
            headers=_headers(token),
        )
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"transcript", "rating", "tip", "expected_line"}
    assert data["transcript"] == "I brew coffee"
    assert data["rating"] == 100
    assert data["expected_line"] == "brew coffee"
