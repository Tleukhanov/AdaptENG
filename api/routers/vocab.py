"""Режим «Словарь» (web-продукт): личные слова, повторение и проверка ИИ.

Эндпоинты:

* ``GET /api/vocab`` — слова пользователя (сначала due, затем по дате добавления);
* ``POST /api/vocab`` — добавить слово (идемпотентно по ``(user_id, word)``);
* ``POST /api/vocab/check`` — ОДИН LLM-вызов: перевод + собственное предложение;
* ``DELETE /api/vocab/{word_id}`` — удалить своё слово (чужое → 404).

Повторение по интервалам живёт в ``POST /api/review/answer`` (``core.srs``) и
здесь не дублируется. Бизнес-логика — в ``core.vocab``, тут только HTTP,
лимиты и события аналитики.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.analytics import track_event
from core.vocab import (
    VocabError,
    VocabLLMUnavailable,
    VocabParseError,
    VocabService,
    VocabWordNotFound,
    word_status,
)
from storage.repo import SRSWord

from ..deps import current_user, get_current_user_id, get_repository, get_settings_dep
from ..loadguard import QueueFull
from ..quota import QuotaExceeded, check_quota, consume_quota
from ..schemas import (
    VocabAddRequest,
    VocabCheckRequest,
    VocabCheckResponse,
    VocabListResponse,
    VocabWordOut,
)

router = APIRouter(prefix="/api/vocab", tags=["vocab"])

logger = logging.getLogger(__name__)

QUOTA_ERROR = "Дневной лимит исчерпан"
THROTTLE_ERROR = "Слишком часто — подожди секунду"
QUEUE_FULL_ERROR = "Сейчас много запросов — очередь переполнена, попробуй через минуту"
LLM_ERROR = "Не удалось проверить ответ — попробуй ещё раз через минуту"
WORD_NOT_FOUND_ERROR = "Слово не найдено"


def _word_out(word: SRSWord) -> VocabWordOut:
    return VocabWordOut(
        id=word.id,
        word=word.word,
        translation=word.translation,
        example=word.example,
        status=word_status(word),
        next_review=word.next_review,
    )


@router.get("", response_model=VocabListResponse)
async def list_vocab(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> VocabListResponse:
    """Слова текущего пользователя: due-первыми, затем по дате добавления."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    page = await VocabService(repo).list_words(user.id, limit=limit, offset=offset)
    return VocabListResponse(
        words=[_word_out(word) for word in page.words],
        total=page.total,
        due=page.due,
    )


@router.post("")
async def add_vocab(
    body: VocabAddRequest,
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> dict[str, Any]:
    """Добавляет слово идемпотентно: повтор возвращает существующую запись."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    service = VocabService(repo)
    try:
        word, created = await service.add_word(
            user.id,
            body.word,
            translation=body.translation,
            example=body.example,
            lesson_id=body.lesson_id,
        )
    except VocabError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await track_event(
        repo,
        user.id,
        "vocab_word_added",
        {
            "word_id": word.id,
            "word": word.word,
            "lesson_id": word.lesson_id,
            "duplicate": not created,
        },
    )
    return {"word": _word_out(word)}


@router.post("/check", response_model=VocabCheckResponse)
async def check_vocab(
    request: Request,
    body: VocabCheckRequest,
    user_id: int = Depends(get_current_user_id),
    settings=Depends(get_settings_dep),
    repo=Depends(get_repository),
) -> VocabCheckResponse:
    """Проверка перевода и предложения: квота → троттлинг → один LLM-вызов."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        # 502, а не 503: для фронта это «проверка сейчас недоступна».
        raise HTTPException(status_code=502, detail=LLM_ERROR)

    # Квота проверяется ДО вызова: при исчерпанном лимите LLM не дёргаем.
    try:
        await check_quota(repo, settings, user.id)
    except QuotaExceeded:
        raise HTTPException(status_code=429, detail=QUOTA_ERROR)

    throttle = getattr(request.app.state, "action_throttle", None)
    if throttle is not None and not throttle.allow(f"vocab:{user.id}"):
        raise HTTPException(status_code=429, detail=THROTTLE_ERROR)

    service = VocabService(repo, llm=llm)
    guard = getattr(request.app.state, "llm_guard", None)
    try:
        with_guard = guard.slot() if guard is not None else nullcontext()
        async with with_guard:
            result = await service.check(
                user.id,
                body.word_id,
                translation=body.translation,
                sentence=body.sentence,
            )
    except VocabWordNotFound:
        raise HTTPException(status_code=404, detail=WORD_NOT_FOUND_ERROR)
    except VocabLLMUnavailable:
        raise HTTPException(status_code=502, detail=LLM_ERROR)
    except QueueFull:
        logger.warning("Очередь LLM переполнена (vocab): user=%s", user.id)
        raise HTTPException(status_code=429, detail=QUEUE_FULL_ERROR)
    except HTTPException:
        raise
    except VocabParseError:
        logger.warning("Словарь: LLM вернул невалидный JSON: user=%s", user.id)
        raise HTTPException(status_code=502, detail=LLM_ERROR)
    except Exception:
        logger.exception("Словарь: LLM не ответил: user=%s", user.id)
        raise HTTPException(status_code=502, detail=LLM_ERROR)

    try:
        await consume_quota(repo, settings, user.id)
    except QuotaExceeded:
        logger.warning("Словарь: гонка квоты при списании user=%s", user.id)

    await track_event(
        repo,
        user.id,
        "vocab_check",
        {
            "word_id": body.word_id,
            "score": result.score,
            "translation_ok": result.translation_ok,
            "sentence_ok": result.sentence_ok,
        },
    )
    return VocabCheckResponse(
        translation_ok=result.translation_ok,
        sentence_ok=result.sentence_ok,
        score=result.score,
        feedback=result.feedback,
        improved=result.improved,
    )


@router.delete("/{word_id}")
async def delete_vocab(
    word_id: int,
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> dict[str, bool]:
    """Удаляет слово пользователя; чужое или несуществующее → 404."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    try:
        await VocabService(repo).delete_word(user.id, word_id)
    except VocabWordNotFound:
        raise HTTPException(status_code=404, detail=WORD_NOT_FOUND_ERROR)
    return {"ok": True}
