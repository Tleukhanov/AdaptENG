"""DI-хелперы FastAPI: настройки, репозиторий, аутентификация, локаль."""

from __future__ import annotations

from datetime import date

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from storage.repo import Repository

from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    """Настройки берутся из attached app.state (могут быть переопределены в тестах)."""
    return request.app.state.settings


def get_repository(request: Request) -> Repository:
    """Репозиторий, подключённый в lifespan приложения."""
    repo: Repository = request.app.state.repo
    return repo


def get_practice(request: Request):
    """PracticeService, собранный в lifespan (None, если LLM не настроен)."""
    return getattr(request.app.state, "practice", None)


def get_llm(request: Request):
    """LLM-провайдер, собранный в lifespan (None, если LLM не настроен)."""
    return getattr(request.app.state, "llm", None)


def get_tts(request: Request):
    """TTS-провайдер, собранный в lifespan (None, если TTS не настроен)."""
    return getattr(request.app.state, "tts", None)


def get_stt(request: Request):
    """STT-провайдер, собранный в lifespan (None, если STT не настроен)."""
    return getattr(request.app.state, "stt", None)


def get_llm_guard(request: Request):
    """Очередь LLM-вызовов (семафор + лимит ожидания)."""
    return getattr(request.app.state, "llm_guard", None)


def get_stt_guard(request: Request):
    """Пул для распознавания речи."""
    return getattr(request.app.state, "stt_guard", None)


def get_action_throttle(request: Request):
    """Троттлинг LLM-действий на пользователя."""
    return getattr(request.app.state, "action_throttle", None)


def client_key(request: Request) -> str:
    """Ключ клиента для лимита запросов: IP клиента (за заголовками прокси).

    Берём ПОСЛЕДНЕЕ значение X-Forwarded-For: Heroku дописывает реальный адрес
    в конец, а первым может стоять подделанный клиентом заголовок.
    """
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def get_current_user_id(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int:
    """Извлекает и проверяет JWT: из ``Authorization: Bearer`` или из cookie сессии.

    Возвращает внутренний ``users.id`` — идентичность больше не привязана к Telegram.
    """
    token = ""
    if credentials is not None and credentials.credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get(settings.session_cookie_name, "")
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    user_id = decode_access_token(settings, token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Невалидный или истёкший токен")
    return user_id


async def current_user(repo: Repository, user_id: int):
    """Возвращает пользователя по внутреннему id либо 401."""
    user = await repo.get_user(user_id)
    if user is None:
        # Совместимость со старыми токенами (в них sub = tg_id).
        user = await repo.get_user_by_tg_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def resolve_locale(request: Request) -> str:
    """Локаль ответа api: явный ``?lang=`` или ``Accept-Language``, по умолчанию ru."""
    lang = request.query_params.get("lang")
    if lang in ("ru", "en"):
        return lang
    accept = request.headers.get("accept-language", "")
    if accept.lower().startswith("en"):
        return "en"
    return "ru"


def today_str() -> str:
    return date.today().isoformat()


async def build_user_public(
    repo: Repository,
    user,
    profile,
    settings: Settings,
    stats=None,
) -> dict[str, object]:
    """Собирает публичное представление пользователя для /api/me и auth-ответа."""
    used = await repo.get_llm_usage(user.id, today_str())
    quota_total = settings.llm_daily_limit if settings.llm_daily_limit > 0 else None
    quota_left: int | None = None
    if quota_total is not None:
        unlimited = bool(user.is_unlimited)
        sub = await repo.get_subscription(user.id)
        subscription_active = bool(sub and sub.is_active)
        if not unlimited and not subscription_active:
            quota_left = max(quota_total - used, 0)

    interests = [x.strip() for x in (profile.interests or "").split(",") if x.strip()] if profile else []
    char_id = profile.character if profile else ""

    return {
        "id": user.id,
        "tg_id": user.tg_id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "email": user.email or "",
        "level": user.level,
        "character": char_id,
        "interests": interests,
        "quota_left": quota_left,
        "quota_total": quota_total,
        "llm_daily_limit": settings.llm_daily_limit,
        "is_unlimited": bool(user.is_unlimited),
        "total_turns": stats.total_turns if stats else 0,
        "correct": stats.correct if stats else 0,
        "errors": stats.errors if stats else 0,
    }