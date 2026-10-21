"""Фабрики провайдеров. Выбор реализации — только через .env (см. bot/config.py)."""

from bot.config import Settings

from .base import LLMProvider, STTProvider, TTSProvider
from .llm_openai import OpenAIChatProvider
from .tts_edge import EdgeTTSProvider


def create_llm(settings: Settings) -> LLMProvider:
    if not settings.resolved_llm_base_url:
        raise ValueError(
            f"Неизвестный LLM_PROVIDER={settings.llm_provider!r}. "
            f"Доступные: deepseek, openai, ollama, groq, mistral, gemini, openrouter "
            f"(или укажи LLM_BASE_URL/LLM_MODEL вручную)."
        )
    api_key = settings.llm_api_key or "not-needed"
    return OpenAIChatProvider(
        base_url=settings.resolved_llm_base_url,
        api_key=api_key,
        model=settings.resolved_llm_model,
        default_temperature=settings.llm_temperature,
        timeout=getattr(settings, "llm_timeout_sec", 90.0),
    )


def create_stt(settings: Settings) -> STTProvider:
    provider = settings.stt_provider.lower()
    if provider == "faster-whisper":
        from .stt_faster_whisper import FasterWhisperProvider

        return FasterWhisperProvider(model_name=settings.resolved_stt_model)
    if provider == "openai":
        # Ключ облачного STT: STT_API_KEY, иначе LLM_API_KEY.
        api_key = settings.resolved_stt_api_key
        if not api_key:
            raise ValueError(
                "STT_PROVIDER=openai, но не заданы STT_API_KEY (или LLM_API_KEY) в .env"
            )
        from .stt_openai import OpenAIWhisperProvider

        return OpenAIWhisperProvider(
            api_key=api_key,
            model=settings.resolved_stt_model,
            base_url=settings.stt_base_url,
            timeout=settings.stt_timeout_sec,
            language=settings.stt_language,
        )
    raise ValueError(f"Неизвестный STT_PROVIDER={provider!r}. Доступные: faster-whisper, openai")


def create_tts(settings: Settings) -> TTSProvider:
    provider = settings.tts_provider.lower()
    if provider == "edge-tts":
        return EdgeTTSProvider(voice=settings.tts_voice)
    if provider == "openai":
        if not settings.tts_api_key:
            raise ValueError("TTS_PROVIDER=openai, но TTS_API_KEY не задан в .env")
        from .tts_openai import OpenAITTSProvider

        return OpenAITTSProvider(api_key=settings.tts_api_key)
    raise ValueError(f"Неизвестный TTS_PROVIDER={provider!r}. Доступные: edge-tts, openai")


def create_embedder(settings: Settings):
    """Асинхронный эмбеддер для RAG (OpenAI-совместимый API провайдера).

    Возвращает ``async (texts: list[str]) -> list[list[float]]``.
    Если провайдер не умеет эмбеддинги — вызов упадёт, а RAG-тьютор
    корректно откатится на обычный чат (см. core/rag.py).
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=settings.resolved_llm_base_url,
        api_key=settings.llm_api_key or "not-needed",
        max_retries=0,
    )
    model = settings.rag_embed_model

    async def embed(texts: list[str]) -> list[list[float]]:
        response = await client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

    return embed
