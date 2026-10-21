"""Облачный STT через OpenAI-совместимый API.

Один класс закрывает OpenAI (whisper-1) и Groq (whisper-large-v3-turbo):
разница только в ``base_url``, модели и ключе. Аудио уходит multipart'ом на
``{base_url}/audio/transcriptions``, ответ разбирается по полю ``text``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlsplit, urlunsplit

from openai import AsyncOpenAI

from .base import STTProvider

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "whisper-1"
DEFAULT_LANGUAGE = "en"
DEFAULT_TIMEOUT_SEC = 60.0

#: Версия в пути (…/v1, …/v1beta) — такой базе хвост не добавляем.
_VERSION_RE = re.compile(r"/v\d")


class STTUnavailableError(RuntimeError):
    """Провайдер распознавания не ответил (перегрузка, сеть, все модели отвалились)."""


def _is_retryable(exc: Exception) -> bool:
    """Повторять ли попытку: 429/5xx/таймауты — да; 401/400 — нет."""
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    name = type(exc).__name__
    return any(
        marker in name
        for marker in ("Timeout", "Connection", "APIConnection", "RateLimit", "InternalServer", "ServiceUnavailable")
    )


def normalize_base_url(base_url: str) -> str:
    """Приводит базу к OpenAI-совместимому виду (…/v1).

    * ``https://api.openai.com/v1`` — без изменений;
    * ``https://api.openai.com`` → ``https://api.openai.com/v1``;
    * ``https://api.groq.com/openai`` → ``https://api.groq.com/openai/v1``.
    """
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return DEFAULT_BASE_URL
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    host = parts.netloc.lower()
    if "api.groq.com" in host:
        if path.endswith("/v1"):
            pass
        elif "/openai" in path:
            path = f"{path}/v1"
        else:
            path = "/openai/v1"
    elif not path:
        path = "/v1"
    elif not path.endswith("/v1") and not _VERSION_RE.search(path):
        path = f"{path}/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class OpenAIWhisperProvider(STTProvider):
    """Облачное распознавание речи (OpenAI / Groq / другие совместимые API).

    Устойчив к временным сбоям провайдера: Groq в пиковые часы отвечает
    «Please wait a moment and try again» (503) или 429. Поэтому запрос
    повторяется с backoff, а при неудаче пробуется запасная модель.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        language: str = DEFAULT_LANGUAGE,
        fallback_models: tuple[str, ...] = (),
        max_attempts: int = 3,
        retry_backoff_sec: float = 1.5,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise ValueError(
                "Облачный STT требует API-ключ: задай STT_API_KEY (или LLM_API_KEY)"
            )
        self._base_url = normalize_base_url(base_url)
        self._model = (model or "").strip() or DEFAULT_MODEL
        self._fallback_models = tuple(m for m in fallback_models if m and m != self._model)
        self._language = (language or "").strip() or DEFAULT_LANGUAGE
        self._timeout = max(1.0, float(timeout or DEFAULT_TIMEOUT_SEC))
        self._max_attempts = max(1, int(max_attempts))
        self._retry_backoff_sec = max(0.0, float(retry_backoff_sec))
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=key,
            max_retries=0,
            timeout=self._timeout,
        )

    @property
    def endpoint(self) -> str:
        """URL, куда уходит файл (для логов и тестов)."""
        return f"{self._base_url}/audio/transcriptions"

    @property
    def model(self) -> str:
        return self._model

    @property
    def language(self) -> str:
        return self._language

    @property
    def timeout(self) -> float:
        return self._timeout

    async def _transcribe_once(self, audio_path: str, model: str) -> str:
        with open(audio_path, "rb") as audio_file:
            result = await self._client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                language=self._language,
                timeout=self._timeout,
            )
        return (getattr(result, "text", "") or "").strip()

    async def transcribe(self, audio_path: str) -> str:
        """Распознаёт речь, переживая временные сбои провайдера.

        Порядок попыток: основная модель (с ретраями) → запасные модели.
        """
        last_error: Exception | None = None
        for model in (self._model, *self._fallback_models):
            for attempt in range(1, self._max_attempts + 1):
                try:
                    return await self._transcribe_once(audio_path, model)
                except Exception as exc:  # noqa: BLE001 — решаем по типу ошибки
                    last_error = exc
                    if not _is_retryable(exc):
                        break  # 401/400 — повтор не поможет, пробуем другую модель
                    if attempt < self._max_attempts:
                        delay = self._retry_backoff_sec * attempt
                        logger.warning(
                            "STT: %s не ответил (%s), повтор %d/%d через %.1fs",
                            model,
                            type(exc).__name__,
                            attempt + 1,
                            self._max_attempts,
                            delay,
                        )
                        await asyncio.sleep(delay)
        raise STTUnavailableError(
            f"Облачный сервис распознавания речи временно недоступен: {last_error}"
        ) from last_error
