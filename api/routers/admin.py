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
from storage.repo import Repository

from ..deps import (
    build_user_public,
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


def _subscription_status(sub) -> str:
    if sub is None:
        return "none"
    return "active" if sub.is_active else "expired"


@router.get("/admin/users", response_model=UserListResponse)
async def admin_list_users(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dep),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    subscription: str | None = Query(default=None, pattern="^(active|expired|none)$"),
) -> UserListResponse:
    """Список пользователей с фильтрами и пагинацией."""
    admin = await current_user(repo, admin_user_id)
    await require_admin(admin, settings)

    users = await repo.admin_list_users(limit=limit, offset=offset, search=search)
    total = await repo.admin_count_users(search=search)

    # Грузим подписки всем пользователям списка за один запрос
    subs = await repo.get_all_subscriptions()
    subs_by_user = {s.user_id: s for s in subs}

    items: list[UserListItem] = []
    for u in users:
        sub = subs_by_user.get(u.id)
        status = _subscription_status(sub)

        if subscription is not None and status != subscription:
            continue

        items.append(
            UserListItem(
                id=u.id,
                tg_id=u.tg_id,
                username=u.username,
                first_name=u.first_name,
                email=u.email or "",
                level=u.level,
                character=u.character,
                interests=u.interests or [],
                quota_left=u.quota_left,
                quota_total=u.quota_total,
                llm_daily_limit=u.llm_daily_limit,
                is_unlimited=u.is_unlimited,
                blocked=u.blocked,
                created_at=u.created_at,
                last_activity=None,
                subscription_status=status,
                subscription_expires_at=sub.expires_at if sub else None,
            )
        )

    return UserListResponse(
        users=items,
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.get("/admin/users/{user_id}", response_model=UserDetailResponse)
async def admin_get_user(
    user_id: int,
    request: Request,
    admin_user_id: int = Depends(get_current_user_id),
    repo: Repository = Depends(get_repository),
    settings: Settings = Depends(get_settings_dep),
) -> UserDetailResponse:
    """Детальная страница пользователя в админ-панели."""
    admin = await current_user(repo, admin_user_id)
    await require_admin(admin, settings)

    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    sub = await repo.get_subscription(user.id)
    stats = await repo.get_stats(user.id)

    return UserDetailResponse(
        user=UserListItem(
            id=user.id,
            tg_id=user.tg_id,
            username=user.username,
            first_name=user.first_name,
            email=user.email or "",
            level=user.level,
            character=user.character,
            interests=user.interests or [],
            quota_left=user.quota_left,
            quota_total=user.quota_total,
            llm_daily_limit=user.llm_daily_limit,
            is_unlimited=user.is_unlimited,
            blocked=user.blocked,
            created_at=user.created_at,
            last_activity=None,
            subscription_status=_subscription_status(sub),
            subscription_expires_at=sub.expires_at if sub else None,
        ),
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
    admin = await current_user(repo, admin_user_id)
    await require_admin(admin, settings)

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
    admin = await current_user(repo, admin_user_id)
    await require_admin(admin, settings)

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
    admin = await current_user(repo, admin_user_id)
    await require_admin(admin, settings)

    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await repo.set_blocked(user_id, True)
    return {"ok": True, "deleted": True, "note": "Аккаунт заблокирован (мягкое удаление)"}