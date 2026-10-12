"""GET /api/me и PUT /api/me/character — профиль авторизованного пользователя."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from core.characters import character_localized, get_character, list_characters
from core.config import Settings
from storage.repo import Repository, UserProfile

from ..deps import (
    build_user_public,
    get_current_tg_id,
    get_repository,
    get_settings_dep,
    resolve_locale,
)
from ..schemas import CharacterSetResponse, MeResponse, SetCharacterRequest, UserPublic

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


@router.put("/me/character", response_model=CharacterSetResponse)
async def set_character(
    body: SetCharacterRequest,
    request: Request,
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
) -> CharacterSetResponse:
    valid_ids = {character.id for character in list_characters()}
    if body.character_id not in valid_ids:
        raise HTTPException(status_code=400, detail="Такого персонажа нет")

    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    profile = await repo.get_profile(user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
    profile.character = body.character_id
    profile.updated_at = datetime.now(timezone.utc).isoformat()
    await repo.save_profile(profile)

    locale = resolve_locale(request)
    character_view = character_localized(get_character(body.character_id), locale)
    return CharacterSetResponse(character=character_view)