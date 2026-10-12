"""Pydantic-схемы REST API AdaptENG."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TelegramUserAuth(BaseModel):
    """Объект пользователя, приходящий с Telegram Login Widget."""

    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    photo_url: str = ""
    auth_date: int = 0
    hash: str = ""


class AuthResponse(BaseModel):
    token: str
    user: "UserPublic"


class UserPublic(BaseModel):
    id: int
    tg_id: int
    username: str = ""
    first_name: str = ""
    level: str | None = None
    character: str = ""
    interests: list[str] = Field(default_factory=list)
    quota_left: int | None = None
    quota_total: int | None = None
    llm_daily_limit: int = 0
    is_unlimited: bool = False
    total_turns: int = 0
    correct: int = 0
    errors: int = 0


class MeResponse(BaseModel):
    user: UserPublic
    character: dict[str, object] | None = None


class CharacterPublic(BaseModel):
    id: str
    emoji: str
    voice: str
    avatar: str
    palette: list[str]
    name: str
    description: str
    tagline: str = ""
    backstory: str = ""


class HealthResponse(BaseModel):
    ok: bool = True


class ApiError(BaseModel):
    ok: bool = False
    error: str