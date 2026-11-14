"""Админ-панель: управление пользователями.

* ``GET /api/admin/users`` — список пользователей с фильтрами и пагинацией
* ``GET /api/admin/users/{user_id}`` — детальная страница пользователя
* ``PUT /api/admin/users/{user_id}/subscription`` — выдать/продлить подписку
* ``PUT /api/admin/users/{user_id}/block`` — заблокировать/разблокировать
* ``DELETE /api/admin/users/{user_id}`` — мягкое удаление (блокировка)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.config import Settings
from storage.repo import Repository, Subscription, UserRow

from ..deps import (
    current_user,
    get_current_user_id,
    get_repository,
    get_settings_dep,
    require_admin,
)
from ..schemas import (
    BlockToggleRequest,
    SubscriptionGrantRequest,
    UserDetailResponse,
    UserListItem,
    UserListResponse,
)

router = APIRouter(prefix="/api", tags=["admin"])

# Потолок выборки для фильтра по подписке: фильтрация идёт в памяти,
# поэтому сначала грузим страницу целиком, а потом режем на limit/offset.
_FILTER_CAP = 500


def _subscription_status(sub: Subscription | None) -> str:
    if sub is None:
        return "none"
    return "active" if sub.is_active else "expired"


def _to_item(user: UserRow, sub: Subscription | None) -> UserListItem:
    """Собирает строку таблицы строго из реальных полей ``UserRow``."""
    return UserListItem(
        id=user.id,
        tg_id=user.tg_id,
        username=user.username,
        first_name=user.first_name,
        email=user.email or "",
        level=user.level,
        is_unlimited=user.is_unlimited,
        blocked=user.blocked,
        email_verified_at=user.email_verified_at,
        reminders_enabled=user.reminders_enabled,
        created_at=user.created_at,
        subscription_status=_subscription_status(sub),
        subscription_expires_at=sub.expires_at if sub else None,
    )


async def _require_admin(
    repo: Repository,
    admin_user_id: int,
    settings: Settings,
) -> None:
    admin = await current_user(repo, admin_user_id)
    await require_admin(admin, settings)


@router.get("/admin/users", response_model=UserListResponse)
async def admin_list_users(
    request: Request,
    admin_user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dep),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    subscription: str | None = Query(default=None, pattern="^(active|expired|none)$"),
) -> UserListResponse:
    """Список пользователей с фильтрами и пагинацией."""
    await _require_admin(repo, admin_user_id, settings)

    if subscription is not None:
        # Фильтр по статусу подписки: грузим выборку, фильтруем, затем пагинируем.
        candidates = await repo.admin_list_users(
            limit=min(_FILTER_CAP, limit + offset + _FILTER_CAP),
            offset=0,
            search=search,
        )
        matched: list[UserListItem] = []
        for user in candidates:
            sub = await repo.get_subscription(user.id)
            item = _to_item(user, sub)
            if item.subscription_status == subscription:
                matched.append(item)
        total = len(matched)
        page = matched[offset : offset + limit]
        return UserListResponse(users=page, total=total, limit=limit, offset=offset)

    users = await repo.admin_list_users(limit=limit, offset=offset, search=search)
    total = await repo.admin_count_users(search=search)

    items = [
        _to_item(user, await repo.get_subscription(user.id))
        for user in users
    ]
    return UserListResponse(users=items, total=total, limit=limit, offset=offset)


@router.get("/admin/users/{user_id}", response_model=UserDetailResponse)
async def admin_get_user(
    user_id: int,
    request: Request,
    admin_user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dep),
) -> UserDetailResponse:
    """Детальная страница пользователя в админ-панели."""
    await _require_admin(repo, admin_user_id, settings)

    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    sub = await repo.get_subscription(user.id)
    stats = await repo.get_stats(user.id)

    return UserDetailResponse(
        user=_to_item(user, sub),
        stats={
            "total_turns": stats.total_turns,
            "correct": stats.correct,
            "errors": stats.errors,
            "top_categories": stats.top_categories,
        },
        subscription=(
            {
                "plan_days": sub.plan_days,
                "granted_at": sub.granted_at,
                "expires_at": sub.expires_at,
                "is_active": sub.is_active,
            }
            if sub
            else None
        ),
        recent_activity=[],
    )


@router.put("/admin/users/{user_id}/subscription")
async def admin_grant_subscription(
    user_id: int,
    body: SubscriptionGrantRequest,
    request: Request,
    admin_user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Выдать или продлить подписку пользователю."""
    await _require_admin(repo, admin_user_id, settings)

    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    sub = await repo.grant_subscription(user.id, body.plan_days)
    if sub is None:
        raise HTTPException(status_code=500, detail="Не удалось выдать подписку")

    return {
        "ok": True,
        "expires_at": sub.expires_at,
        "plan_days": sub.plan_days,
    }


@router.put("/admin/users/{user_id}/block")
async def admin_block_user(
    user_id: int,
    body: BlockToggleRequest,
    request: Request,
    admin_user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Заблокировать или разблокировать пользователя."""
    await _require_admin(repo, admin_user_id, settings)

    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await repo.set_blocked(user_id, body.blocked)

    return {"ok": True, "blocked": body.blocked}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    request: Request,
    admin_user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Мягкое удаление пользователя (блокировка)."""
    await _require_admin(repo, admin_user_id, settings)

    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await repo.set_blocked(user_id, True)
    return {"ok": True, "deleted": True, "note": "Аккаунт заблокирован (мягкое удаление)"}
