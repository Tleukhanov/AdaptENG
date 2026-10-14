"""GET /api/me, PUT /api/me/character и профиль-память студента."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from core.characters import character_localized, get_character, list_characters
from core.config import Settings
from core.lessons import LEVEL_DESCRIPTIONS
from storage.repo import Repository, UserProfile

from ..deps import (
    build_user_public,
    get_current_tg_id,
    get_repository,
    get_settings_dep,
    resolve_locale,
)
from ..schemas import (
    CharacterSetResponse,
    MeResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SetCharacterRequest,
    UserPublic,
)

router = APIRouter(prefix="/api", tags=["users"])


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _join_list(values: list[str]) -> str:
    return ", ".join(item.strip() for item in values if item.strip())


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


@router.get("/me/profile", response_model=ProfileResponse)
async def get_profile(
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
) -> ProfileResponse:
    """Память студента: цель, интересы, формат, заметки, уровень."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    profile = await repo.get_profile(user.id)
    has_profile = bool(
        profile
        and (
            profile.goal
            or profile.interests
            or profile.weak_areas
            or profile.preferred_format
            or profile.notes
        )
    )
    return ProfileResponse(
        goal=profile.goal if profile else "",
        interests=_split_list(profile.interests) if profile else [],
        weak_areas=_split_list(profile.weak_areas) if profile else [],
        preferred_format=profile.preferred_format if profile else "",
        notes=profile.notes if profile else "",
        level=user.level,
        character=profile.character if profile else "",
        has_profile=has_profile,
    )


@router.put("/me/profile", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    tg_id: int = Depends(get_current_tg_id),
    repo: Repository = Depends(get_repository),
) -> ProfileResponse:
    """Сохраняет ответы онбординга: уровень, цель, интересы, формат, заметки."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    profile = await repo.get_profile(user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)

    if body.level is not None:
        candidate = body.level.strip().upper()
        if candidate and candidate not in LEVEL_DESCRIPTIONS:
            raise HTTPException(status_code=400, detail="Уровень должен быть A1..C1")
        await repo.set_level(user.id, candidate)
        user.level = candidate or None

    if body.goal is not None:
        profile.goal = body.goal.strip()
    if body.interests is not None:
        profile.interests = _join_list(body.interests)
    if body.weak_areas is not None:
        profile.weak_areas = _join_list(body.weak_areas)
    if body.preferred_format is not None:
        profile.preferred_format = body.preferred_format
    if body.notes is not None:
        profile.notes = body.notes.strip()

    profile.updated_at = datetime.now(timezone.utc).isoformat()
    await repo.save_profile(profile)

    return ProfileResponse(
        goal=profile.goal,
        interests=_split_list(profile.interests),
        weak_areas=_split_list(profile.weak_areas),
        preferred_format=profile.preferred_format,
        notes=profile.notes,
        level=user.level,
        character=profile.character,
        has_profile=bool(
            profile.goal
            or profile.interests
            or profile.weak_areas
            or profile.preferred_format
            or profile.notes
        ),
    )