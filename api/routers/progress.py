"""Прогресс и SRS-повторение (web-продукт, Phase C).

GET /api/progress — агрегированный прогресс + тема следующего урока и число
слов к повтору. GET /api/review/due и POST /api/review/answer — работа с
очередью spaced repetition. Логика — из ``core``/``storage``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from core.achievements import check_achievements, get_level_for_xp, get_next_level
from core.lesson_plan import LessonPlan, next_plan_index
from core.progress import ProgressService
from core.srs import SRSService

from ..deps import current_user, get_current_user_id, get_repository
from ..schemas import (
    AchievementItem,
    AchievementsResponse,
    LeaderboardEntry,
    LevelInfo,
    ProgressResponse,
    ReviewAnswerRequest,
    ReviewDueWord,
)

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
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> ProgressResponse:
    """Прогресс авторизованного пользователя + next_topic + due_words."""
    user = await current_user(repo, user_id)
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
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> list[ReviewDueWord]:
    """Слова SRS, готовые к повторению (до 10)."""
    user = await current_user(repo, user_id)
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
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> dict[str, Any]:
    """Обновляет интервал повторения слова по SM-2. 404, если слова нет."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    srs = SRSService(repo)
    existing = await srs.get_word_by_id(body.word_id)
    if existing is None or existing.user_id != user.id:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    await srs.review(body.word_id, body.quality)
    return {"ok": True}


@router.get("/achievements", response_model=AchievementsResponse)
async def achievements(
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> AchievementsResponse:
    """Все достижения пользователя (earned=True/False) + уровень по XP."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    data = await ProgressService(repo).get_progress(user.id, level=user.level)
    level_name, level_emoji = get_level_for_xp(data.xp)
    next_level, xp_needed = get_next_level(data.xp)
    return AchievementsResponse(
        level=LevelInfo(
            name=level_name,
            emoji=level_emoji,
            xp=data.xp,
            next_level=next_level,
            xp_needed=xp_needed,
        ),
        achievements=[
            AchievementItem(
                id=a.id,
                name=a.name,
                emoji=a.emoji,
                description=a.description,
                condition=a.condition,
                earned=a.earned,
            )
            for a in check_achievements(data)
        ],
    )


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def leaderboard(
    limit: int = Query(default=20, ge=1, le=50),
    user_id: int = Depends(get_current_user_id),
    repo=Depends(get_repository),
) -> list[LeaderboardEntry]:
    """Топ пользователей по XP."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    rows = await repo.get_leaderboard(limit=limit)
    return [
        LeaderboardEntry(
            user_id=r.user_id,
            username=r.username,
            first_name=r.first_name,
            level=r.level,
            xp=r.xp,
            total_lessons=r.total_lessons,
            streak_days=r.streak_days,
        )
        for r in rows
    ]
