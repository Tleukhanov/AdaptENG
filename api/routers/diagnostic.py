"""Диагностика уровня CEFR (web-продукт, онбординг).

POST /api/diagnostic/start — «лестница» из 6 заданий через LLM
(``core.diagnostic``). POST /api/diagnostic/finish — ответы студента и оценка
уровня A1..C1 с обоснованием; при сбое LLM — эвристика по длине ответов.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from core.analytics import track_event
from core.diagnostic import (
    DiagnosticService,
    DiagnosticTask,
    estimate_level_heuristic,
)
from storage.repo import Repository

from ..deps import get_current_tg_id, get_llm, get_repository, get_settings_dep
from ..loadguard import QueueFull
from ..quota import QuotaExceeded, check_quota, consume_quota
from ..schemas import (
    DiagnosticFinishRequest,
    DiagnosticFinishResponse,
    DiagnosticStartResponse,
    DiagnosticTaskOut,
)

router = APIRouter(prefix="/api", tags=["diagnostic"])

logger = logging.getLogger(__name__)

QUEUE_FULL_ERROR = "Сейчас много запросов — очередь переполнена, попробуй через минуту"


async def _user_or_401(repo: Repository, tg_id: int):
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def _service(llm) -> DiagnosticService:
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM не настроен")
    return DiagnosticService(llm)


@router.post("/diagnostic/start", response_model=DiagnosticStartResponse)
async def start(
    request: Request,
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
    settings=Depends(get_settings_dep),
    llm=Depends(get_llm),
) -> DiagnosticStartResponse:
    """Генерирует 6 заданий разной сложности для определения уровня."""
    user = await _user_or_401(repo, tg_id)
    service = _service(llm)
    throttle = getattr(request.app.state, "action_throttle", None)
    if throttle is not None and not throttle.allow(f"diag:{user.id}"):
        raise HTTPException(status_code=429, detail=QUEUE_FULL_ERROR)
    try:
        await check_quota(repo, settings, user.id)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    guard = getattr(request.app.state, "llm_guard", None)
    try:
        if guard is not None:
            try:
                async with guard.slot():
                    tasks = await service.generate_tasks()
            except QueueFull:
                logger.warning("Очередь LLM переполнена (diagnostic): user=%s", user.id)
                raise HTTPException(status_code=429, detail=QUEUE_FULL_ERROR)
        else:
            tasks = await service.generate_tasks()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось сгенерировать задания") from exc

    await consume_quota(repo, settings, user.id)
    return DiagnosticStartResponse(
        tasks=[DiagnosticTaskOut(text=t.text, level_hint=t.level_hint) for t in tasks]
    )


@router.post("/diagnostic/finish", response_model=DiagnosticFinishResponse)
async def finish(
    request: Request,
    body: DiagnosticFinishRequest,
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
    settings=Depends(get_settings_dep),
    llm=Depends(get_llm),
) -> DiagnosticFinishResponse:
    """Оценивает уровень CEFR по ответам студента."""
    user = await _user_or_401(repo, tg_id)
    service = _service(llm)

    answers = [a.strip() for a in body.answers]
    filled = [a for a in answers if a]
    if len(filled) < 3:
        raise HTTPException(
            status_code=400,
            detail="Нужно ответить минимум на 3 задания",
        )

    questions = [
        DiagnosticTask(text=t.text, level_hint=t.level_hint) for t in body.tasks
    ] or None

    try:
        await check_quota(repo, settings, user.id)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    if questions:
        guard = getattr(request.app.state, "llm_guard", None)
        try:
            if guard is not None:
                try:
                    async with guard.slot():
                        assessment = await service.assess(questions, answers)
                except QueueFull:
                    logger.warning("Очередь LLM переполнена (diagnostic): user=%s", user.id)
                    raise HTTPException(status_code=429, detail=QUEUE_FULL_ERROR)
            else:
                assessment = await service.assess(questions, answers)
            await consume_quota(repo, settings, user.id)
            await track_event(
                repo,
                user.id,
                "diagnostic_completed",
                {"level": assessment.level, "confidence": assessment.confidence},
            )
            return DiagnosticFinishResponse(
                level=assessment.level,
                confidence=assessment.confidence,
                explanation_ru=assessment.explanation_ru,
                strengths=assessment.strengths,
                weaknesses=assessment.weaknesses,
                recommendation=assessment.recommendation,
            )
        except HTTPException:
            raise
        except Exception:
            logger.warning("Диагностика: LLM-оценка не удалась", exc_info=True)

    level = estimate_level_heuristic(answers)
    await track_event(repo, user.id, "diagnostic_completed", {"level": level, "heuristic": True})
    return DiagnosticFinishResponse(
        level=level,
        confidence=0.3,
        explanation_ru="Уровень оценён по объёму ответов: пройди мини-тест ещё раз для точности.",
        strengths=[],
        weaknesses=[],
        recommendation="",
    )
