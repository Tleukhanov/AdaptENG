"""Сессии и учётные данные web-продукта AdaptENG.

Что здесь есть:

* ``hash_password`` / ``verify_password`` — PBKDF2-HMAC-SHA256 из стандартной
  библиотеки (без внешних зависимостей). Формат хранения:
  ``pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>``.
* ``create_access_token`` / ``decode_access_token`` — JWT HS256. Внутри токена
  теперь внутренний ``users.id``, а не Telegram ID: идентичность больше не
  привязана к Telegram.
* Куки сессии: HttpOnly + SameSite=Lax + Secure (в проде). Фронт шлёт их
  автоматически (same-origin прокси), поэтому токен не лежит в localStorage.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

import jwt

from core.config import Settings

PBKDF2_ITERATIONS = 200_000
PASSWORD_SCHEME = "pbkdf2_sha256"
MIN_PASSWORD_LENGTH = 8


# ---------- пароли ----------


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Хеш пароля с индивидуальной солью."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "{}${}${}${}".format(
        PASSWORD_SCHEME,
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    """Сверяет пароль с хешем. Невалидный формат → False (без исключений)."""
    if not stored:
        return False
    try:
        scheme, iterations_text, salt_b64, hash_b64 = stored.split("$")
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def password_problem(password: str) -> str | None:
    """Возвращает текст проблемы с паролем или None, если пароль подходит."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов"
    if len(password) > 200:
        return "Пароль слишком длинный"
    return None


# ---------- JWT ----------


def create_access_token(settings: Settings, user_id: int) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + settings.jwt_ttl_days * 86_400,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> int | None:
    """Возвращает ``users.id`` по токену или ``None`` при любой ошибке."""
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


# ---------- сессия в cookie ----------


def new_session_id() -> str:
    return secrets.token_urlsafe(24)


def set_session_cookie(response, settings: Settings, token: str) -> None:
    """Ставит HttpOnly-cookie с JWT-сессией."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.jwt_ttl_days * 86_400,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response, settings: Settings) -> None:
    """Сбрасывает cookie сессии (выход)."""
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
