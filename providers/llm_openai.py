"""Универсальный LLM-адаптер поверх OpenAI-совместимого API.

Один класс закрывает DeepSeek, OpenAI, Ollama, Groq, Mistral, Gemini, OpenRouter —
провайдер задаётся только через base_url/api_key/model в .env.

Устойчивость к перегрузу провайдера (важно для интерактивных экранов):
* общий бюджет времени на весь вызов (`total_budget`), чтобы не упереться в
  30-секундный таймаут Heroku-роутера;
* при 429/5xx/таймауте пробуем ЗАПАСНУЮ модель (OpenRouter/агрегаторы часто
  отдают 429 на пул одной модели, а другая модель в это время работает);
* 401/400 не повторяем — ключ/запрос не исправятся повтором.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from .base import LLMProvider

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError)
_MAX_RETRIES = 3
_BACKOFF_SECONDS = (3.0, 6.0, 12.0)

#: Сколько всего секунд отводим на один chat() (Heroku-роутер режет на 30 c).
DEFAULT_TOTAL_BUDGET_SEC = 24.0


def _is_retryable(exc: Exception) -> bool:
    """429/5xx/сеть/таймаут — повторяем; 401/400 — нет."""
    if isinstance(exc, _RETRYABLE_ERRORS):
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    name = type(exc).__name__
    return any(
        marker in name
        for marker in ("Timeout", "Connection", "RateLimit", "InternalServer", "ServiceUnavailable")
    )


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
        fallback_models: tuple[str, ...] = (),
        total_budget: float = DEFAULT_TOTAL_BUDGET_SEC,
    ):
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            timeout=timeout,
        )
        self._model = model
        self._fallback_models = tuple(m for m in fallback_models if m and m != model)
        self._temperature = default_temperature
        self._max_retries = retries
        self._backoff = backoff
        self._timeout = timeout
        self._total_budget = max(1.0, float(total_budget))

    @property
    def model(self) -> str:
        return self._model

    @property
    def fallback_models(self) -> tuple[str, ...]:
        return self._fallback_models

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> str:
        deadline = time.monotonic() + self._total_budget
        last_error: Exception | None = None

        base_kwargs: dict = {
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if json_mode:
            base_kwargs["response_format"] = {"type": "json_object"}

        # Основная модель (с ретраями), затем запасные — пока есть бюджет.
        for model in (self._model, *self._fallback_models):
            for attempt in range(self._max_retries + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 1.0:
                    break
                per_attempt = min(self._timeout, remaining)
                try:
                    response = await asyncio.wait_for(
                        self._client.chat.completions.create(
                            model=model,
                            timeout=per_attempt,
                            **base_kwargs,
                        ),
                        timeout=per_attempt + 1.0,
                    )
                    content = response.choices[0].message.content
                    return (content or "").strip()
                except Exception as exc:  # noqa: BLE001 — решаем по типу ошибки
                    last_error = exc
                    if not _is_retryable(exc):
                        # Ключ/запрос неверны: другая модель не поможет.
                        raise
                    if model != self._model:
                        logger.warning(
                            "LLM: запасная модель %s тоже не ответила (%s)",
                            model,
                            type(exc).__name__,
                        )
                        break
                    if attempt < self._max_retries:
                        delay = min(
                            self._backoff[min(attempt, len(self._backoff) - 1)],
                            max(0.0, deadline - time.monotonic() - 1.0),
                        )
                        if delay <= 0:
                            break
                        logger.warning(
                            "LLM %s: %s (%s), повтор %s/%s через %.1fs",
                            model,
                            type(exc).__name__,
                            _short(exc),
                            attempt + 1,
                            self._max_retries,
                            delay,
                        )
                        await asyncio.sleep(delay)

        if last_error is not None:
            raise last_error
        raise TimeoutError("LLM: истёк бюджет времени на ответ")

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """Куски ответа по мере генерации (SSE-совместимый ``stream=True``).

        Тот же бюджет времени и фолбэк моделей, что у ``chat()``. Ошибка ДО
        первого чанка повторяется/уходит на запасную модель; после первого
        чанка стрим обрывается ошибкой — склеивать два ответа нельзя.
        """
        deadline = time.monotonic() + self._total_budget
        last_error: Exception | None = None

        base_kwargs: dict = {
            "messages": messages,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if json_mode:
            base_kwargs["response_format"] = {"type": "json_object"}

        for model in (self._model, *self._fallback_models):
            for attempt in range(self._max_retries + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 1.0:
                    break
                per_attempt = min(self._timeout, remaining)
                started = False
                stream = None
                try:
                    stream = await asyncio.wait_for(
                        self._client.chat.completions.create(
                            model=model,
                            timeout=per_attempt,
                            stream=True,
                            **base_kwargs,
                        ),
                        timeout=per_attempt + 1.0,
                    )
                    async for event in stream:
                        if time.monotonic() > deadline:
                            raise TimeoutError("LLM: истёк бюджет времени на стрим")
                        chunk = _chunk_text(event)
                        if not chunk:
                            continue
                        started = True
                        yield chunk
                    return
                except Exception as exc:  # noqa: BLE001 — решаем по типу ошибки
                    last_error = exc
                    if started:
                        # Часть ответа уже ушла клиенту: повтор дал бы дубль.
                        logger.warning(
                            "LLM %s: стрим оборвался после первого чанка (%s)",
                            model,
                            type(exc).__name__,
                        )
                        raise
                    if not _is_retryable(exc):
                        raise
                    if model != self._model:
                        logger.warning(
                            "LLM: запасная модель %s не стримится (%s)",
                            model,
                            type(exc).__name__,
                        )
                        break
                    if attempt < self._max_retries:
                        delay = min(
                            self._backoff[min(attempt, len(self._backoff) - 1)],
                            max(0.0, deadline - time.monotonic() - 1.0),
                        )
                        if delay <= 0:
                            break
                        logger.warning(
                            "LLM %s: %s (%s), повтор стрима %s/%s через %.1fs",
                            model,
                            type(exc).__name__,
                            _short(exc),
                            attempt + 1,
                            self._max_retries,
                            delay,
                        )
                        await asyncio.sleep(delay)
                finally:
                    closer = getattr(stream, "aclose", None)
                    if closer is not None:
                        try:
                            await closer()
                        except Exception:  # noqa: BLE001 — закрытие не должно ломать поток
                            logger.debug("LLM: не удалось закрыть stream", exc_info=True)

        if last_error is not None:
            raise last_error
        raise TimeoutError("LLM: истёк бюджет времени на ответ")


def _chunk_text(event) -> str:
    """Текст дельты из чанка OpenAI-стрима (usage-чанки без choices пропускаем)."""
    choices = getattr(event, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    content = getattr(delta, "content", None)
    return content or ""


def _short(exc: Exception) -> str:
    """Короткий текст ошибки для логов (без огромного JSON от провайдера)."""
    text = str(exc).replace("\n", " ")
    return text[:200]
