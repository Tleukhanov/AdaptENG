"""Диагностика уровня CEFR (web-продукт, онбординг).

POST /api/diagnostic/start — «лестница» из 6 заданий через LLM
(``core.diagnostic``). POST /api/diagnostic/finish — ответы студента и оценка
уровня A1..C1 с обоснованием; при сбое LLM — эвристика по длине ответов.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.diagnostic import (
    DiagnosticService,
    DiagnosticTask,
    estimate_level_heuristic,
)
from storage.repo import Repository

from ..deps import get_current_tg_id, get_llm, get_repository, get_settings_dep
from ..quota import QuotaExceeded, check_quota, consume_quota
from ..schemas import (
    DiagnosticFinishRequest,
    DiagnosticFinishResponse,
    DiagnosticStartResponse,
    DiagnosticTaskOut,
)

router = APIRouter(prefix="/api", tags=["diagnostic"])

logger = logging.getLogger(__name__)


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
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
    settings=Depends(get_settings_dep),
    llm=Depends(get_llm),
) -> DiagnosticStartResponse:
    """Генерирует 6 заданий разной сложности для определения уровня."""
    user = await _user_or_401(repo, tg_id)
    service = _service(llm)
    try:
        await check_quota(repo, settings, user.id)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    try:
        tasks = await service.generate_tasks()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось сгенерировать задания") from exc

    await consume_quota(repo, settings, user.id)
    return DiagnosticStartResponse(
        tasks=[DiagnosticTaskOut(text=t.text, level_hint=t.level_hint) for t in tasks]
    )


@router.post("/diagnostic/finish", response_model=DiagnosticFinishResponse)
async def finish(
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
        try:
            assessment = await service.assess(questions, answers)
            await consume_quota(repo, settings, user.id)
            return DiagnosticFinishResponse(
                level=assessment.level,
                confidence=assessment.confidence,
                explanation_ru=assessment.explanation_ru,
                strengths=assessment.strengths,
                weaknesses=assessment.weaknesses,
                recommendation=assessment.recommendation,
            )
        except Exception:
            logger.warning("Диагностика: LLM-оценка не удалась", exc_info=True)

    level = estimate_level_heuristic(answers)
    return DiagnosticFinishResponse(
        level=level,
        confidence=0.3,
        explanation_ru="Уровень оценён по объёму ответов: пройди мини-тест ещё раз для точности.",
        strengths=[],
        weaknesses=[],
        recommendation="",
    )
