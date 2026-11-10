"""Премиум/подписка: статус, тарифы и покупка (/premium)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

from core.analytics import track_event

from bot.config import Settings
from storage.repo import Repository

from ..keyboards import main_menu
from ..quota import QuotaGuard

router = Router()
logger = logging.getLogger(__name__)


def premium_keyboard(plans: list[tuple[int, int]], coupon=None) -> InlineKeyboardMarkup:
    """Кнопки покупки подписки. Coupon — WheelCoupon|None со скидкой."""
    rows: list[list[InlineKeyboardButton]] = []
    for days, price in plans:
        final = price
        if coupon is not None and not coupon.is_expired:
            final = price - price * coupon.discount_pct // 100
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Купить {days} дней — {final}₸ (-{coupon.discount_pct}%)",
                        callback_data=f"premium:buy:{days}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Купить {days} дней — {price}₸",
                        callback_data=f"premium:buy:{days}",
                    )
                ]
            )
    # Stars-кнопки (если включены)
    stars_plans = settings.stars_subscription_plan_list  # type: ignore[name-defined]
    if stars_plans:
        rows.append(
            [InlineKeyboardButton(text="⭐ Оплатить звёздами Telegram", callback_data="stars:menu")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("premium"))
async def cmd_premium(
    message: Message, repo: Repository, settings: Settings, quota: QuotaGuard
) -> None:
    user = await repo.get_or_create_user(
        message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await track_event(repo, user.id, "premium_screen_shown")
    lines: list[str] = ["💎 <b>Лимиты и подписка</b>\n"]
    sub = await repo.get_subscription(user.id)
    if sub and sub.is_active:
        lines.append(f"✅ Подписка активна: {sub.plan_days} дн., до {sub.expires_at[:10]}")
    else:
        lines.append("➖ Подписки нет — действует дневной лимит.")
    if await repo.get_unlimited_status(user.id):
        lines.append("♾️ Промокод: <b>безлимит</b> активен")
    if settings.llm_daily_limit > 0:
        used = await repo.get_llm_usage(user.id, quota._today())
        lines.append(f"📊 ИИ-действий сегодня: {used}/{settings.llm_daily_limit}")
    extra = await repo.get_extra_actions(user.id)
    lines.append(f"🎁 Бонусных действий сверх лимита: {extra}")
    coupon = await repo.get_active_coupon(user.id)
    if coupon and not coupon.is_expired:
        lines.append(f"🎟 Купон на скидку {coupon.discount_pct}% при покупке!")
    await message.answer(
        "\n".join(lines),
        reply_markup=premium_keyboard(settings.subscription_plan_list, coupon=coupon),
    )
    logger.info("/premium: user=%s", user.id)


@router.callback_query(F.data.startswith("premium:buy:"))
async def cb_premium_buy(callback: CallbackQuery, repo: Repository, settings: Settings) -> None:
    await callback.answer()
    days_text = callback.data.removeprefix("premium:buy:")
    try:
        days = int(days_text)
    except ValueError:
        await callback.message.answer("❌ Некорректный тариф.")
        return
    plan = next((p for p in settings.subscription_plan_list if p[0] == days), None)
    if plan is None:
        await callback.answer("Не найден тариф")
        return
    user = await repo.get_or_create_user(
        callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    await track_event(repo, user.id, "premium_buy_clicked", {"days": days})
    price = plan[1]
    coupon = await repo.get_active_coupon(user.id)
    discount = 0
    final = price
    if coupon and not coupon.is_expired:
        discount = coupon.discount_pct
        final = price - price * discount // 100
    text = f"Подписка {days} дней, цена {final}₸"
    if discount:
        text += f" (со скидкой {discount}%)"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🪙 Оплатить Kaspi QR", callback_data=f"kaspi:pay:{days}"
                )
            ]
        ]
    )
    await callback.message.answer(text, reply_markup=keyboard)
    logger.info("premium buy: user=%s days=%s final=%s", user.id, days, final)


@router.callback_query(F.data.startswith("stars:pay:"))
async def cb_stars_pay(callback: CallbackQuery, repo: Repository, settings: Settings) -> None:
    """Купить подписку через Telegram Stars."""
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
        await callback.answer("Не найден тариф")
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
        logger.exception("Stars-инвойс не отправлен: user=%s days=%s", user.id, days)
        await callback.message.answer(
            "❌ Не удалось выставить счёт. Попробуйте позже или напишите @Napaleonwww"
        )
        return

    logger.info("Stars-инвойс отправлен: user=%s days=%s stars=%s", user.id, days, price_stars)