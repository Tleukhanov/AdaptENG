# Корневой монорепо деплоится как приложение API+бот (adapteng-api).
# ВАЖНО: Heroku-роутер отдаёт HTTP только процессу типа `web`, поэтому
# uvicorn (REST API) должен быть именно в `web`, иначе H14 «No web processes».
# Бот Telegram обслуживается тем же процессом: webhook регистрируется в
# FastAPI при USE_WEBHOOK=1, поэтому отдельный web-процесс не нужен.
# Процесс `bot` оставлен для локального polling (масштабирование: web=1, bot=0).
web: uvicorn api.main:app --host 0.0.0.0 --port $PORT --workers 1

# Telegram-бот живёт отдельным фоновым процессом (polling, не HTTP).
bot: python -m bot.main
