"""Универсальный LLM-адаптер поверх OpenAI-совместимого API.

Один класс закрывает DeepSeek, OpenAI, Ollama, Groq, Mistral, Gemini, OpenRouter —
провайдер задаётся только через base_url/api_key/model в .env.
"""

import asyncio
import logging

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from .base import LLMProvider

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError)
_MAX_RETRIES = 3
_BACKOFF_SECONDS = (3.0, 6.0, 12.0)


class OpenAIChatProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        default_temperature: float = 0.3,
        retries: int = _MAX_RETRIES,
        backoff: tuple[float, ...] = _BACKOFF_SECONDS,
        timeout: float = 90.0,
    ):
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            timeout=timeout,
        )
        self._model = model
        self._temperature = default_temperature
        self._max_retries = retries
        self._backoff = backoff

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> str:
        last_error: Exception | None = None
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                return (content or "").strip()
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = self._backoff[min(attempt, len(self._backoff) - 1)]
                    logger.warning(
                        "LLM транзиентная ошибка %s, попытка %s/%s через %ss: %s",
                        type(exc).__name__,
                        attempt + 1,
                        self._max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM chat вернул ошибку без исключения")
