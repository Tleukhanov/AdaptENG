"""POST /api/voice — универсальное распознавание речи (не зависит от урока).

Принимает файл записи (multipart/form-data: mp3/m4a/webm/ogg/wav) и
необязательные поля ``expected_line``, ``word``, ``mode``. Активная уроковая
сессия НЕ требуется — для уроков есть ``POST /api/lesson/voice``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from core.analytics import track_event
from core.config import Settings
from providers.pronunciation import PronunciationResult, PronunciationUnavailableError
from storage.repo import Repository

from ..deps import current_user, get_current_user_id, get_repository, get_settings_dep, get_stt
from ..loadguard import QueueFull
from ..voice import (
    AUDIO_TOO_LARGE_ERROR,
    CHUNK_SIZE,
    NO_SPEECH_ERROR,
    QUEUE_FULL_ERROR,
    STT_MISSING_ERROR,
    check_audio_suffix,
    ensure_stt_allowed,
    expected_phrase,
    normalize_tokens,
    phrase_rating,
    prepare_audio,
    process_audio,
    rating_tip,
    remove_temp_audio,
    transcribe,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice"])

MODE_LESSON = "lesson"
MODE_WORD = "word"
MODE_FREE = "free"
ASSESS_MISSING_TEXT_ERROR = "Не задана эталонная фраза для оценки"


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """Читает загруженный файл, обрываясь на лимите размера (413).

    ``max_bytes <= 0`` — без ограничения размера.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if max_bytes > 0 and total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=AUDIO_TOO_LARGE_ERROR.format(mb=max_bytes // (1024 * 1024)),
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/voice")
async def voice(
    request: Request,
    file: UploadFile = File(...),
    expected_line: str = Form(""),
    word: str = Form(""),
    mode: str = Form(MODE_LESSON),
    user_id: int = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
    stt=Depends(get_stt),
) -> dict[str, Any]:
    """Файл речи → транскрипт (+ оценка, если задана эталонная фраза).

    ``mode``: ``lesson`` (эталон — expected_line/word), ``word`` (эталон — слово),
    ``free`` (без оценки, только транскрипт).
    """
    if stt is None:
        raise HTTPException(status_code=503, detail=STT_MISSING_ERROR)

    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    ensure_stt_allowed(request, user.id)

    max_bytes = settings.max_audio_bytes or 0
    suffix = Path(file.filename or "").suffix
    check_audio_suffix(suffix)

    try:
        audio = await _read_limited(file, max_bytes)
    finally:
        await file.close()

    stt_guard = getattr(request.app.state, "stt_guard", None)
    transcript, duration = await process_audio(
        audio,
        suffix=suffix or ".webm",
        stt=stt,
        guard=stt_guard,
        max_bytes=max_bytes,
        max_duration_sec=settings.max_voice_duration_sec,
    )

    expected = expected_phrase(expected_line, word, mode)
    rating = phrase_rating(transcript, expected)
    tip = rating_tip(rating)

    await track_event(
        repo,
        user.id,
        "web_voice_transcribed",
        {"mode": (mode or MODE_LESSON).strip().lower(), "rating": rating},
    )
    logger.info(
        "Распознавание речи: user=%s mode=%s rating=%s duration=%.1fs",
        user.id,
        mode,
        rating,
        duration,
    )
    return {
        "transcript": transcript,
        "duration": round(duration, 1),
        "rating": rating,
        "tip": tip,
    }


# ---------- POST /api/voice/assess ----------


def _assess_payload(result: PronunciationResult, duration: float) -> dict[str, Any]:
    """Результат провайдера → JSON эндпоинта (+ rating/tip для UI)."""
    accuracy = result.accuracy
    rating = round(accuracy) if accuracy is not None else None
    return {
        "provider": result.provider,
        "accuracy": accuracy,
        "fluency": result.fluency,
        "completeness": result.completeness,
        "prosody": result.prosody,
        "transcript": result.transcript,
        "words": result.words,
        "phonemes": result.phonemes,
        "rating": rating,
        "tip": rating_tip(rating),
        "duration": round(duration, 1),
    }


def _words_payload(transcript: str, expected: str, duration: float) -> dict[str, Any]:
    """Фолбэк без провайдера: оценка по совпадению слов (как POST /api/voice)."""
    spoken = set(normalize_tokens(transcript))
    words = [
        {
            "word": token,
            "accuracy": 100.0 if token in spoken else 0.0,
            "error_type": "None" if token in spoken else "Omission",
        }
        for token in normalize_tokens(expected)
    ]
    rating = phrase_rating(transcript, expected)
    # accuracy и rating — обе шкалы 0..100 (rating — доля найденных слов).
    accuracy = float(rating) if rating is not None else 0.0
    return {
        "provider": "words",
        "accuracy": accuracy,
        "fluency": None,
        "completeness": accuracy if rating is not None else None,
        "prosody": None,
        "transcript": transcript,
        "words": words,
        "phonemes": [],
        "rating": rating,
        "tip": rating_tip(rating),
        "duration": round(duration, 1),
    }


@router.post("/voice/assess")
async def voice_assess(
    request: Request,
    file: UploadFile = File(...),
    expected_text: str = Form(""),
    language: str = Form(""),
    user_id: int = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
    stt=Depends(get_stt),
) -> dict[str, Any]:
    """Оценка произношения фразы: провайдер фонем, иначе мягкий фолбэк по словам.

    Аудио конвертируется в wav один раз; провайдер получает эталон
    ``expected_text``. Если провайдер выключен или недоступен — тот же wav
    уходит в STT, а балл считается по совпадению слов (``provider="words"``).
    """
    expected = (expected_text or "").strip()
    if not expected:
        raise HTTPException(status_code=400, detail=ASSESS_MISSING_TEXT_ERROR)

    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    ensure_stt_allowed(request, user.id)

    max_bytes = settings.max_audio_bytes or 0
    suffix = Path(file.filename or "").suffix
    check_audio_suffix(suffix)

    try:
        audio = await _read_limited(file, max_bytes)
    finally:
        await file.close()

    lang = (language or "").strip() or settings.azure_speech_language or "en-US"
    provider = getattr(request.app.state, "pronunciation", None)

    raw_path, wav_path, duration = await prepare_audio(
        audio,
        suffix=suffix or ".webm",
        max_bytes=max_bytes,
        max_duration_sec=settings.max_voice_duration_sec,
    )
    try:
        if provider is not None:
            try:
                result = await provider.assess(wav_path, expected, lang)
            except PronunciationUnavailableError as exc:
                logger.warning(
                    "Оценка произношения недоступна, фолбэк по словам: user=%s error=%s",
                    user.id,
                    exc,
                )
            else:
                await track_event(
                    repo,
                    user.id,
                    "web_voice_assessed",
                    {"provider": result.provider, "accuracy": result.accuracy},
                )
                return _assess_payload(result, duration)

        if stt is None:
            raise HTTPException(status_code=503, detail=STT_MISSING_ERROR)

        stt_guard = getattr(request.app.state, "stt_guard", None)
        try:
            transcript = await transcribe(stt, wav_path, guard=stt_guard)
        except QueueFull:
            logger.warning("Очередь STT переполнена: user=%s", user.id)
            raise HTTPException(status_code=429, detail=QUEUE_FULL_ERROR)
    finally:
        remove_temp_audio(raw_path, wav_path)

    if not transcript:
        raise HTTPException(status_code=400, detail=NO_SPEECH_ERROR)

    payload = _words_payload(transcript, expected, duration)
    await track_event(
        repo,
        user.id,
        "web_voice_assessed",
        {"provider": "words", "accuracy": payload["accuracy"]},
    )
    logger.info(
        "Оценка произношения (слова): user=%s accuracy=%s duration=%.1fs",
        user.id,
        payload["accuracy"],
        duration,
    )
    return payload
