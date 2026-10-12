"""Дневная квота LLM для web-продукта AdaptENG.

Дублирует логику бота (bot/quota.py) без импорта из ``bot`` — api должен
оставаться независимым каналом. Двухшаговый контроль::

    await check_quota(repo, settings, user_id)   # бросит QuotaExceeded
    result = await practice.analyze(...)          # LLM-вызов
    await consume_quota(repo, settings, user_id)  # списание после успеха

Для unlimited-пользователей и активной подписки квота бесплатна (no-op).
"""

from __future__ import annotations

from datetime import date

from core.config import Settings
from storage.repo import Repository


class QuotaExceeded(Exception):
    """Дневной лимит LLM-действий пользователя исчерпан."""


def _today() -> str:
    return date.today().isoformat()


async def _is_exempt(repo: Repository, settings: Settings, user_id: int) -> bool:
    """Пользователь не тратит квоту: промокод-безлимит или активная подписка."""
    if await repo.get_unlimited_status(user_id):
        return True
    sub = await repo.get_subscription(user_id)
    if sub is not None and sub.is_active:
        return True
    return False


async def check_quota(repo: Repository, settings: Settings, user_id: int) -> None:
    """Предпроверка бюджета без мутаций. Бросает QuotaExceeded, если лимит исчерпан."""
    if settings.llm_daily_limit <= 0:
        return
    if await _is_exempt(repo, settings, user_id):
        return
    used = await repo.get_llm_usage(user_id, _today())
    if used >= settings.llm_daily_limit:
        raise QuotaExceeded(f"квота исчерпана: {used}/{settings.llm_daily_limit}")


async def consume_quota(repo: Repository, settings: Settings, user_id: int) -> None:
    """Списывает одну единицу квоты после успешного LLM-вызова (no-op для exempt)."""
    if settings.llm_daily_limit <= 0:
        return
    if await _is_exempt(repo, settings, user_id):
        return
    await repo.increment_llm_usage(user_id, _today(), 1)
