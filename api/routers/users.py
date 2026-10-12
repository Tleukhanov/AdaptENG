"""GET /api/me — профиль авторизованного пользователя."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.characters import character_localized, get_character
from core.config import Settings
from storage.repo import Repository

from ..deps import (
    build_user_public,
    get_current_tg_id,
    get_repository,
    get_settings_dep,
    resolve_locale,
)
from ..schemas import MeResponse, UserPublic

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    tg_id: int = Depends(get_current_tg_id),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> MeResponse:
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Пользователь не найден")

    profile = await repo.get_profile(user.id)
    stats = await repo.get_stats(user.id)
    public = await build_user_public(repo, user, profile, settings, stats)

    locale = resolve_locale(request)
    char_id = profile.character if profile and profile.character else "default"
    character_view = character_localized(get_character(char_id), locale)

    return MeResponse(user=UserPublic(**public), character=character_view)