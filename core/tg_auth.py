"""Проверка авторизации Telegram Login Widget (веб-landing AdaptENG).

Виджет (telegram-widget.js) присылает на POST /api/auth/tg объект
``{id, first_name, last_name, username, photo_url, auth_date, hash}``.

Верификация отличается от Mini App (bot/webapp.py):
для виджета secret_key = SHA256(bot_token) (без HMAC-обёртки ``WebAppData``),
а ``data_check_string`` строится из плоских скалярных полей.

Все функции чистые: без сети и БД.
"""

import hashlib
import hmac
import time
from collections.abc import Mapping
from typing import Any


def widget_secret_key(bot_token: str) -> bytes:
    """secret_key для Login Widget = raw SHA256 от токена бота."""
    return hashlib.sha256(bot_token.encode("utf-8")).digest()


def widget_data_check_string(params: Mapping[str, str]) -> str:
    """Пары ``k=v`` по алфавиту через ``\\n``, без ``hash``."""
    return "\n".join(f"{key}={value}" for key, value in sorted(params.items()) if key != "hash")


def widget_compute_hash(bot_token: str, params: Mapping[str, str]) -> str:
    return hmac.new(
        widget_secret_key(bot_token),
        widget_data_check_string(params).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sign_login_widget(bot_token: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Набор параметров с валидным ``hash`` (используется в тестах)."""
    payload = {str(key): str(value) for key, value in params.items() if key != "hash"}
    payload["hash"] = widget_compute_hash(bot_token, payload)
    return payload


def verify_login_widget(
    bot_token: str,
    params: Mapping[str, Any],
    max_age_sec: int = 86_400,
) -> dict[str, Any] | None:
    """Проверяет подпись виджета и возвращает нормализованные поля пользователя.

    ``None`` — нет токена/hash, подпись не совпала, нет ``id`` или устарел
    ``auth_date``. Возврат: ``{id, first_name, last_name, username,
    photo_url, auth_date}`` с ``id``/``auth_date`` как ``int``.
    """
    if not bot_token or not params:
        return None
    text_params = {str(key): str(value) for key, value in params.items()} | {"hash": ""}
    text_params["hash"] = str(params.get("hash", ""))
    received_hash = text_params["hash"]
    if not received_hash:
        return None
    expected_hash = widget_compute_hash(bot_token, text_params)
    if not hmac.compare_digest(expected_hash, received_hash):
        return None
    try:
        user_id = int(params["id"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        auth_date = int(params.get("auth_date", 0))
    except (TypeError, ValueError):
        auth_date = 0
    if max_age_sec > 0 and auth_date and time.time() - auth_date > max_age_sec:
        return None
    return {
        "id": user_id,
        "first_name": str(params.get("first_name", "")),
        "last_name": str(params.get("last_name", "")),
        "username": str(params.get("username", "")),
        "photo_url": str(params.get("photo_url", "")),
        "auth_date": auth_date,
    }