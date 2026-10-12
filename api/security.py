"""JWT-сессии для веб-версии AdaptENG.

Токены HS256: секрет берётся из настроек (обязателен при запуске api),
период жизни — ``jwt_ttl_days`` дней. Внутри токена — только ``tg_id``.
"""

from __future__ import annotations

import time

import jwt

from core.config import Settings


def create_access_token(settings: Settings, tg_id: int) -> str:
    now = int(time.time())
    payload = {
        "sub": str(tg_id),
        "iat": now,
        "exp": now + settings.jwt_ttl_days * 86_400,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> int | None:
    """Возвращает ``tg_id`` по токену или ``None`` при любой ошибке."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None


def require_secret(settings: Settings) -> None:
    """Падает с внятной ошибкой, если JWT-секрет не задан."""
    if not settings.jwt_secret.strip():
        raise RuntimeError(
            "JWT_SECRET не задан. Укажи его в .env/Heroku (напр. openssl rand -hex 32) "
            "прежде чем поднимать api."
        )