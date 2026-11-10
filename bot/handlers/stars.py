"""Оплата подписки через Telegram Stars (звёзды Telegram).

Покупатель нажимает кнопку «Оплатить Stars», бот выставляет инвойс через
bot.send_invoice, Telegram подтверждает оплату (successful_payment), и
подписка выдаётся автоматически через grant_subscription.

Не требует ручного подтверждения админа — в отличие от Kaspi QR.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
)

from core.config import Settings
from storage.repo import Repository

router = Router()
logger = logging.getLogger(__name__)

# Цены в минимальных единицах валюты Telegram (звёзды = XTR).
# 1 звезда ≈ 1 XTR (цены задаются в Stars, без копеек).


def stars_keyboard(plans: list[tuple[int, int]]) -> InlineKeyboardMarkup:
    """Кнопки покупки подписки через Telegram Stars."""
    rows: list[list[InlineKeyboardButton]] = []
    for days, stars in plans:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"⭐ {days} дн. — {stars} звёзд",
                    callback_data=f"stars:pay:{days}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("stars:pay:"))
async def cb_stars_pay(
    callback: CallbackQuery, repo: Repository, settings: Settings
) -> None:
    """Пользователь нажал «Оплатить Stars» — выставляем инвойс."""
    await callback.answer()

    if not settings.stars_payment_enabled:
        await callback.message.answer(
            "❌ Оплата через Stars пока недоступна. Попробуйте Kaspi QR через /premium."
        )
        return

    days_text = callback.data.removeprefix("stars:pay:")
    try:
        days = int(days_text)
    except ValueError:
        await callback.message.answer("❌ Некорректный тариф.")
        return

    plans = settings.resolved_stars_subscription_plan_list
    plan = next((p for p in plans if p[0] == days), None)
    if plan is None:
        await callback.answer("Не найден тариф.")
        return

    user = await repo.get_or_create_user(
        callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )

    price_stars = plan[1]
    payload = f"stars:{days}d:{user.id}"

    try:
        await callback.message.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"AdaptENG — подписка на {days} дней",
            description=f"Английский с AI-наставником: подписка на {days} дней",
            payload=payload,
            provider_token="",  # пусто для Telegram Stars
            currency="XTR",  # Telegram Stars
            prices=[LabeledPrice(label=f"Подписка {days} дн.", amount=price_stars)],
            start_parameter="stars_subscription",
        )
    except Exception:
        logger.exception(
            "Stars-инвойс не отправлен: user=%s days=%s", user.id, days
        )
        await callback.message.answer(
            "❌ Не удалось выставить счёт. Попробуйте позже или напишите @Napaleonwww"
        )
        return

    logger.info(
        "Stars-инвойс отправлен: user=%s days=%s stars=%s", user.id, days, price_stars
    )


@router.pre_checkout_query()
async def pre_checkout_query_handler(query: PreCheckoutQuery) -> None:
    """Подтверждаем инвойс перед оплатой."""
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, repo: Repository) -> None:
    """Платёж через Stars подтверждён — выдаём подписку."""
    assert message.successful_payment is not None
    payment = message.successful_payment
    payload = payment.invoice_payload

    # Парсим payload: stars:{days}d:{user_id}
    try:
        parts = payload.split(":")
        if len(parts) != 3 or parts[0] != "stars":
            raise ValueError("bad payload")
        days = int(parts[1])
        user_id = int(parts[2])
    except (ValueError, IndexError):
        logger.exception("Неверный payload в successful_payment: %s", payload)
        await message.answer(
            "❌ Ошибка обработки платежа. Напишите @Napaleonwww"
        )
        return

    # Проверяем, что плательщик — тот же пользователь
    if message.from_user.id != user_id:
        await message.answer("❌ Платёж не относится к вашему аккаунту.")
        return

    # Выдаём подписку
    sub = await repo.grant_subscription(user_id, days)
    if sub is None:
        await message.answer(
            "❌ Не удалось активировать подписку. Напишите @Napaleonwww"
        )
        return

    await track_event(
        repo, user_id, "stars_payment_completed", {"days": days, "stars": payment.total_amount}
    )

    await message.answer(
        f"🎉 Спасибо за покупку!\n\n"
        f"✅ Подписка на {days} дней активирована.\n"
        f"💫 Списано {payment.total_amount} звёзд.\n"
        f"Подписка действует до {sub.expires_at[:10]}."
    )
    logger.info(
        "Stars-подписка выдана: user=%s days=%s stars=%s",
        user_id,
        days,
        payment.total_amount,
    )


# ------- Регистрация хендлеров -------

def setup_stars(dp) -> None:
    """Регистрирует хендлеры Stars-оплаты в диспетчере."""
    dp.include_router(router)
    logger.info("Stars-платёжные хендлеры зарегистрированы")
