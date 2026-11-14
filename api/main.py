"""FastAPI-приложение AdaptENG: сборка, lifespan (репозиторий), CORS.

Фабрика ``create_app(settings)`` позволяет тестам поднимать изолированные
приложения с переопределёнными настройками и временной SQLite-БД.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from core.config import Settings, get_settings
from core.email import create_email_sender
from core.practice import PracticeService
from core.reminders import setup_reminder_scheduler
from providers import create_llm, create_pronunciation, create_stt, create_tts
from storage import create_repository

from .loadguard import ActionThrottle, AsyncQueueGuard, ClientWindowLimiter
from .ratelimit import RateLimitMiddleware
from .routers import (
    admin,
    analytics,
    auth,
    characters,
    chat,
    diagnostic,
    guest,
    health,
    lessons,
    progress,
    tutor,
    users,
    vocab,
    voice,
)
from .security import require_secret

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        require_secret(settings)
        repo = create_repository(
            database_url=settings.database_url,
            database_path=settings.database_path,
        pool_min=settings.db_pool_min,
        pool_max=settings.db_pool_max,
        )
        await repo.connect()
        app.state.repo = repo
        app.state.email_sender = create_email_sender(settings)
        app.state.llm = None
        app.state.practice = None
        app.state.tts = None
        app.state.stt = None
        try:
            app.state.llm = create_llm(settings)
            app.state.practice = PracticeService(llm=app.state.llm, max_history=settings.max_context_messages)
        except Exception as exc:
            logger.warning("LLM не настроен, /api/chat недоступен: %s", exc)
            app.state.practice = None
            app.state.llm = None
        try:
            app.state.tts = create_tts(settings)
        except Exception as exc:
            logger.warning("TTS не настроен, /api/chat/tts недоступен: %s", exc)
            app.state.tts = None
        try:
            app.state.stt = create_stt(settings)
            if settings.stt_provider.lower() == "faster-whisper":
                # На маленьких дино (Heroku Eco, 512 МБ) модель whisper не влезает:
                # первый запрос убьёт процесс по памяти (R14/R15). Предупреждаем.
                logger.warning(
                    "STT_PROVIDER=faster-whisper: модель %s грузится в память — "
                    "на дино меньше ~2 ГБ процесс убьётся по памяти. "
                    "Для прода используй STT_PROVIDER=openai (Groq/OpenAI).",
                    settings.resolved_stt_model,
                )
        except Exception as exc:
            logger.warning("STT не настроен, /api/voice недоступен: %s", exc)
            app.state.stt = None

        # Оценка произношения: None = провайдер выключен (фолбэк по словам).
        try:
            app.state.pronunciation = create_pronunciation(settings)
        except Exception as exc:
            logger.warning("Оценка произношения не настроена, фолбэк по словам: %s", exc)
            app.state.pronunciation = None
        if app.state.pronunciation is not None:
            logger.info("Оценка произношения: %s", settings.pronunciation_provider)

        # Защита от перегрузки: очередь LLM, пул STT, троттлинги.
        app.state.llm_guard = AsyncQueueGuard(
            settings.llm_max_concurrency,
            settings.llm_queue_max,
            settings.llm_queue_timeout_sec,
        )
        app.state.stt_guard = AsyncQueueGuard(
            settings.stt_max_concurrency,
            max(4, settings.stt_max_concurrency * 2),
            settings.llm_queue_timeout_sec,
        )
        app.state.action_throttle = ActionThrottle(
            window_sec=60.0,
            limit=settings.api_llm_actions_per_min,
            min_interval=settings.api_llm_min_interval_sec,
        )
        # Троттлинг распознаваний речи на пользователя (отдельно от LLM-квоты).
        app.state.stt_throttle = ActionThrottle(
            window_sec=60.0,
            limit=settings.stt_max_per_min,
            min_interval=0.0,
        )
        app.state.client_limiter = ClientWindowLimiter(
            window_sec=settings.api_rate_limit_window_sec,
            limit=settings.api_rate_limit_per_min,
        )
        # Гостевой «Урок 0»: не больше N ходов в сутки на IP.
        app.state.tutor_guest_limiter = ClientWindowLimiter(
            window_sec=86_400.0,
            limit=settings.tutor_guest_turns_per_day,
        )
        logger.info(
            "Load guard: llm_concurrency=%s queue_max=%s stt_concurrency=%s",
            settings.llm_max_concurrency,
            settings.llm_queue_max,
            settings.stt_max_concurrency,
        )
        logger.info(
            "AdaptENG api started (db=%s)",
            "postgres" if settings.database_url else "sqlite",
        )
        # Ежедневные email-напоминания. Выключены по умолчанию (REMINDERS_ENABLED=0):
        # в dev и тестах письма не должны уходить сами. Планировщик один на процесс.
        reminder_scheduler = setup_reminder_scheduler(
            repo, app.state.email_sender, settings
        )
        if reminder_scheduler is not None:
            reminder_scheduler.start()
            logger.info(
                "Email reminders scheduler started (hour=%s UTC)",
                settings.reminder_hour_utc,
            )

        # Telegram-бот в том же процессе: на Heroku-роутер отдаёт HTTP только
        # web-процессу, поэтому webhook бота обслуживает FastAPI, а не aiohttp
        # (иначе REST API не поднят вовсе). Ошибка инициализации бота не должна
        # ронять HTTP-сервер — API продолжит работать, бот вернётся после рестарта.
        bot_runtime = None
        if settings.webhook_enabled and settings.telegram_bot_token.strip():
            public_root = settings.public_webapp_url
            if not public_root:
                logger.error(
                    "USE_WEBHOOK=1, но WEBAPP_PUBLIC_URL/WEBAPP_URL пуст — "
                    "webhook Telegram не зарегистрирован"
                )
            else:
                try:
                    from bot.runtime import build_runtime, build_webhook_url

                    bot_runtime = await build_runtime(settings, repo)
                    webhook_url = build_webhook_url(
                        public_root, app.state.webhook_path
                    )
                    await bot_runtime.bot.set_webhook(
                        webhook_url,
                        secret_token=bot_runtime.secret_token,
                        drop_pending_updates=True,
                    )
                    app.state.bot_runtime = bot_runtime
                    app.state.webhook_secret = bot_runtime.secret_token
                    logger.info("Telegram webhook set: %s", webhook_url)
                except Exception:
                    logger.exception(
                        "Не удалось запустить бота в API-процессе — API продолжит без него"
                    )
                    if bot_runtime is not None:
                        await bot_runtime.close()
                        bot_runtime = None
                    app.state.bot_runtime = None
                    app.state.webhook_secret = ""

        try:
            yield
        finally:
            if bot_runtime is not None:
                await bot_runtime.close()
            if reminder_scheduler is not None and reminder_scheduler.running:
                reminder_scheduler.shutdown(wait=False)
            await repo.close()

    app = FastAPI(
        title="AdaptENG API",
        version="0.1.0",
        description="Персональный AI-репетитор английского с персонажами.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.bot_runtime = None
    app.state.webhook_secret = ""
    app.state.webhook_path = ""

    # Webhook Telegram обслуживает этот же процесс, когда USE_WEBHOOK=1.
    # Путь фиксируется при сборке приложения: при пустом WEBHOOK_PATH он
    # случайный, и регистрация в Telegram должна использовать ровно его.
    if settings.webhook_enabled:
        from bot.runtime import resolve_webhook_path

        app.state.webhook_path = resolve_webhook_path(settings.webhook_path)

        @app.post(app.state.webhook_path, include_in_schema=False)
        async def telegram_webhook(request: Request) -> dict[str, bool]:
            runtime = getattr(app.state, "bot_runtime", None)
            secret = getattr(app.state, "webhook_secret", "")
            if runtime is None or not secret:
                raise HTTPException(status_code=503, detail="Bot runtime не запущен")
            header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header != secret:
                raise HTTPException(status_code=403, detail="Неверный secret webhook")
            payload = await request.json()

            from aiogram.types import Update

            update = Update.model_validate(payload, context={"bot": runtime.bot})
            await runtime.dp.feed_webhook_update(runtime.bot, update)
            return {"ok": True}

    origins = settings.cors_origins_list or [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Лимит запросов на клиента; лимитер создаётся в lifespan, поэтому
    # middleware-обёртка достаёт его из app.state по первому запросу.
    app.add_middleware(RateLimitMiddleware)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(guest.router)
    app.include_router(users.router)
    app.include_router(characters.router)
    app.include_router(chat.router)
    app.include_router(lessons.router)
    app.include_router(voice.router)
    app.include_router(progress.router)
    app.include_router(analytics.router)
    app.include_router(admin.router)
    app.include_router(diagnostic.router)
    app.include_router(tutor.router)
    app.include_router(vocab.router)

    return app


app = create_app()