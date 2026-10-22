"""Аутентификация web-продукта: email+пароль (основной вход) и Telegram (legacy).

* ``POST /api/auth/register`` — регистрация по email с паролем.
* ``POST /api/auth/login`` — вход по email и паролю.
* ``POST /api/auth/logout`` — выход (сбрасывает cookie сессии).
* ``POST /api/auth/tg`` — legacy-вход через Telegram Login Widget: оставлен, чтобы
  не потерять прогресс старых пользователей. Новые аккаунты создаются по email.

Сессия живёт в HttpOnly-cookie ``adapteng_session``; JWT внутри — по внутреннему
``users.id``, поэтому идентичность больше не привязана к Telegram.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.analytics import track_event
from core.config import Settings
from core.tg_auth import verify_login_widget
from storage.repo import Repository, UserProfile

from ..deps import build_user_public, get_repository, get_settings_dep
from ..schemas import (
    AuthResponse,
    GUEST_GOAL_LABELS,
    LoginRequest,
    RegisterRequest,
    TelegramUserAuth,
    UserPublic,
    normalize_guest_profile,
)
from ..security import (
    clear_guest_cookie,
    clear_session_cookie,
    create_access_token,
    decode_guest_profile,
    hash_password,
    password_problem,
    require_secret,
    set_session_cookie,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Сколько неудачных попыток входа с одного email за окно.
LOGIN_ATTEMPTS_LIMIT = 10
LOGIN_ATTEMPT_WINDOW_SEC = 300.0

_login_failures: dict[str, list[float]] = {}


def _now() -> float:
    import time

    return time.time()


def _login_allowed(email: str) -> bool:
    """Простой антибрутфорс: не больше N неудачных попыток на email за окно."""
    now = _now()
    attempts = [t for t in _login_failures.get(email, []) if now - t < LOGIN_ATTEMPT_WINDOW_SEC]
    _login_failures[email] = attempts
    return len(attempts) < LOGIN_ATTEMPTS_LIMIT


def _register_failure(email: str) -> None:
    _login_failures.setdefault(email, []).append(_now())


def _clear_failures(email: str) -> None:
    _login_failures.pop(email, None)


def _guest_profile(request: Request, settings: Settings) -> dict | None:
    """Валидный гостевой профиль из подписанной cookie (или ``None``)."""
    token = request.cookies.get(settings.guest_cookie_name)
    return normalize_guest_profile(decode_guest_profile(settings, token))


@router.post("/register", response_model=AuthResponse)
async def register(
    body: RegisterRequest,
    response: Response,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> AuthResponse:
    """Регистрация по email. Создаёт пользователя без Telegram-привязки."""
    require_secret(settings)

    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    existing = await repo.get_user_by_email(body.email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Этот email уже зарегистрирован")

    user = await repo.create_email_user(
        email=body.email,
        password_hash=hash_password(body.password),
        username=body.name or None,
        first_name=body.name or None,
    )

    guest = _guest_profile(request, settings)
    if guest is not None:
        # Переносим гостевые ответы в профиль, не теряя уже существующие поля.
        profile = await repo.get_profile(user.id) or UserProfile(user_id=user.id)
        profile.goal = GUEST_GOAL_LABELS[guest["goal"]]
        profile.minutes_per_day = guest["minutes"]
        profile.self_level = guest["level"]
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        await repo.save_profile(profile)
        await track_event(
            repo,
            user.id,
            "guest_profile_merged",
            {"goal": guest["goal"], "minutes": guest["minutes"], "level": guest["level"]},
        )
        clear_guest_cookie(response, settings)

    profile = await repo.get_profile(user.id)
    public = await build_user_public(repo, user, profile, settings)

    await track_event(repo, user.id, "user_registered")
    await track_event(repo, user.id, "user_login")

    token = create_access_token(settings, user.id)
    set_session_cookie(response, settings, token)
    return AuthResponse(token=token, user=UserPublic(**public))


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> AuthResponse:
    """Вход по email и паролю."""
    require_secret(settings)

    email = body.email.strip().lower()
    if not _login_allowed(email):
        raise HTTPException(status_code=429, detail="Слишком много попыток входа. Попробуй позже")

    user = await repo.get_user_by_email(email)
    account = await repo.get_auth_account(user.id) if user else None
    if user is None or account is None or not verify_password(body.password, account.password_hash):
        _register_failure(email)
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    _clear_failures(email)

    profile = await repo.get_profile(user.id)
    public = await build_user_public(repo, user, profile, settings)
    await track_event(repo, user.id, "user_login")

    token = create_access_token(settings, user.id)
    set_session_cookie(response, settings, token)
    return AuthResponse(token=token, user=UserPublic(**public))


@router.post("/logout")
async def logout(response: Response, settings: Settings = Depends(get_settings_dep)) -> dict[str, bool]:
    """Выход: сбрасывает cookie сессии."""
    clear_session_cookie(response, settings)
    return {"ok": True}


@router.post("/tg", response_model=AuthResponse)
async def auth_tg(
    body: TelegramUserAuth,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> AuthResponse:
    """Legacy-вход через Telegram Login Widget (перенос прогресса старых юзеров)."""
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

    await track_event(repo, user.id, "user_login")

    token = create_access_token(settings, user.id)
    set_session_cookie(response, settings, token)
    return AuthResponse(token=token, user=UserPublic(**public))
