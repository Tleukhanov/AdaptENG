"""Middleware лимита запросов на клиента (защита от флуда).

Скользящее окно по IP (с учётом X-Forwarded-For за прокси Heroku/nginx).
При превышении — 429 с ``Retry-After``. Лимит задаётся
``api_rate_limit_per_min`` (0 = выключить).
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .deps import client_key
from .loadguard import ClientWindowLimiter

logger = logging.getLogger(__name__)

_EXEMPT_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:  # noqa: D107 - лимитер берём из app.state
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # ВАЖНО: self.app — это следующий middleware в стеке, а не FastAPI.
        # Приложение доступно как request.app.
        limiter = getattr(request.app.state, "client_limiter", None) or _NULL_LIMITER
        if path in _EXEMPT_PATHS or limiter.limit <= 0:
            return await call_next(request)

        key = client_key(request)
        if not limiter.allow(key):
            return JSONResponse(
                status_code=429,
                content={"detail": "Слишком много запросов, попробуй чуть позже"},
                headers={"Retry-After": str(int(limiter.window_sec))},
            )
        return await call_next(request)


# Заглушка на случай, если lifespan ещё не отработал (или тест без него).
_NULL_LIMITER = ClientWindowLimiter(window_sec=60.0, limit=0)