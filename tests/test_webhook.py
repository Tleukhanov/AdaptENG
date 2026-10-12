"""Тесты webhook-режима (Heroku): сборка URL, секретный путь, роуты.

Без сети и Telegram: чистые функции + сборка aiohttp-приложения с фейковым
webhook-хендлером. Полный запуск _run_webhook_mode требует живого Bot и сети —
здесь не вызывается.
"""

from aiohttp import web

from bot.config import Settings
from bot.main import build_webhook_url, resolve_webhook_path
from bot.webapp import SETTINGS_KEY, create_webapp

BOT_TOKEN = "123456:TEST-token"


# ---------- путь и URL webhook ----------


def test_resolve_webhook_path_generates_secret():
    path = resolve_webhook_path("")
    assert path.startswith("/webhook/")
    assert len(path) > len("/webhook/")


def test_resolve_webhook_path_is_random_each_call():
    assert resolve_webhook_path("") != resolve_webhook_path("")


def test_resolve_webhook_path_normalizes_configured():
    assert resolve_webhook_path("hook") == "/hook"
    assert resolve_webhook_path("/hook/abc") == "/hook/abc"


def test_build_webhook_url_joins_root_and_path():
    assert build_webhook_url("https://app.herokuapp.com", "/webhook/x") == (
        "https://app.herokuapp.com/webhook/x"
    )


def test_build_webhook_url_handles_trailing_slash_and_missing_leading_slash():
    assert build_webhook_url("https://app.herokuapp.com/", "webhook/x") == (
        "https://app.herokuapp.com/webhook/x"
    )


# ---------- настройки ----------


def test_use_webhook_flag():
    assert Settings(telegram_bot_token=BOT_TOKEN).webhook_enabled is False
    assert Settings(telegram_bot_token=BOT_TOKEN, use_webhook=1).webhook_enabled is True


def test_public_webapp_url_prefers_webapp_public_url():
    settings = Settings(
        telegram_bot_token=BOT_TOKEN,
        webapp_url="https://tunnel.example.com",
        webapp_public_url="https://app.herokuapp.com",
    )
    assert settings.public_webapp_url == "https://app.herokuapp.com"


def test_public_webapp_url_falls_back_to_webapp_url():
    settings = Settings(telegram_bot_token=BOT_TOKEN, webapp_url="https://tunnel.example.com")
    assert settings.public_webapp_url == "https://tunnel.example.com"


# ---------- webhook-роут в aiohttp-приложении ----------


def test_create_webapp_registers_webhook_before_static():
    async def fake_webhook(request):
        return web.json_response({})

    settings = Settings(telegram_bot_token=BOT_TOKEN)
    app = create_webapp(
        settings,
        None,
        {},
        webhook_path="/webhook/abc",
        webhook_handler=fake_webhook,
    )

    resources = list(app.router.resources())
    webhook_idx = next(
        i for i, res in enumerate(resources) if getattr(res, "canonical", None) == "/webhook/abc"
    )
    # Статика в этом проекте регистрируется через add_static (StaticResource).
    # Webhook-роут обязан быть зарегистрирован раньше, иначе catch-all перехватит POST.
    static_indexes = [
        i for i, res in enumerate(resources) if type(res).__name__ == "StaticResource"
    ]
    assert static_indexes
    assert webhook_idx < min(static_indexes)


def test_create_webapp_without_webhook_stays_compatible():
    settings = Settings(telegram_bot_token=BOT_TOKEN)
    app = create_webapp(settings, None, {})
    assert app[SETTINGS_KEY] is settings
    # webhook-роут не добавлен, если не передан handler
    assert all(
        getattr(res, "canonical", None) != "/webhook/abc" for res in app.router.resources()
    )