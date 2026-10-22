"""Гостевой онбординг до регистрации.

Гость отвечает на 3 вопроса (цель, минуты в день, уровень). Ответы живут в
подписанной HttpOnly-cookie ``adapteng_guest`` — без серверного состояния и без
авторизации. При регистрации значения переносятся в профиль пользователя
(см. ``api/routers/auth.py``).

* ``GET /api/guest/profile`` — текущий гостевой профиль или ``null``.
* ``POST /api/guest/profile`` — сохранить ответы (ставит cookie).
* ``DELETE /api/guest/profile`` — сбросить гостевой профиль.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from core.config import Settings

from ..deps import get_settings_dep
from ..schemas import (
    GuestProfileIn,
    GuestProfileOut,
    GuestProfileResponse,
    normalize_guest_profile,
)
from ..security import clear_guest_cookie, decode_guest_profile, set_guest_cookie

router = APIRouter(prefix="/api/guest", tags=["guest"])


def guest_profile_from_request(request: Request, settings: Settings) -> dict | None:
    """Читает гостевую cookie и возвращает валидный профиль (или ``None``)."""
    token = request.cookies.get(settings.guest_cookie_name)
    return normalize_guest_profile(decode_guest_profile(settings, token))


@router.get("/profile", response_model=GuestProfileResponse)
async def get_guest_profile(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> GuestProfileResponse:
    """Гостевой профиль из cookie; битая/протухшая cookie → ``null`` без ошибки."""
    profile = guest_profile_from_request(request, settings)
    if profile is None:
        return GuestProfileResponse(profile=None)
    return GuestProfileResponse(profile=GuestProfileOut(**profile))


@router.post("/profile", response_model=GuestProfileResponse)
async def save_guest_profile(
    body: GuestProfileIn,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> GuestProfileResponse:
    """Валидирует ответы онбординга и кладёт их в подписанную cookie."""
    profile = body.model_dump()
    set_guest_cookie(response, settings, profile)
    return GuestProfileResponse(profile=GuestProfileOut(**profile))


@router.delete("/profile")
async def delete_guest_profile(
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, bool]:
    """Сбрасывает гостевую cookie."""
    clear_guest_cookie(response, settings)
    return {"ok": True}
