"""Тесты оценки произношения: Azure-провайдер, фабрика и /api/voice/assess.

Без сети: HTTP-клиент Azure подменяется, ffmpeg — заглушкой (кроме теста на
битое аудио). Фолбэк по словам работает на существующем STT-пути.
"""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.config import Settings
from providers.factory import create_pronunciation
from providers.pronunciation import (
    AzurePronunciationProvider,
    PronunciationResult,
    PronunciationUnavailableError,
    parse_azure_response,
)

SECRET = "pron-secret-0123456789abcdef0123456789"
EMAIL = "speaker@example.com"
PASSWORD = "supersecret1"


class FakeSTT:
    def __init__(self, transcript: str = "I brew coffee") -> None:
        self.transcript = transcript
        self.calls = 0

    async def transcribe(self, audio_path: str) -> str:
        self.calls += 1
        return self.transcript


class FakePronunciation:
    """Провайдер-заглушка: отдаёт готовый результат или ошибку."""

    def __init__(self, result: PronunciationResult | None = None, error: Exception | None = None):
        self.result = result or PronunciationResult(provider="azure")
        self.error = error
        self.calls: list[tuple[bool, str, str]] = []

    async def assess(self, audio_path: str, expected_text: str, language: str = "en-US"):
        self.calls.append((Path(audio_path).exists(), expected_text, language))
        if self.error is not None:
            raise self.error
        return self.result


async def _fake_to_wav(src: str, dst: str, sample_rate: int = 16000) -> None:
    Path(dst).write_bytes(b"RIFF")


def _app(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        database_path=str(tmp_path / "adapteng_pron.db"),
        jwt_secret=SECRET,
        stt_provider="openai",
        stt_api_key="",
        llm_api_key="",
        **overrides,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient) -> str:
    response = client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload(name: str = "voice.webm", payload: bytes = b"fake-audio") -> dict:
    return {"file": (name, payload, "audio/webm")}


AZURE_PAYLOAD = {
    "RecognitionStatus": "Success",
    "DisplayText": "Good morning.",
    "NBest": [
        {
            "Display": "Good morning.",
            "Lexical": "good morning",
            "PronunciationAssessment": {
                "AccuracyScore": 87,
                "FluencyScore": 90,
                "CompletenessScore": 100,
                "ProsodyScore": 78,
            },
            "Words": [
                {
                    "Word": "good",
                    "PronunciationAssessment": {"AccuracyScore": 92, "ErrorType": "None"},
                    "Phonemes": [
                        {"Phoneme": "g", "PronunciationAssessment": {"AccuracyScore": 95}},
                        {"Phoneme": "uh", "PronunciationAssessment": {"AccuracyScore": 88}},
                    ],
                },
                {
                    "Word": "morning",
                    "PronunciationAssessment": {"AccuracyScore": 82, "ErrorType": "Mispronunciation"},
                    "Phonemes": [
                        {"Phoneme": "m", "PronunciationAssessment": {"AccuracyScore": 90}},
                    ],
                },
            ],
        }
    ],
}


# ---------- разбор ответа Azure ----------


def test_parse_azure_response_scores_words_and_phonemes():
    result = parse_azure_response(AZURE_PAYLOAD)
    assert result.provider == "azure"
    assert result.accuracy == 87.0
    assert result.fluency == 90.0
    assert result.completeness == 100.0
    assert result.prosody == 78.0
    assert result.transcript == "Good morning."
    assert result.words == [
        {"word": "good", "accuracy": 92.0, "error_type": "None"},
        {"word": "morning", "accuracy": 82.0, "error_type": "Mispronunciation"},
    ]
    assert result.phonemes == [
        {"phoneme": "g", "accuracy": 95.0},
        {"phoneme": "uh", "accuracy": 88.0},
        {"phoneme": "m", "accuracy": 90.0},
    ]


def test_parse_azure_response_prosody_missing_is_none():
    payload = {
        "RecognitionStatus": "Success",
        "NBest": [{"PronunciationAssessment": {"AccuracyScore": 50}}],
    }
    result = parse_azure_response(payload)
    assert result.prosody is None
    assert result.words == []
    assert result.phonemes == []


def test_parse_azure_response_no_match_is_unavailable():
    with pytest.raises(PronunciationUnavailableError):
        parse_azure_response({"RecognitionStatus": "NoMatch", "NBest": []})


# ---------- Azure Speech REST ----------


def test_azure_provider_builds_endpoint_and_header():
    provider = AzurePronunciationProvider(api_key="key", region="westeurope")
    assert provider.endpoint == (
        "https://westeurope.stt.speech.microsoft.com"
        "/speech/recognition/conversation/cognitiveservices/v1"
    )
    assert provider.language == "en-US"
    header = json.loads(base64.b64decode(provider.assessment_header("Good morning")).decode())
    assert header["ReferenceText"] == "Good morning"
    assert header["GradingSystem"] == "HundredMark"
    assert header["Granularity"] == "Phoneme"
    assert header["EnableMiscue"] is True


def test_azure_provider_requires_key_and_region():
    with pytest.raises(ValueError, match="AZURE_SPEECH_KEY"):
        AzurePronunciationProvider(api_key="", region="westeurope")
    with pytest.raises(ValueError, match="AZURE_SPEECH_REGION"):
        AzurePronunciationProvider(api_key="key", region="")


async def test_azure_provider_assess_parses_response(tmp_path, monkeypatch):
    provider = AzurePronunciationProvider(api_key="key", region="westeurope", timeout=5.0)
    captured: dict = {}

    async def fake_post(self, audio, language, assessment):
        captured["audio"] = audio
        captured["language"] = language
        captured["assessment"] = assessment
        return SimpleNamespace(status_code=200, json=lambda: AZURE_PAYLOAD, text="")

    monkeypatch.setattr(AzurePronunciationProvider, "_post", fake_post)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFFfake")

    result = await provider.assess(str(audio), "Good morning", "en-GB")

    assert result.provider == "azure"
    assert result.accuracy == 87.0
    assert result.words[0]["word"] == "good"
    assert result.phonemes[0]["phoneme"] == "g"
    assert captured["audio"] == b"RIFFfake"
    assert captured["language"] == "en-GB"
    header = json.loads(base64.b64decode(captured["assessment"]).decode())
    assert header["ReferenceText"] == "Good morning"


@pytest.mark.parametrize("status", [401, 500])
async def test_azure_provider_http_errors_are_unavailable(tmp_path, monkeypatch, status):
    provider = AzurePronunciationProvider(api_key="key", region="westeurope")
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFFfake")

    async def fake_post(self, audio, language, assessment):
        return SimpleNamespace(status_code=status, text="denied")

    monkeypatch.setattr(AzurePronunciationProvider, "_post", fake_post)
    with pytest.raises(PronunciationUnavailableError):
        await provider.assess(str(audio), "Good morning")


async def test_azure_provider_network_error_is_unavailable(tmp_path, monkeypatch):
    import httpx

    provider = AzurePronunciationProvider(api_key="key", region="westeurope")
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFFfake")

    async def fake_post(self, audio, language, assessment):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(AzurePronunciationProvider, "_post", fake_post)
    with pytest.raises(PronunciationUnavailableError):
        await provider.assess(str(audio), "Good morning")


# ---------- фабрика ----------


def test_factory_off_by_default():
    assert create_pronunciation(Settings(pronunciation_provider="off")) is None


def test_factory_azure_needs_key_and_region():
    assert create_pronunciation(Settings(pronunciation_provider="azure")) is None
    assert (
        create_pronunciation(
            Settings(pronunciation_provider="azure", azure_speech_key="key", azure_speech_region="")
        )
        is None
    )


def test_factory_azure_with_credentials():
    provider = create_pronunciation(
        Settings(
            pronunciation_provider="azure",
            azure_speech_key="key",
            azure_speech_region="westeurope",
            azure_speech_language="en-GB",
        )
    )
    assert isinstance(provider, AzurePronunciationProvider)
    assert provider.language == "en-GB"
    assert provider.endpoint.startswith("https://westeurope.stt.speech.microsoft.com/")


# ---------- POST /api/voice/assess ----------


def test_assess_requires_auth(tmp_path):
    client = _app(tmp_path)
    with client:
        response = client.post(
            "/api/voice/assess",
            files=_upload(),
            data={"expected_text": "I brew coffee"},
        )
    assert response.status_code == 401


def test_assess_without_provider_falls_back_to_words(tmp_path, monkeypatch):
    monkeypatch.setattr("api.voice.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice/assess",
            files=_upload(),
            data={"expected_text": "I brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["provider"] == "words"
    assert data["accuracy"] == 100.0
    assert data["rating"] == 100
    assert data["phonemes"] == []
    assert [w["word"] for w in data["words"]] == ["i", "brew", "coffee"]
    assert all(w["error_type"] == "None" for w in data["words"])
    assert data["transcript"] == "I brew coffee"


def test_assess_fallback_marks_missing_words(tmp_path, monkeypatch):
    monkeypatch.setattr("api.voice.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew")
        token = _register(client)
        response = client.post(
            "/api/voice/assess",
            files=_upload(),
            data={"expected_text": "I brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "words"
    assert data["words"][-1] == {"word": "coffee", "accuracy": 0.0, "error_type": "Omission"}


def test_assess_with_provider_returns_phonemes(tmp_path, monkeypatch):
    monkeypatch.setattr("api.voice.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    result = parse_azure_response(AZURE_PAYLOAD)
    fake = FakePronunciation(result=result)
    with client:
        client.app.state.pronunciation = fake
        client.app.state.stt = FakeSTT("should not be used")
        token = _register(client)
        response = client.post(
            "/api/voice/assess",
            files=_upload(),
            data={"expected_text": "Good morning", "language": "en-GB"},
            headers=_headers(token),
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["provider"] == "azure"
    assert data["accuracy"] == 87.0
    assert data["prosody"] == 78.0
    assert data["words"][0] == {"word": "good", "accuracy": 92.0, "error_type": "None"}
    assert data["phonemes"][0] == {"phoneme": "g", "accuracy": 95.0}
    assert client.app.state.stt.calls == 0
    assert fake.calls == [(True, "Good morning", "en-GB")]


def test_assess_provider_failure_falls_back_to_words(tmp_path, monkeypatch):
    monkeypatch.setattr("api.voice.to_wav", _fake_to_wav)
    client = _app(tmp_path)
    fake = FakePronunciation(error=PronunciationUnavailableError("boom"))
    with client:
        client.app.state.pronunciation = fake
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice/assess",
            files=_upload(),
            data={"expected_text": "I brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 200
    assert response.json()["provider"] == "words"
    assert client.app.state.stt.calls == 1


def test_assess_missing_expected_text_400(tmp_path):
    client = _app(tmp_path)
    with client:
        token = _register(client)
        response = client.post(
            "/api/voice/assess",
            files=_upload(),
            data={"expected_text": "   "},
            headers=_headers(token),
        )
    assert response.status_code == 400
    assert "эталонная фраза" in response.json()["detail"]


def test_assess_too_large_file_413(tmp_path):
    client = _app(tmp_path, max_audio_bytes=1024)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice/assess",
            files=_upload(payload=b"x" * 4096),
            data={"expected_text": "I brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 413
    assert "слишком большое" in response.json()["detail"].lower()


def test_assess_broken_audio_is_400(tmp_path):
    client = _app(tmp_path)
    with client:
        client.app.state.stt = FakeSTT("I brew coffee")
        token = _register(client)
        response = client.post(
            "/api/voice/assess",
            files=_upload(payload=b"not-audio-at-all"),
            data={"expected_text": "I brew coffee"},
            headers=_headers(token),
        )
    assert response.status_code == 400
    assert "повреждён" in response.json()["detail"]
