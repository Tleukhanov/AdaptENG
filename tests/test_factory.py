import pytest

from bot.config import Settings
from providers.factory import create_llm, create_stt, create_tts


def test_openai_tts_without_key_raises():
    settings = Settings(tts_provider="openai", tts_api_key="")
    with pytest.raises(ValueError, match="TTS_API_KEY"):
        create_tts(settings)


def test_openai_tts_with_key_creates_provider(monkeypatch):
    from providers import tts_openai

    created = {}

    class FakeAsyncOpenAI:
        def __init__(self, api_key: str, **kwargs):
            created["api_key"] = api_key

    monkeypatch.setattr(tts_openai, "AsyncOpenAI", FakeAsyncOpenAI)

    settings = Settings(tts_provider="openai", tts_api_key="tts-key-123")
    provider = create_tts(settings)
    assert created["api_key"] == "tts-key-123"
    assert provider is not None


def test_openai_tts_does_not_use_llm_key(monkeypatch):
    from providers import tts_openai

    created = {}

    class FakeAsyncOpenAI:
        def __init__(self, api_key: str, **kwargs):
            created["api_key"] = api_key

    monkeypatch.setattr(tts_openai, "AsyncOpenAI", FakeAsyncOpenAI)

    settings = Settings(tts_provider="openai", tts_api_key="", llm_api_key="llm-key")
    with pytest.raises(ValueError, match="TTS_API_KEY"):
        create_tts(settings)
    assert created == {}


def test_edge_tts_does_not_require_key():
    settings = Settings(tts_provider="edge-tts", tts_api_key="", llm_api_key="")
    provider = create_tts(settings)
    assert provider is not None


def test_unknown_tts_provider_raises():
    settings = Settings(tts_provider="yandex")
    with pytest.raises(ValueError, match="Неизвестный TTS_PROVIDER"):
        create_tts(settings)


def test_create_llm_unknown_provider_raises():
    settings = Settings(llm_provider="unknown", llm_base_url="", llm_model="")
    with pytest.raises(ValueError, match="Неизвестный LLM_PROVIDER"):
        create_llm(settings)


def test_create_stt_openai_without_key_raises():
    # llm_api_key="" — иначе ключ подхватится из .env как запасной.
    settings = Settings(stt_provider="openai", stt_api_key="", llm_api_key="")
    with pytest.raises(ValueError, match="STT_API_KEY"):
        create_stt(settings)


def test_create_stt_openai_falls_back_to_llm_key():
    settings = Settings(stt_provider="openai", stt_api_key="", llm_api_key="llm-key")
    provider = create_stt(settings)
    assert provider is not None
