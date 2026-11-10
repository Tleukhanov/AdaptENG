# Корневой монорепо деплоится как приложение API+бот (adapteng-api).
# ВАЖНО: Heroku-роутер отдаёт HTTP только процессу типа `web`, поэтому
# uvicorn (REST API) должен быть именно в `web`, иначе H14 «No web processes».
# В webhook-режиме bot/main.py запускает и бота, и веб-сервер в одном процессе.
web: python -m bot.main

# Telegram-бот живёт отдельным фоновым процессом (polling, не HTTP).
bot: python -m bot.main
