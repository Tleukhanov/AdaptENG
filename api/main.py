"""FastAPI-приложение AdaptENG: сборка, lifespan (репозиторий), CORS.

Фабрика ``create_app(settings)`` позволяет тестам поднимать изолированные
приложения с переопределёнными настройками и временной SQLite-БД.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import Settings, get_settings
from core.practice import PracticeService
from providers import create_llm, create_stt, create_tts
from storage import create_repository

from .loadguard import ActionThrottle, AsyncQueueGuard, ClientWindowLimiter
from .ratelimit import RateLimitMiddleware
from .routers import (
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
        try:
            yield
        finally:
            await repo.close()

    app = FastAPI(
        title="AdaptENG API",
        version="0.1.0",
        description="Персональный AI-репетитор английского с персонажами.",
        lifespan=lifespan,
    )
    app.state.settings = settings

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
    app.include_router(diagnostic.router)
    app.include_router(tutor.router)
    app.include_router(vocab.router)

    return app


app = create_app()