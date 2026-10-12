"""HTTP-сервер Telegram Mini App (aiohttp) в том же процессе, что и бот.

Отдаёт статику из пакета ``web/`` и API: ``/api/init``, ``/api/tts``,
``/api/health``. Роуты уроков (``/api/deck/*``) живут в :mod:`bot.mini_api`
и монтируются под-приложением на ``/api``.

Безопасность: ``user_id`` берётся ТОЛЬКО из подписанного Telegram ``initData``
(HMAC-SHA256 от токена бота), тело запроса и query-параметры не доверяем.
Сам ``initData`` нигде не логируется — только ``user_id``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot

from core.characters import character_voice, get_character

from .config import Settings

logger = logging.getLogger(__name__)

# Корень репозитория: bot/webapp.py -> bot/ -> <root>
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

# Статика иммутабельна между релизами только условно, поэтому кэшируем умеренно.
ASSETS_MAX_AGE = 3600
NO_STORE = "no-store, no-cache, must-revalidate"

INIT_DATA_HEADER = "X-Telegram-Init-Data"
MAX_TTS_CHARS = 300
TTS_CACHE_LIMIT = 256

# Типизированные ключи состояния aiohttp-приложения (рекомендация aiohttp 3.9+).
SETTINGS_KEY: web.AppKey[Settings] = web.AppKey("settings")
BOT_KEY: web.AppKey[Bot] = web.AppKey("bot")
DEPS_KEY: web.AppKey[Any] = web.AppKey("deps")

# Кэш озвучки: (голос, текст) -> mp3 в base64. Карточки слов повторяются часто.
_TTS_CACHE: dict[tuple[str, str], str] = {}


# ---------- ответы и разбор запроса ----------


def ok_response(payload: Mapping[str, Any], status: int = 200) -> web.Response:
    """Успешный JSON: всегда с ``ok: true``."""
    return web.json_response({"ok": True, **dict(payload)}, status=status)


def error_response(error: str, status: int = 400, **extra: Any) -> web.Response:
    """Единый формат ошибок API: ``{ok: false, error: ...}``."""
    return web.json_response({"ok": False, "error": error, **extra}, status=status)


def unauthorized_response() -> web.Response:
    return error_response("unauthorized", status=401)


async def read_json(request: web.Request) -> dict[str, Any]:
    """Читает JSON-тело запроса; битое/пустое тело — пустой словарь."""
    if not request.can_read_body:
        return {}
    try:
        raw = await request.text()
    except Exception:
        logger.warning("Не удалось прочитать тело запроса: %s", request.path)
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Битый JSON в теле запроса: %s", request.path)
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_init_data(request: web.Request, payload: Mapping[str, Any] | None = None) -> str:
    """Достаёт initData из тела, заголовка или query — фронт шлёт все три сразу."""
    if payload:
        for key in ("initData", "init_data"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    header = request.headers.get(INIT_DATA_HEADER, "")
    if header.strip():
        return header.strip()
    query = request.query.get("initData") or request.query.get("init_data") or ""
    return query.strip()


# ---------- валидация initData ----------


def parse_init_data(init_data: str) -> dict[str, str]:
    """Разбирает query-строку initData в словарь (последнее значение побеждает)."""
    if not init_data:
        return {}
    return dict(parse_qsl(init_data, keep_blank_values=True))


def data_check_string(params: Mapping[str, str]) -> str:
    """Строка проверки: пары ``k=v`` по алфавиту, склеенные ``\\n``, без ``hash``."""
    return "\n".join(f"{key}={value}" for key, value in sorted(params.items()) if key != "hash")


def secret_key(bot_token: str) -> bytes:
    """secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)."""
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def compute_hash(bot_token: str, params: Mapping[str, str]) -> str:
    """Ожидаемая подпись initData для набора параметров."""
    signature = hmac.new(
        secret_key(bot_token), data_check_string(params).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return signature


def sign_init_data(bot_token: str, params: Mapping[str, str]) -> str:
    """Собирает корректную строку initData с подписью (используется в тестах)."""
    payload = {key: value for key, value in params.items() if key != "hash"}
    payload["hash"] = compute_hash(bot_token, payload)
    return "&".join(f"{key}={value}" for key, value in payload.items())


def validate_init_data(bot_token: str, init_data: str) -> int | None:
    """Проверяет подпись initData и возвращает Telegram ``user_id``.

    ``None`` — initData невалидна (нет hash, подпись не совпала, нет user).
    Чистая функция: без сети, без настроек, без БД.
    """
    if not bot_token or not init_data:
        return None
    params = parse_init_data(init_data)
    received_hash = params.get("hash", "")
    if not received_hash:
        return None
    expected_hash = compute_hash(bot_token, params)
    if not hmac.compare_digest(expected_hash, received_hash):
        return None
    try:
        user = json.loads(params.get("user", "") or "{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(user, dict):
        return None
    try:
        return int(user["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _unverified_user_id(init_data: str) -> int | None:
    """user_id из initData БЕЗ проверки подписи (только для WEBAPP_INSECURE_AUTH=1)."""
    user = parse_init_data(init_data).get("user", "")
    if not user:
        return None
    try:
        payload = json.loads(user)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload["id"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------- доступ к зависимостям ----------


def dependency(request: web.Request, name: str, default: Any = None) -> Any:
    """Сервис из ``deps`` (dict или объект) текущего приложения/субприложения."""
    deps = request.app.get(DEPS_KEY)
    if deps is None:
        return default
    if isinstance(deps, Mapping):
        return deps.get(name, default)
    return getattr(deps, name, default)


async def authenticate(
    request: web.Request, payload: Mapping[str, Any] | None = None
) -> tuple[int | None, web.Response | None]:
    """Возвращает ``(telegram_user_id, error_response)`` — user_id только из initData."""
    settings: Settings = request.app[SETTINGS_KEY]
    init_data = extract_init_data(request, payload)
    if not init_data:
        return None, unauthorized_response()
    if getattr(settings, "webapp_insecure_auth", 0):
        user_id = _unverified_user_id(init_data) or 0
        logger.warning("WEBAPP_INSECURE_AUTH=1: initData не проверен (user=%s)", user_id)
        return user_id, None
    user_id = validate_init_data(settings.telegram_bot_token, init_data)
    if user_id is None:
        logger.warning("initData не прошла проверку подписи: %s", request.path)
        return None, unauthorized_response()
    return user_id, None


# ---------- профиль для /api/init ----------


def _split_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        items = [part.strip() for part in str(value or "").split(",")]
    return [item for item in items if item]


async def quota_left(quota: Any, user_id: int) -> int | None:
    """Остаток дневной квоты; ``None`` — безлимит (фронт показывает «∞»)."""
    if quota is None:
        return None
    try:
        limit = int(getattr(quota, "_daily_limit", 0) or 0)
        if limit <= 0:
            return None
        repo = getattr(quota, "_repo", None)
        if repo is None:
            return None
        if await repo.get_unlimited_status(user_id):
            return None
        subscription = await repo.get_subscription(user_id)
        if subscription is not None and subscription.is_active:
            return None
        from datetime import datetime, timezone

        used = await repo.get_llm_usage(user_id, datetime.now(timezone.utc).date().isoformat())
        extra = await repo.get_extra_actions(user_id)
        return max(limit + extra - used, 0)
    except Exception:
        logger.warning("Не удалось посчитать остаток квоты user=%s", user_id, exc_info=True)
        return None


async def planned_topics(repo: Any, user_id: int, limit: int = 3) -> list[str]:
    """Ближайшие темы из плана уроков (пусто, если плана нет)."""
    try:
        from core.lesson_plan import LessonPlan, next_plan_index

        row = await repo.get_lesson_plan(user_id)
        if row is None:
            return []
        plan = LessonPlan.from_json(row.plan_json)
        completed = await repo.count_finished_lessons(user_id)
        idx = next_plan_index(row.based_on_lessons, completed, row.horizon)
        if idx is None:
            return [lesson.topic for lesson in plan.lessons[:limit]]
        upcoming = [lesson.topic for lesson in plan.lessons[idx: idx + limit]]
        return [topic for topic in upcoming if topic]
    except Exception:
        logger.warning("Не удалось прочитать план уроков user=%s", user_id, exc_info=True)
        return []


async def build_profile_payload(request: web.Request, tg_user_id: int) -> dict[str, Any]:
    """Данные для экрана меню Mini App: уровень, квота, персонаж, интересы, темы."""
    repo = dependency(request, "repo")
    user = await repo.get_or_create_user(tg_user_id)
    profile = await repo.get_profile(user.id)
    character = get_character(profile.character if profile else "")
    return {
        "user_id": user.id,
        "tg_id": tg_user_id,
        "level": user.level or "A1",
        "quota_left": await quota_left(dependency(request, "quota"), user.id),
        "character": character.name,
        "character_id": character.id,
        "interests": _split_list(profile.interests if profile else ""),
        "topics": await planned_topics(repo, user.id),
    }


# ---------- хендлеры верхнего уровня ----------


async def handle_index(request: web.Request) -> web.Response:
    """GET / — точка монтирования Mini App (index.html)."""
    index = WEB_ROOT / "index.html"
    if not index.is_file():
        logger.error("Не найден web/index.html (ожидался %s)", index)
        return web.Response(status=404, text="index.html not found")
    return web.FileResponse(index, headers={"Cache-Control": NO_STORE})


async def handle_health(request: web.Request) -> web.Response:
    """GET /api/health — healthcheck для туннеля/мониторинга."""
    return ok_response({})


async def handle_init(request: web.Request) -> web.Response:
    """POST /api/init — профиль меню Mini App."""
    payload = await read_json(request)
    user_id, error = await authenticate(request, payload)
    if error is not None:
        return error
    try:
        profile = await build_profile_payload(request, user_id)
    except Exception:
        logger.exception("Ошибка /api/init: user=%s", user_id)
        return error_response("init_failed", status=500)
    logger.info("Mini App init: user=%s level=%s", profile["user_id"], profile["level"])
    return ok_response(profile)


async def _resolve_voice(request: web.Request, tg_user_id: int) -> str | None:
    """Голос персонажа (best effort, ошибки не ломают озвучку)."""
    repo = dependency(request, "repo")
    if repo is None:
        return None
    try:
        user = await repo.get_or_create_user(tg_user_id)
        profile = await repo.get_profile(user.id)
        return character_voice(profile.character if profile else "")
    except Exception:
        logger.debug("Не удалось определить голос персонажа", exc_info=True)
        return None


async def synthesize_base64(request: web.Request, text: str, voice: str | None) -> str:
    """Синтез речи в mp3 → base64 (с кэшем в памяти процесса)."""
    cache_key = (voice or "", text)
    cached = _TTS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    tts = dependency(request, "tts")
    if tts is None:
        raise RuntimeError("tts_unavailable")
    audio = await tts.synthesize(text, voice=voice)
    if not audio:
        raise RuntimeError("tts_empty")
    encoded = base64.b64encode(audio).decode("ascii")
    if len(_TTS_CACHE) >= TTS_CACHE_LIMIT:
        _TTS_CACHE.clear()
    _TTS_CACHE[cache_key] = encoded
    return encoded


async def handle_tts(request: web.Request) -> web.Response:
    """POST /api/tts — озвучка слова/фразы для карточек."""
    payload = await read_json(request)
    user_id, error = await authenticate(request, payload)
    if error is not None:
        return error
    text = ""
    for key in ("text", "word", "phrase"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            break
    if not text:
        return error_response("text_required")
    text = text[:MAX_TTS_CHARS]
    voice = await _resolve_voice(request, user_id)
    try:
        audio_base64 = await synthesize_base64(request, text, voice)
    except Exception:
        logger.exception("Ошибка TTS: user=%s", user_id)
        return error_response("tts_failed", status=502)
    return ok_response({"audio_base64": audio_base64, "format": "audio/mpeg"})


# ---------- сборка приложения ----------


@web.middleware
async def cache_headers_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Кэш для статики, запрет кэша для API и index.html."""
    response = await handler(request)
    path = request.path
    if isinstance(response, web.FileResponse) or path.startswith("/assets/"):
        if path in ("/", "/index.html"):
            response.headers["Cache-Control"] = NO_STORE
        else:
            response.headers.setdefault("Cache-Control", f"public, max-age={ASSETS_MAX_AGE}")
    elif path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def create_webapp(
    settings: Settings,
    bot: Bot,
    deps: Mapping[str, Any] | Any,
    *,
    webhook_path: str = "",
    webhook_handler: web.Handler | None = None,
) -> web.Application:
    """Собирает aiohttp-приложение: Mini App + опциональный webhook Telegram.

    ``webhook_handler`` (например, aiogram ``SimpleRequestHandler.handle``)
    регистрируется на ``POST webhook_path`` ПЕРЕД статикой: корневой ``add_static``
    является catch-all'ом и перекрыл бы POST-роут, дав 405.
    """
    # Импорт внутри функции: bot.mini_api импортирует хелперы отсюда (без цикла).
    from . import mini_api

    app = web.Application(middlewares=[cache_headers_middleware])
    app[SETTINGS_KEY] = settings
    app[BOT_KEY] = bot
    app[DEPS_KEY] = deps

    if webhook_path and webhook_handler is not None:
        app.router.add_post(webhook_path, webhook_handler)
        logger.info("Webhook route registered: POST %s", webhook_path)

    app.router.add_get("/", handle_index)
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/init", handle_init)
    app.router.add_post("/api/tts", handle_tts)
    # Роуты уроков монтируем ПОСЛЕ точных /api/*: aiohttp разрешает URL по порядку
    # регистрации, иначе под-приложение перехватило бы /api/init и /api/tts.
    app.add_subapp("/api", mini_api.build_app(settings, bot, deps))

    if WEB_ROOT.is_dir():
        app.router.add_static("/assets", WEB_ROOT, name="assets")
        # index.html подключает ./style.css и ./app.js — отдаём их с корня.
        app.router.add_static("/", WEB_ROOT, name="web")
    else:
        logger.warning("Каталог статики Mini App не найден: %s", WEB_ROOT)
    return app


def iter_route_paths(app: web.Application) -> list[str]:
    """Пути, зарегистрированные в приложении и его под-приложениях."""
    paths: list[str] = []
    for resource in app.router.resources():
        path = getattr(resource, "canonical", None) or getattr(resource, "prefix", None) or str(resource)
        paths.append(path)
        sub = getattr(resource, "app", None)
        if sub is not None:
            paths.extend(iter_route_paths(sub))
    return paths
