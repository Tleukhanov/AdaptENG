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

from ..deps import current_user, get_current_user_id, get_repository, get_settings_dep

router = APIRouter(prefix="/api", tags=["analytics"])


async def _require_admin(user, settings) -> None:
    """Доступ только администратору (email из ADMIN_EMAILS или Telegram-ADMIN_TG_ID)."""
    admin_id = int(getattr(settings, "admin_tg_id", 0) or 0)
    admin_emails = {
        item.strip().lower()
        for item in (getattr(settings, "admin_emails", "") or "").split(",")
        if item.strip()
    }
    if admin_id <= 0 and not admin_emails:
        raise HTTPException(status_code=404, detail="Админ-метрики выключены")
    if user.tg_id and admin_id and user.tg_id == admin_id:
        return
    if user.email and user.email.lower() in admin_emails:
        return
    raise HTTPException(status_code=403, detail="Нужен доступ администратора")


@router.get("/analytics/me")
async def analytics_me(
    user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Отчёт о прогрессе: результат обучения, а не «сколько раз зашёл»."""
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    data = await collect_user_learning(repo, user.id)
    return learning_report(data)


@router.get("/admin/analytics")
async def admin_analytics(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings=Depends(get_settings_dep),
    days: int = Query(default=30, ge=1, le=180),
) -> dict[str, Any]:
    """Воронка и когорты: сколько людей дошло до первого урока и вернулось."""
    admin = await current_user(repo, user_id)
    await _require_admin(admin, settings)

    funnel = await funnel_summary(repo, days=days)
    cohorts = await learning_cohort_summary(repo, limit=25)
    return {
        "funnel": funnel,
        "cohorts": cohorts,
        "cohort_size": len(cohorts),
        "note": "Денежные метрики сознательно не считаем — проверяем продуктовую ценность.",
    }