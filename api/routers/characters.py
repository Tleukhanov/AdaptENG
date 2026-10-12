"""GET /api/characters — витрина AI-персонажей (локализована)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from core.characters import list_characters_localized

from ..deps import resolve_locale
from ..schemas import CharacterPublic

router = APIRouter(prefix="/api/characters", tags=["characters"])


@router.get("", response_model=list[CharacterPublic])
async def characters(request: Request) -> list[CharacterPublic]:
    locale = resolve_locale(request)
    return [CharacterPublic(**item) for item in list_characters_localized(locale)]