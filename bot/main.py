"""Точка входа бота.

Запуск: ``python -m bot.main`` (polling) или webhook-режим при ``USE_WEBHOOK=1``.

В проде (Heroku) webhook Telegram обслуживает FastAPI (см. ``api/main.py``),
поэтому этот модуль нужен только для локального запуска и legacy-режима
aiohttp (Mini App + webhook в одном процессе).
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web as aiohttp_web

from .config import get_settings
from .keyboards import set_webapp_url
from .runtime import (  # noqa: F401 — публичные хелперы для тестов и деплоя
    COMMANDS,
    BotRuntime,
    build_runtime,
    build_webhook_url,
    resolve_webhook_path,
)
from .webapp import create_webapp

logger = logging.getLogger(__name__)


async def _start_webapp(settings, bot, deps: dict) -> "aiohttp_web.AppRunner | None":
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


async def _run_webhook_mode(settings, runtime: BotRuntime) -> None:
    """Webhook-режим aiohttp (Mini App + Telegram) на $PORT.

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

    set_webapp_url(public_root)
    handler = SimpleRequestHandler(
        dispatcher=runtime.dp, bot=runtime.bot, secret_token=runtime.secret_token
    )
    app = create_webapp(
        settings,
        runtime.bot,
        runtime.deps,
        webhook_path=webhook_path,
        webhook_handler=handler.handle,
    )
    setup_application(app, runtime.dp)

    await runtime.bot.set_webhook(
        webhook_url, secret_token=runtime.secret_token, drop_pending_updates=True
    )
    logger.info(
        "Telegram webhook set: %s (secret %d chars)",
        webhook_url,
        len(runtime.secret_token),
    )

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

    from storage import create_repository

    repo = create_repository(
        database_url=settings.database_url,
        database_path=settings.database_path,
        pool_min=settings.db_pool_min,
        pool_max=settings.db_pool_max,
    )
    await repo.connect()
    runtime = await build_runtime(settings, repo)

    try:
        if settings.webhook_enabled:
            await _run_webhook_mode(settings, runtime)
            return
        runner = await _start_webapp(settings, runtime.bot, runtime.deps)
        try:
            await runtime.dp.start_polling(
                runtime.bot, allowed_updates=runtime.dp.resolve_used_update_types()
            )
        finally:
            if runner is not None:
                await runner.cleanup()
    finally:
        await runtime.close()
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
