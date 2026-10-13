"""Прогресс и SRS-повторение (web-продукт, Phase C).

GET /api/progress — агрегированный прогресс + тема следующего урока и число
слов к повтору. GET /api/review/due и POST /api/review/answer — работа с
очередью spaced repetition. Логика — из ``core``/``storage``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.lesson_plan import LessonPlan, next_plan_index
from core.progress import ProgressService
from core.srs import SRSService

from ..deps import get_current_tg_id, get_repository
from ..schemas import ProgressResponse, ReviewAnswerRequest, ReviewDueWord

router = APIRouter(prefix="/api", tags=["progress"])


async def _next_topic(repo, user) -> str:
    """Тема следующего урока из плана (без LLM). Пустая строка — плана нет."""
    try:
        completed = await repo.count_finished_lessons(user.id)
        row = await repo.get_lesson_plan(user.id)
        if row is None:
            return ""
        plan = LessonPlan.from_json(row.plan_json)
        idx = next_plan_index(row.based_on_lessons, completed, row.horizon)
        if idx is None or idx >= len(plan.lessons):
            return ""
        return plan.lessons[idx].topic
    except Exception:
        return ""


@router.get("/progress", response_model=ProgressResponse)
async def progress(
    tg_id: int = Depends(get_current_tg_id),
    repo=Depends(get_repository),
) -> ProgressResponse:
    """Прогресс авторизованного пользователя + next_topic + due_words."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    data = await ProgressService(repo).get_progress(user.id, level=user.level)
    next_topic = await _next_topic(repo, user)
    due = await SRSService(repo).get_due_words(user.id, limit=100)

    payload: dict[str, Any] = dict(data.__dict__)
    payload["level"] = data.level or "—"
    payload["next_topic"] = next_topic
    payload["due_words"] = len(due)
    return ProgressResponse(**payload)


@router.get("/review/due", response_model=list[ReviewDueWord])
async def review_due(
    tg_id: int = Depends(get_current_tg_id),
    repo=Depends(get_repository),
) -> list[ReviewDueWord]:
    """Слова SRS, готовые к повторению (до 10)."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    words = await SRSService(repo).get_due_words(user.id, limit=10)
    return [
        ReviewDueWord(id=w.id, word=w.word, translation=w.translation, example=w.example)
        for w in words
    ]


@router.post("/review/answer")
async def review_answer(
    body: ReviewAnswerRequest,
    tg_id: int = Depends(get_current_tg_id),
    repo=Depends(get_repository),
) -> dict[str, Any]:
    """Обновляет интервал повторения слова по SM-2. 404, если слова нет."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    srs = SRSService(repo)
    existing = await srs.get_word_by_id(body.word_id)
    if existing is None or existing.user_id != user.id:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    await srs.review(body.word_id, body.quality)
    return {"ok": True}
