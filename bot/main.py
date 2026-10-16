"""Точка входа бота.

Запуск: python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging
import secrets

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiohttp import web as aiohttp_web

from core.diagnostic import DiagnosticService
from core.lesson_notes import LessonNoteService
from core.lesson_plan import LessonPlanService
from core.lessons import LessonService
from core.practice import PracticeService
from core.profile import ProfileService
from core.rag import RAGGrammarTutor
from core.srs import SRSService
from providers import create_embedder, create_llm, create_stt, create_tts
from storage import create_repository

from .config import get_settings
from .diagnostic import router as diagnostic_router
from .flow import router as practice_router
from .quota import QuotaGuard
from .rate_limit import LLMThrottle
from .handlers import menu, profile, start, text, voice
from .handlers.character import router as character_router
from .handlers.interests import router as interests_router
from .handlers.progress import router as progress_router
from .handlers.achievements import router as achievements_router
from .handlers.review import router as review_router
from .handlers.tutor import router as tutor_router
from .handlers.onboarding import router as onboarding_router
from .handlers.leaderboard import router as leaderboard_router
from .handlers.promo import router as promo_router
from .handlers.wheel import router as wheel_router
from .handlers.premium import router as premium_router
from .handlers.kaspi import router as kaspi_router
from .handlers.admin import router as admin_router
from .lessons import router as lessons_router
from .keyboards import set_webapp_url
from .webapp import create_webapp

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Начать практику"),
    BotCommand(command="lesson", description="Структурированный урок"),
    BotCommand(command="app", description="📱 Урок в Mini App"),
    BotCommand(command="character", description="🎭 Выбрать персонажа"),
    BotCommand(command="interests", description="🎯 Мои интересы"),
    BotCommand(command="diagnostic", description="🎯 Определить уровень"),
    BotCommand(command="review", description="📚 Повторить слова"),
    BotCommand(command="tutor", description="🎓 Спросить грамматику (RAG)"),
    BotCommand(command="stats", description="Моя статистика"),
    BotCommand(command="progress", description="📊 Мой прогресс"),
    BotCommand(command="achievements", description="🎮 Достижения"),
    BotCommand(command="leaderboard", description="🏅 Рейтинг"),
    BotCommand(command="reset", description="🔄 Сбросить состояние"),
    BotCommand(command="profile", description="🧠 Мой профиль"),
    BotCommand(command="promo", description="🎟 Промокод на безлимит"),
    BotCommand(command="wheel", description="🎡 Колесо удачи"),
    BotCommand(command="premium", description="💳 Подписка (Kaspi QR)"),
    BotCommand(command="admin", description="⚙️ Админ"),
    BotCommand(command="help", description="Помощь"),
]


async def _start_webapp(settings, bot: Bot, deps: dict) -> "aiohttp_web.AppRunner | None":
    """Поднимает aiohttp-сервер Mini App рядом с поллингом.

    Без WEBAPP_URL ничего не запускаем — обычный запуск бота не меняется.
    Возвращает runner для cleanup() или None.
    """
    if not settings.webapp_url.strip():
        return None
    set_webapp_url(settings.webapp_url)
    app = create_webapp(settings, bot, deps)
    runner = aiohttp_web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        site = aiohttp_web.TCPSite(runner, settings.webapp_host, settings.webapp_port)
        await site.start()
    except OSError:
        logger.exception(
            "Не удалось занять %s:%s для Mini App — бот продолжит без него",
            settings.webapp_host,
            settings.webapp_port,
        )
        await runner.cleanup()
        return None
    logger.info(
        "Mini App server started: http://%s:%s (public: %s)",
        settings.webapp_host,
        settings.webapp_port,
        settings.webapp_url,
    )
    return runner


async def _run_webhook_mode(settings, bot: Bot, dp: Dispatcher, deps: dict) -> None:
    """Webhook-режим для Heroku: один aiohttp-сервер (Mini App + webhook) на $PORT.

    Требует публичного HTTPS-корня (WEBAPP_PUBLIC_URL или WEBAPP_URL). Секретный
    путь webhook при пустом WEBHOOK_PATH генерируется на каждом старте через
    ``secrets.token_urlsafe`` и сразу пере-регистрируется через set_webhook —
    это безопасно для перезапусков (dyno sleep/recycle) и не даёт подглядывать
    адрес webhook в истории коммитов.
    """
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    public_root = settings.public_webapp_url
    if not public_root:
        raise SystemExit("Webhook-режим требует WEBAPP_PUBLIC_URL или WEBAPP_URL")

    webhook_path = resolve_webhook_path(settings.webhook_path)
    webhook_url = build_webhook_url(public_root, webhook_path)
    secret_token = secrets.token_urlsafe(24).rstrip("=")

    set_webapp_url(public_root)
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret_token)
    app = create_webapp(
        settings,
        bot,
        deps,
        webhook_path=webhook_path,
        webhook_handler=handler.handle,
    )
    setup_application(app, dp)

    await bot.set_webhook(webhook_url, secret_token=secret_token, drop_pending_updates=True)
    logger.info("Telegram webhook set: %s (secret %d chars)", webhook_url, len(secret_token))

    port = settings.port or settings.webapp_port
    runner = aiohttp_web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        site = aiohttp_web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
    except OSError:
        logger.exception("Не удалось занять 0.0.0.0:%s — webhook-сервер не поднят", port)
        await runner.cleanup()
        raise
    logger.info("Webhook server started: 0.0.0.0:%s (path %s)", port, webhook_path)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def resolve_webhook_path(configured: str) -> str:
    """Секретный путь webhook: заданный (нормализован до '/...') или случайный."""
    path = configured.strip()
    if path:
        return path if path.startswith("/") else "/" + path
    return "/webhook/" + secrets.token_urlsafe(15)


def build_webhook_url(public_root: str, path: str) -> str:
    """Склеивает публичный корень и путь webhook в один URL."""
    return public_root.rstrip("/") + (path if path.startswith("/") else "/" + path)


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан в .env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if not settings.llm_ready:
        logger.warning(
            "LLM не настроен полностью: LLM_PROVIDER=%s, LLM_API_KEY пуст. "
            "Практика начнёт работать после заполнения .env.",
            settings.llm_provider,
        )

    if settings.admin_tg_id == 0:
        logger.warning(
            "ADMIN_TG_ID не задан: подтверждение Kaspi-оплат будет недоступно."
        )
    if not settings.kaspi_qr_path:
        logger.warning(
            "KASPI_QR_PATH не задан: QR будет показан текстом, без картинки."
        )

    repo = create_repository(
        database_url=settings.database_url,
        database_path=settings.database_path,
    pool_min=settings.db_pool_min,
    pool_max=settings.db_pool_max,
    )
    await repo.connect()

    llm = create_llm(settings)
    stt = create_stt(settings)
    tts = create_tts(settings)
    practice = PracticeService(llm, max_history=settings.max_context_messages)
    lessons = LessonService(llm)
    diagnostic = DiagnosticService(llm)
    profile_service = ProfileService(llm)
    note_service = LessonNoteService(llm)
    plan_service = LessonPlanService(llm)
    srs_service = SRSService(repo)
    rag_tutor = RAGGrammarTutor(
        chat=llm,
        embedder=create_embedder(settings),
        threshold=settings.rag_threshold,
    )

    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    quota = QuotaGuard(repo, settings.llm_daily_limit)

    dp["repo"] = repo
    dp["practice"] = practice
    dp["lesson_service"] = lessons
    dp["diagnostic_service"] = diagnostic
    dp["profile_service"] = profile_service
    dp["note_service"] = note_service
    dp["plan_service"] = plan_service
    dp["srs"] = srs_service
    dp["tutor"] = rag_tutor
    dp["stt"] = stt
    dp["tts"] = tts
    dp["settings"] = settings
    dp["quota"] = quota

    dp.message.outer_middleware(LLMThrottle())

    dp.include_router(onboarding_router)
    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(character_router)
    dp.include_router(interests_router)
    dp.include_router(progress_router)
    dp.include_router(achievements_router)
    dp.include_router(leaderboard_router)
    dp.include_router(profile.router)
    dp.include_router(practice_router)
    dp.include_router(lessons_router)
    dp.include_router(diagnostic_router)
    dp.include_router(review_router)
    dp.include_router(tutor_router)
    dp.include_router(promo_router)
    dp.include_router(wheel_router)
    dp.include_router(premium_router)
    dp.include_router(kaspi_router)
    dp.include_router(admin_router)
    dp.include_router(text.router)
    dp.include_router(voice.router)

    from aiogram.types import ErrorEvent
    @dp.error()
    async def global_error_handler(event: ErrorEvent) -> None:
        logger.exception("Unhandled error: %s", event.exception)
        try:
            if hasattr(event.update, "message") and event.update.message:
                await event.update.message.answer(
                    "⚠️ Произошла ошибка. Попробуй ещё раз или нажми /start."
                )
            elif hasattr(event.update, "callback_query") and event.update.callback_query:
                await event.update.callback_query.message.answer(
                    "⚠️ Произошла ошибка. Попробуй ещё раз или нажми /start."
                )
        except Exception:
            pass

    await bot.set_my_commands(COMMANDS)

    from core.scheduler import setup_scheduler
    scheduler = setup_scheduler(bot, repo, interval_hours=24)
    scheduler.start()
    logger.info("Scheduler started: reminders every %d hours", 24)

    deps = {
        "repo": repo,
        "llm": llm,
        "tts": tts,
        "stt": stt,
        "quota": quota,
        "srs": srs_service,
        "plan_service": plan_service,
        "note_service": note_service,
    }

    if settings.webhook_enabled:
        try:
            await _run_webhook_mode(settings, bot, dp, deps)
        finally:
            scheduler.shutdown(wait=False)
            await repo.close()
            await bot.session.close()
        return

    runner = await _start_webapp(settings, bot, deps)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if runner is not None:
            await runner.cleanup()
        scheduler.shutdown(wait=False)
        await repo.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
