web: python -m bot.main
# Веб-продукт AdaptENG (Фаза A): для adapteng-api приложения на Heroku
# запускается отдельно: heroku ps:scale web=0 api=1 --app adapteng-api
api: uvicorn api.main:app --host 0.0.0.0 --port $PORT

# --- Фаза D: web-продукт (Next.js standalone, Next 15) ---
# Папка frontend деплоится как отдельное приложение (adapteng-web).
# В корне монорепо Procfile нужен только для bot/api, поэтому web-процесс
# описан в frontend/Procfile.
