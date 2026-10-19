# Корневой монорепо деплоится как приложение API+бот (adapteng-api).
# ВАЖНО: Heroku-роутер отдаёт HTTP только процессу типа `web`, поэтому
# uvicorn (REST API) должен быть именно в `web`, иначе H14 «No web processes».
# Веб-продукт (Next.js) деплоится из поддерева frontend/ со своим Procfile.
web: uvicorn api.main:app --host 0.0.0.0 --port $PORT

# Telegram-бот живёт отдельным фоновым процессом (polling, не HTTP).
bot: python -m bot.main
