"""Оценка произношения по фонемам (Pronunciation Assessment).

Внешний сервис слушает запись, сравнивает её с эталонной фразой и возвращает
баллы accuracy/fluency/completeness/prosody, разбивку по словам и фонемам.
Сейчас реализован Azure Speech REST (Pronunciation Assessment); если сервис
недоступен или отказал — исключение :class:`PronunciationUnavailableError`,
а вызывающий код (api) мягко откатывается на оценку по словам.

Эндпоинт Azure: ``POST https://{region}.stt.speech.microsoft.com/speech/
recognition/conversation/cognitiveservices/v1?language=en-US``. Параметры
оценки передаются в заголовке ``Pronunciation-Assessment`` (base64 JSON),
тело — wav 16 кГц моно.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "en-US"
DEFAULT_TIMEOUT_SEC = 15.0

#: Путь Azure Speech REST для распознавания с оценкой произношения.
AZURE_PATH = "/speech/recognition/conversation/cognitiveservices/v1"
AZURE_HOST_TEMPLATE = "https://{region}.stt.speech.microsoft.com"


class PronunciationUnavailableError(RuntimeError):
    """Сервис оценки произношения не ответил (сеть, таймаут, 4xx/5xx, мусор)."""


@dataclass
class PronunciationResult:
    """Результат оценки: баллы 0..100 и разбивка по словам/фонемам."""

    provider: str
    accuracy: float | None = None
    fluency: float | None = None
    completeness: float | None = None
    prosody: float | None = None
    transcript: str = ""
    words: list[dict[str, Any]] = field(default_factory=list)
    phonemes: list[dict[str, Any]] = field(default_factory=list)


class PronunciationProvider(Protocol):
    """Контракт провайдера оценки произношения."""

    async def assess(
        self,
        audio_path: str,
        expected_text: str,
        language: str = DEFAULT_LANGUAGE,
    ) -> PronunciationResult:
        ...


def _score(value: Any) -> float | None:
    """Балл Azure → float (None, если поля нет или оно нечисловое)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _word_entry(word: dict[str, Any]) -> dict[str, Any]:
    assessment = word.get("PronunciationAssessment") or {}
    return {
        "word": word.get("Word") or "",
        "accuracy": _score(assessment.get("AccuracyScore")),
        "error_type": assessment.get("ErrorType") or "None",
    }


def _phoneme_entries(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phonemes: list[dict[str, Any]] = []
    for word in words:
        for phoneme in word.get("Phonemes") or []:
            assessment = phoneme.get("PronunciationAssessment") or {}
            phonemes.append(
                {
                    "phoneme": phoneme.get("Phoneme") or "",
                    "accuracy": _score(assessment.get("AccuracyScore")),
                }
            )
    return phonemes


def parse_azure_response(payload: dict[str, Any], provider: str = "azure") -> PronunciationResult:
    """Разбирает JSON Azure Speech в :class:`PronunciationResult`.

    ``RecognitionStatus`` не ``Success`` (тишина, шум, не распознано) и пустой
    ``NBest`` — это отказ сервиса, а не результат с нулевым баллом.
    """
    status = payload.get("RecognitionStatus")
    if status not in (None, "Success"):
        raise PronunciationUnavailableError(f"Azure Speech не распознал речь: {status}")

    best_list = payload.get("NBest") or []
    if not best_list:
        raise PronunciationUnavailableError("Azure Speech вернул ответ без NBest")
    best = best_list[0] or {}

    assessment = best.get("PronunciationAssessment") or {}
    words = [_word_entry(word) for word in (best.get("Words") or [])]
    transcript = (
        best.get("Display")
        or payload.get("DisplayText")
        or best.get("Lexical")
        or ""
    ).strip()

    return PronunciationResult(
        provider=provider,
        accuracy=_score(assessment.get("AccuracyScore")),
        fluency=_score(assessment.get("FluencyScore")),
        completeness=_score(assessment.get("CompletenessScore")),
        prosody=_score(assessment.get("ProsodyScore")),
        transcript=transcript,
        words=words,
        phonemes=_phoneme_entries(best.get("Words") or []),
    )


class AzurePronunciationProvider:
    """Azure Speech Pronunciation Assessment (REST, без SDK).

    Запрос идёт с ``Granularity: Phoneme`` и ``EnableMiscue`` — сервис сам
    отмечает пропущенные/лишние слова, а баллы приходят по словам и фонемам.
    """

    def __init__(
        self,
        api_key: str,
        region: str,
        language: str = DEFAULT_LANGUAGE,
        timeout: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        key = (api_key or "").strip()
        region_name = (region or "").strip()
        if not key:
            raise ValueError("Azure Speech требует ключ: задай AZURE_SPEECH_KEY")
        if not region_name:
            raise ValueError("Azure Speech требует регион: задай AZURE_SPEECH_REGION")
        self._api_key = key
        self._region = region_name
        self._language = (language or "").strip() or DEFAULT_LANGUAGE
        self._timeout = max(1.0, float(timeout or DEFAULT_TIMEOUT_SEC))

    @property
    def language(self) -> str:
        return self._language

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def endpoint(self) -> str:
        """URL, куда уходит аудио (для логов и тестов)."""
        return f"{AZURE_HOST_TEMPLATE.format(region=self._region)}{AZURE_PATH}"

    def assessment_header(self, expected_text: str) -> str:
        """base64 JSON с параметрами оценки для заголовка Pronunciation-Assessment."""
        config = {
            "ReferenceText": expected_text,
            "GradingSystem": "HundredMark",
            "Granularity": "Phoneme",
            "EnableMiscue": True,
            "EnableProsodyAssessment": True,
        }
        raw = json.dumps(config, ensure_ascii=False).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    async def _post(self, audio: bytes, language: str, assessment: str) -> httpx.Response:
        """Отправляет wav в Azure. Вынесено отдельно — тесты подменяют HTTP."""
        headers = {
            "Ocp-Apim-Subscription-Key": self._api_key,
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json",
            "Pronunciation-Assessment": assessment,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                self.endpoint,
                params={"language": language},
                headers=headers,
                content=audio,
            )

    async def assess(
        self,
        audio_path: str,
        expected_text: str,
        language: str = DEFAULT_LANGUAGE,
    ) -> PronunciationResult:
        """Оценивает произношение записи относительно ``expected_text``."""
        text = (expected_text or "").strip()
        if not text:
            raise PronunciationUnavailableError("Не задана эталонная фраза для оценки")
        lang = (language or "").strip() or self._language

        try:
            audio = Path(audio_path).read_bytes()
        except OSError as exc:
            raise PronunciationUnavailableError(f"Не удалось прочитать аудио: {exc}") from exc

        try:
            response = await self._post(audio, lang, self.assessment_header(text))
        except httpx.HTTPError as exc:
            raise PronunciationUnavailableError(
                f"Azure Speech недоступен: {type(exc).__name__}: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — провайдер не должен ронять api
            raise PronunciationUnavailableError(f"Azure Speech: {exc}") from exc

        if response.status_code != 200:
            snippet = (getattr(response, "text", "") or "")[:200]
            raise PronunciationUnavailableError(
                f"Azure Speech ответил {response.status_code}: {snippet}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PronunciationUnavailableError("Azure Speech вернул не JSON") from exc
        if not isinstance(payload, dict):
            raise PronunciationUnavailableError("Azure Speech вернул неожиданный JSON")

        return parse_azure_response(payload)
