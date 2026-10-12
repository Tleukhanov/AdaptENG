"""Юнит-тесты HMAC-проверки Telegram Login Widget (core.tg_auth)."""

from __future__ import annotations

import time

import pytest

from core.tg_auth import (
    sign_login_widget,
    verify_login_widget,
    widget_compute_hash,
    widget_data_check_string,
    widget_secret_key,
)


TOKEN = "123456:ABCDEF-test-token"
BASE_PARAMS = {
    "id": 999888777,
    "first_name": "Аня",
    "last_name": "Тестова",
    "username": "anya_t",
    "photo_url": "https://t.me/img.png",
    "auth_date": int(time.time()),
}


def test_valid_signature_returns_user() -> None:
    signed = sign_login_widget(TOKEN, BASE_PARAMS)
    result = verify_login_widget(TOKEN, signed)
    assert result is not None
    assert result["id"] == 999888777
    assert result["username"] == "anya_t"
    assert result["first_name"] == "Аня"


def test_tampered_field_fails() -> None:
    signed = sign_login_widget(TOKEN, BASE_PARAMS)
    signed["first_name"] = "Злой_хакер"
    assert verify_login_widget(TOKEN, signed) is None


def test_wrong_token_fails() -> None:
    signed = sign_login_widget(TOKEN, BASE_PARAMS)
    assert verify_login_widget(TOKEN + "x", signed) is None


def test_missing_hash_fails() -> None:
    assert verify_login_widget(TOKEN, dict(BASE_PARAMS)) is None


def test_missing_id_fails() -> None:
    params = {k: v for k, v in BASE_PARAMS.items() if k != "id"}
    signed = sign_login_widget(TOKEN, params)
    assert verify_login_widget(TOKEN, signed) is None


def test_expired_auth_date_fails() -> None:
    params = dict(BASE_PARAMS)
    params["auth_date"] = int(time.time()) - 10 * 86_400  # 10 дней назад
    signed = sign_login_widget(TOKEN, params)
    assert verify_login_widget(TOKEN, signed, max_age_sec=86_400) is None
    assert verify_login_widget(TOKEN, signed, max_age_sec=0) is not None


def test_secret_key_is_raw_sha256() -> None:
    import hashlib

    key = widget_secret_key(TOKEN)
    assert key == hashlib.sha256(TOKEN.encode("utf-8")).digest()


def test_data_check_string_sorted_and_excludes_hash() -> None:
    params = {"b": "2", "hash": "x", "a": "1"}
    assert widget_data_check_string(params) == "a=1\nb=2"


def test_recomputes_expected_hash() -> None:
    params = {"id": "5", "username": "u"}
    assert widget_compute_hash(TOKEN, params) == widget_compute_hash(TOKEN, params)
    assert widget_compute_hash(TOKEN, params) != widget_compute_hash(TOKEN + "z", params)


def test_str_number_values_accepted() -> None:
    params = dict(BASE_PARAMS)
    params["id"] = 123  # int — виджет может прислать и число, и строку
    signed = sign_login_widget(TOKEN, params)
    result = verify_login_widget(TOKEN, signed)
    assert result is not None
    assert result["id"] == 123