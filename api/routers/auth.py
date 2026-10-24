"""Аутентификация web-продукта: email+пароль (основной вход) и Telegram (legacy).

* ``POST /api/auth/register`` — регистрация по email с паролем.
* ``POST /api/auth/login`` — вход по email и паролю.
* ``POST /api/auth/logout`` — выход (сбрасывает cookie сессии).
* ``POST /api/auth/verify/request`` — письмо со ссылкой подтверждения email.
* ``POST /api/auth/verify`` — подтверждение email по токену.
* ``GET /api/auth/verify`` — ссылка из письма (302 на страницу web-продукта).
* ``POST /api/auth/tg`` — legacy-вход через Telegram Login Widget: оставлен, чтобы
  не потерять прогресс старых пользователей. Новые аккаунты создаются по email.

Сессия живёт в HttpOnly-cookie ``adapteng_session``; JWT внутри — по внутреннему
``users.id``, поэтому идентичность больше не привязана к Telegram.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from core.analytics import track_event
from core.config import Settings
from core.email import EmailSender, verification_link
from core.tg_auth import verify_login_widget
from storage.repo import Repository, UserProfile, UserRow

from ..deps import (
    build_user_public,
    get_current_user_id,
    get_email_sender,
    get_repository,
    get_settings_dep,
)
from ..schemas import (
    AuthResponse,
    GUEST_GOAL_LABELS,
    LoginRequest,
    RegisterRequest,
    TelegramUserAuth,
    UserPublic,
    VerifyRequestResponse,
    VerifyResponse,
    VerifyTokenRequest,
    normalize_guest_profile,
)
from ..security import (
    clear_guest_cookie,
    clear_session_cookie,
    create_access_token,
    create_verify_token,
    decode_guest_profile,
    decode_verify_token,
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

#: Не чаще одного письма подтверждения на пользователя за интервал.
VERIFY_RESEND_INTERVAL_SEC = 60.0

_login_failures: dict[str, list[float]] = {}
#: Время (monotonic) последней отправки письма на пользователя — in-memory,
#: как и антибрутфорс входа: на несколько дино лимит действует по-процессно.
_verify_sent_at: dict[int, float] = {}


def _now() -> float:
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


# ---------- подтверждение email ----------


def _verify_retry_after(user_id: int, now: float | None = None) -> int:
    """Сколько секунд осталось до следующей разрешённой отправки (0 — можно)."""
    last = _verify_sent_at.get(user_id)
    if last is None:
        return 0
    elapsed = (now if now is not None else time.monotonic()) - last
    if elapsed >= VERIFY_RESEND_INTERVAL_SEC:
        return 0
    return max(1, int(VERIFY_RESEND_INTERVAL_SEC - elapsed + 0.999))


async def _send_verification(
    repo: Repository,
    sender: EmailSender,
    settings: Settings,
    user: UserRow,
    *,
    count_rate_limit: bool,
) -> tuple[bool, str]:
    """Собирает ссылку и отправляет письмо. Ошибки отправки не пробрасываются.

    Возвращает ``(sent, link)`` — ссылка нужна в dev-режиме (SMTP не настроен),
    чтобы пользователь мог подтвердить email без почты.
    """
    token = create_verify_token(settings, user.id)
    link = verification_link(settings, token)
    if not user.email:
        return False, ""
    try:
        sent = await sender.send_verification(user.email, link)
    except Exception:  # noqa: BLE001 - письмо не должно ломать регистрацию/запрос
        logger.exception("Сбой отправки письма подтверждения (user_id=%s)", user.id)
        sent = False
    if count_rate_limit:
        _verify_sent_at[user.id] = time.monotonic()
    await track_event(
        repo,
        user.id,
        "email_verify_requested",
        {"sent": sent, "resend": count_rate_limit},
    )
    return sent, link


async def _confirm_email(
    repo: Repository, settings: Settings, token: str
) -> bool:
    """Проверяет токен и подтверждает email. ``True`` — токен валиден.

    Идемпотентность: повторное подтверждение тем же токеном (пока он не истёк)
    возвращает успех и не меняет исходную дату ``email_verified_at``.
    """
    user_id = decode_verify_token(settings, token)
    if user_id is None:
        return False
    user = await repo.get_user(user_id)
    if user is None:
        return False
    if not user.email:
        return False
    if user.email_verified_at:
        return True
    at = datetime.now(timezone.utc).isoformat()
    await repo.set_email_verified(user.id, at)
    await track_event(repo, user.id, "email_verified")
    return True


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
    email_sender: EmailSender = Depends(get_email_sender),
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

    # Письмо подтверждения — best-effort: без SMTP ссылка уходит в лог,
    # а регистрация всё равно успешна (подтверждение мягкое).
    await _send_verification(
        repo, email_sender, settings, user, count_rate_limit=False
    )

    token = create_access_token(settings, user.id)
    set_session_cookie(response, settings, token)
    return AuthResponse(token=token, user=UserPublic(**public))


@router.post("/verify/request", response_model=VerifyRequestResponse)
async def request_email_verification(
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
    user_id: int = Depends(get_current_user_id),
    email_sender: EmailSender = Depends(get_email_sender),
):
    """Отправить письмо со ссылкой подтверждения (не чаще раза в 60 секунд)."""
    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if not user.email:
        raise HTTPException(status_code=400, detail="К аккаунту не привязан email")
    if user.email_verified_at:
        return VerifyRequestResponse(ok=True, already_verified=True)

    retry_after = _verify_retry_after(user.id)
    if retry_after > 0:
        return JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "detail": "Письмо уже отправлено. Попробуйте позже",
                "retry_after": retry_after,
            },
        )

    sent, link = await _send_verification(
        repo, email_sender, settings, user, count_rate_limit=True
    )
    return VerifyRequestResponse(ok=True, sent=sent, dev_link="" if sent else link)


@router.post("/verify", response_model=VerifyResponse)
async def confirm_email(
    body: VerifyTokenRequest,
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> VerifyResponse:
    """Подтвердить email по токену из письма (идемпотентно)."""
    if not await _confirm_email(repo, settings, body.token):
        raise HTTPException(
            status_code=400, detail="Ссылка недействительна или устарела"
        )
    return VerifyResponse(ok=True, email_verified=True)


@router.get("/verify")
async def confirm_email_link(
    token: str = "",
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
):
    """Ссылка из письма: 302 на страницу web-продукта (или JSON без WEBAPP_PUBLIC_URL)."""
    ok = bool(token) and await _confirm_email(repo, settings, token)
    base = settings.public_webapp_url.rstrip("/")
    if base:
        status = "ok" if ok else "error"
        return RedirectResponse(url=f"{base}/verify?status={status}", status_code=302)
    if ok:
        return {"ok": True, "email_verified": True}
    raise HTTPException(status_code=400, detail="Ссылка недействительна или устарела")



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
