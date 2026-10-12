"""POST /api/auth/tg — вход через Telegram Login Widget.

Виджет присылает подписанный объект пользователя; сервер проверяет HMAC
(core.tg_auth) и выпускает JWT. Несуществующий пользователь создаётся —
так прогресс из бота (тот же tg_id) подхватывается автоматически.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.config import Settings
from core.tg_auth import verify_login_widget
from storage.repo import Repository

from ..deps import build_user_public, get_repository, get_settings_dep
from ..schemas import AuthResponse, TelegramUserAuth, UserPublic
from ..security import create_access_token, require_secret

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/tg", response_model=AuthResponse)
async def auth_tg(
    body: TelegramUserAuth,
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> AuthResponse:
    require_secret(settings)

    payload = body.model_dump(exclude_unset=True)
    if settings.api_insecure_auth:
        verified = payload
    else:
        verified = verify_login_widget(settings.telegram_bot_token, payload)
        if verified is None:
            raise HTTPException(status_code=401, detail="Подпись Telegram-виджета не прошла проверку")

    tg_id = int(verified["id"])
    username = verified.get("username") or None
    first_name = verified.get("first_name") or None

    user = await repo.get_or_create_user(tg_id, username=username, first_name=first_name)
    profile = await repo.get_profile(user.id)
    public = await build_user_public(repo, user, profile, settings)

    token = create_access_token(settings, tg_id)
    return AuthResponse(token=token, user=UserPublic(**public))