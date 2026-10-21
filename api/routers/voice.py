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
from storage.repo import Repository

from ..deps import current_user, get_current_user_id, get_repository, get_settings_dep, get_stt
from ..voice import (
    AUDIO_TOO_LARGE_ERROR,
    CHUNK_SIZE,
    STT_MISSING_ERROR,
    check_audio_suffix,
    ensure_stt_allowed,
    expected_phrase,
    phrase_rating,
    process_audio,
    rating_tip,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice"])

MODE_LESSON = "lesson"
MODE_WORD = "word"
MODE_FREE = "free"


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
