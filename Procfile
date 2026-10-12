web: python -m bot.main
# Веб-продукт AdaptENG (Фаза A): для adapteng-api приложения на Heroku
# запускается отдельно: heroku ps:scale web=0 api=1 --app adapteng-api
api: uvicorn api.main:app --host 0.0.0.0 --port $PORT