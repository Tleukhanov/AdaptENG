"""Web-продукт AdaptENG: отдельный FastAPI-сервис на общем ядре (core/ + storage/).

Запуск: ``uvicorn api.main:app --host 0.0.0.0 --port 8000``
(Heroku: ``web: uvicorn api.main:app --host 0.0.0.0 --port $PORT``).
"""

__version__ = "0.1.0"