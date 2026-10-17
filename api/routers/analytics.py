"""Аналитика: персональный отчёт обучения и продуктовая воронка.

* ``GET /api/analytics/me`` — честный прогресс ученика: точность по неделям
  (было/стало), удержание слов на интервалах SRS, серия, рост уровня.
* ``GET /api/admin/analytics`` — воронка и когорты (только для ADMIN_TG_ID).

Денежных метрик сознательно нет: сейчас задача — проверить, есть ли смысл
продолжать, а не считать выручку.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.learning_metrics import (
    collect_user_learning,
    funnel_summary,
    learning_cohort_summary,
    learning_report,
)
from storage.repo import Repository

from ..deps import get_current_tg_id, get_repository, get_settings_dep

router = APIRouter(prefix="/api", tags=["analytics"])


async def _require_admin(tg_id: int, settings) -> None:
    """Доступ только владельцу (ADMIN_TG_ID)."""
    admin_id = int(getattr(settings, "admin_tg_id", 0) or 0)
    if admin_id <= 0:
        raise HTTPException(status_code=404, detail="Админ-метрики выключены")
    if tg_id != admin_id:
        raise HTTPException(status_code=403, detail="Нужен доступ администратора")


@router.get("/analytics/me")
async def analytics_me(
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Отчёт о прогрессе: результат обучения, а не «сколько раз зашёл»."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    data = await collect_user_learning(repo, user.id)
    return learning_report(data)


@router.get("/admin/analytics")
async def admin_analytics(
    request: Request,
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
    settings=Depends(get_settings_dep),
    days: int = Query(default=30, ge=1, le=180),
) -> dict[str, Any]:
    """Воронка и когорты: сколько людей дошло до первого урока и вернулось."""
    await _require_admin(tg_id, settings)

    funnel = await funnel_summary(repo, days=days)
    cohorts = await learning_cohort_summary(repo, limit=25)
    return {
        "funnel": funnel,
        "cohorts": cohorts,
        "cohort_size": len(cohorts),
        "note": "Денежные метрики сознательно не считаем — проверяем продуктовую ценность.",
    }