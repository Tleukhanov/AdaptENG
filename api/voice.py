"""Общая логика распознавания речи для web-api.

Единая точка для конвертации аудио, лимитов и оценки транскрипта. Её
используют и универсальный ``POST /api/voice`` (без урока), и уроковый
``POST /api/lesson/voice`` — чтобы не дублировать конвертацию и лимиты.

Поток: файл → [лимит размера] → ffmpeg в wav 16 кГц моно (с таймаутом) →
[лимит длительности] → STT-провайдер → транскрипт.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import re
import tempfile
import wave
from pathlib import Path

from fastapi import HTTPException, Request

from .loadguard import QueueFull
from providers.stt_openai import STTUnavailableError

logger = logging.getLogger(__name__)

#: Разрешённые форматы записи (браузер/телефон): mp3, m4a, webm, ogg, wav.
AUDIO_SUFFIXES = (
    ".mp3",
    ".m4a",
    ".mp4",
    ".aac",
    ".wav",
    ".webm",
    ".ogg",
    ".oga",
    ".opus",
    ".flac",
)

#: Таймаут конвертации ffmpeg (секунды) — битый файл не должен вешать воркер.
FFMPEG_TIMEOUT_SEC = 30.0

#: Фолбэк, если в настройках не задан лимит размера.
DEFAULT_MAX_AUDIO_BYTES = 8 * 1024 * 1024

#: Размер порции при чтении загруженного файла.
CHUNK_SIZE = 64 * 1024

AUDIO_MISSING_ERROR = "Аудио не получено"
AUDIO_TOO_LARGE_ERROR = "Аудио слишком большое (максимум {mb} МБ)"
AUDIO_TOO_LONG_ERROR = "Аудио слишком длинное (максимум {sec} сек)"
AUDIO_FORMAT_ERROR = "Неподдерживаемый формат аудио ({fmt})"
AUDIO_INVALID_ERROR = "Не удалось прочитать аудио — файл повреждён или не поддерживается"
STT_MISSING_ERROR = "STT не настроен"
STT_UNAVAILABLE_ERROR = "Сервис распознавания речи временно занят — попробуй через минуту"
STT_FAILED_ERROR = "Не удалось распознать речь"
NO_SPEECH_ERROR = "Не распознана речь"
STT_THROTTLE_ERROR = "Слишком часто распознаёшь речь — подожди минуту"
QUEUE_FULL_ERROR = "Сейчас много запросов — очередь переполнена, попробуй через минуту"

_TIP_EXCELLENT = "Отлично произнесено!"
_TIP_GOOD = "Хорошо, но можно точнее повторить интонацию и звуки."
_TIP_WEAK = "Повтори фразу ещё раз — медленнее и ближе к микрофону."

try:  # pragma: no cover - импорт зависит от наличия imageio-ffmpeg
    from providers.audio import to_wav
except ImportError:  # pragma: no cover
    to_wav = None


# ---------- разбор и оценка ----------


def decode_audio_b64(raw: str, max_bytes: int = DEFAULT_MAX_AUDIO_BYTES) -> bytes | None:
    """base64 из тела → байты аудио. None, если строка пустая или битая.

    Слишком большой файл — 413 (Payload Too Large).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not data:
        return None
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=AUDIO_TOO_LARGE_ERROR.format(mb=max_bytes // (1024 * 1024)),
        )
    return data


def normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


def phrase_rating(transcript: str, expected: str) -> int | None:
    """Доля слов фразы, которые юзер произнёс (без LLM и списания квоты)."""
    if not expected or not expected.strip():
        return None
    expected_tokens = normalize_tokens(expected)
    spoken_tokens = normalize_tokens(transcript)
    if not expected_tokens:
        return None
    if not spoken_tokens:
        return 0
    spoken_set = set(spoken_tokens)
    matched = sum(1 for token in expected_tokens if token in spoken_set)
    return round(100 * matched / len(expected_tokens))


def rating_tip(rating: int | None) -> str:
    if rating is None:
        return ""
    if rating >= 70:
        return _TIP_EXCELLENT
    if rating >= 40:
        return _TIP_GOOD
    return _TIP_WEAK


def expected_phrase(expected_line: str, word: str, mode: str = "lesson") -> str:
    """Что считаем эталоном: фраза урока, одно слово или ничего (free)."""
    if (mode or "").strip().lower() == "free":
        return ""
    line = (expected_line or "").strip()
    single = (word or "").strip()
    if (mode or "").strip().lower() == "word":
        return single or line
    return line or single


# ---------- конвертация ----------


async def _call_to_wav(converter, src: str, dst: str) -> None:
    fn = converter if converter is not None else to_wav
    if fn is None:  # pragma: no cover - резервный импорт
        from providers.audio import to_wav as _to_wav

        fn = _to_wav
    await fn(src, dst)


async def convert_to_wav(
    src: str,
    dst: str,
    converter=None,
    timeout: float = FFMPEG_TIMEOUT_SEC,
) -> None:
    """Конвертирует аудио в wav 16 кГц моно. Ошибка ffmpeg → 400, а не 500."""
    try:
        await asyncio.wait_for(_call_to_wav(converter, src, dst), timeout=timeout)
    except asyncio.TimeoutError as exc:
        logger.warning("ffmpeg не успел конвертировать аудио за %ss", timeout)
        raise HTTPException(status_code=400, detail=AUDIO_INVALID_ERROR) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Не удалось конвертировать аудио: %s", exc)
        raise HTTPException(status_code=400, detail=AUDIO_INVALID_ERROR) from exc


def wav_duration_sec(path: str) -> float:
    """Длительность wav в секундах (по заголовку). 0.0, если файл не читается."""
    try:
        with wave.open(path, "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate() or 16000
        return frames / float(rate)
    except (wave.Error, OSError, EOFError, ValueError):
        return 0.0


# ---------- распознавание ----------


async def transcribe(stt, wav_path: str, guard=None) -> str:
    """Зовёт STT-провайдер (через очередь, если она есть). Ошибка провайдера → 502."""
    try:
        if guard is not None:
            async with guard.slot():
                return (await stt.transcribe(wav_path)).strip()
        return (await stt.transcribe(wav_path)).strip()
    except QueueFull:
        raise
    except HTTPException:
        raise
    except Exception:
        logger.exception("Ошибка STT: %s", wav_path)
        raise HTTPException(status_code=502, detail=STT_FAILED_ERROR)


def ensure_stt_allowed(request: Request, user_id: int) -> None:
    """Лимит частоты распознаваний на пользователя (STT_MAX_PER_MIN)."""
    throttle = getattr(request.app.state, "stt_throttle", None)
    if throttle is not None and not throttle.allow(f"voice:{user_id}"):
        raise HTTPException(status_code=429, detail=STT_THROTTLE_ERROR)


def check_audio_suffix(suffix: str) -> None:
    """Пустое расширение пропускаем (браузер шлёт «blob»), известные — тоже."""
    if not suffix:
        return
    if suffix.lower() not in AUDIO_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=AUDIO_FORMAT_ERROR.format(fmt=suffix.lower().lstrip(".")),
        )


def remove_temp_audio(*paths: str) -> None:
    """Удаляет временные файлы аудио, не падая на уже удалённых."""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.warning("Не удалось удалить временное аудио: %s", path)


async def prepare_audio(
    audio: bytes,
    suffix: str = ".webm",
    max_bytes: int = DEFAULT_MAX_AUDIO_BYTES,
    max_duration_sec: int = 60,
    converter=None,
) -> tuple[str, str, float]:
    """Байты аудио → временный wav 16 кГц моно.

    Возвращает ``(raw_path, wav_path, duration)``. Файлы удаляет вызывающий
    через :func:`remove_temp_audio` — так один и тот же wav можно отдать и
    провайдеру оценки произношения, и фолбэку через STT.
    """
    if not audio:
        raise HTTPException(status_code=400, detail=AUDIO_MISSING_ERROR)
    if max_bytes > 0 and len(audio) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=AUDIO_TOO_LARGE_ERROR.format(mb=max_bytes // (1024 * 1024)),
        )

    fd, raw_path = tempfile.mkstemp(suffix=suffix or ".webm")
    os.close(fd)
    wav_path = raw_path + ".wav"
    try:
        Path(raw_path).write_bytes(audio)
        await convert_to_wav(raw_path, wav_path, converter=converter)
        duration = wav_duration_sec(wav_path)
        if max_duration_sec > 0 and duration > max_duration_sec:
            raise HTTPException(
                status_code=400,
                detail=AUDIO_TOO_LONG_ERROR.format(sec=max_duration_sec),
            )
    except Exception:
        remove_temp_audio(raw_path, wav_path)
        raise
    return raw_path, wav_path, duration


async def process_audio(
    audio: bytes,
    suffix: str = ".webm",
    stt=None,
    guard=None,
    max_bytes: int = DEFAULT_MAX_AUDIO_BYTES,
    max_duration_sec: int = 60,
    converter=None,
) -> tuple[str, float]:
    """Общий путь аудио → текст. Возвращает (транскрипт, длительность в сек)."""
    raw_path, wav_path, duration = await prepare_audio(
        audio,
        suffix=suffix,
        max_bytes=max_bytes,
        max_duration_sec=max_duration_sec,
        converter=converter,
    )
    try:
        transcript = await transcribe(stt, wav_path, guard=guard)
    finally:
        remove_temp_audio(raw_path, wav_path)

    if not transcript:
        raise HTTPException(status_code=400, detail=NO_SPEECH_ERROR)
    return transcript, duration
