"""Абстракции провайдеров: LLM, STT, TTS.

Любая конкретная реализация подключается через фабрику (factory.py)
и настраивается только через .env — код бота не знает про провайдеров.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    """Чат-модель. Сообщения — в формате OpenAI: [{"role": "...", "content": "..."}]."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> str:
        raise NotImplementedError

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """Куски ответа по мере генерации.

        Базовая реализация — фолбэк для провайдеров без стриминга: обычный
        ``chat()`` и один чанк с готовым текстом.
        """
        text = await self.chat(messages, temperature=temperature, json_mode=json_mode)
        if text:
            yield text


class STTProvider(ABC):
    """Распознавание речи (голос -> текст)."""

    @abstractmethod
    async def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError


class TTSProvider(ABC):
    """Синтез речи (текст -> аудио в байтах, mp3)."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        raise NotImplementedError
