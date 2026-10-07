"""Инлайн-клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

MINI_APP_BUTTON_TEXT = "📱 Урок в Mini App"
CLASSIC_LESSON_BUTTON_TEXT = "📚 Классический урок"
TUTOR_BUTTON_TEXT = "🎓 Спросить грамматику"

# Публичный HTTPS-URL Mini App. Задаётся один раз при старте (см. bot/main.py),
# чтобы кнопка появлялась во всех main_menu() без правок всех вызывающих мест.
_WEBAPP_URL: str = ""


def set_webapp_url(url: str) -> None:
    """Запоминает URL Mini App (пустая строка — кнопка выключена)."""
    global _WEBAPP_URL
    _WEBAPP_URL = (url or "").strip()


def get_webapp_url() -> str:
    """Текущий URL Mini App (пустая строка — выключен)."""
    return _WEBAPP_URL


def miniapp_button(url: str | None = None) -> InlineKeyboardButton | None:
    """Кнопка открытия Mini App или None, если Mini App выключен."""
    target = (url if url is not None else _WEBAPP_URL).strip()
    if not target:
        return None
    return InlineKeyboardButton(text=MINI_APP_BUTTON_TEXT, web_app=WebAppInfo(url=target))


def _base_menu_rows(due_words: int = 0) -> list[list[InlineKeyboardButton]]:
    review_text = f"📖 Повторить слова ({due_words})" if due_words > 0 else "📖 Повторить слова"
    rows = [
        [InlineKeyboardButton(text="📚 Начать урок", callback_data="lesson_start")],
    ]
    miniapp = miniapp_button()
    if miniapp is not None:
        rows.append([miniapp])
    rows += [
        [InlineKeyboardButton(text=review_text, callback_data="review:start")],
        [InlineKeyboardButton(text=TUTOR_BUTTON_TEXT, callback_data="tutor:start")],
        [InlineKeyboardButton(text="🎯 Определить уровень", callback_data="diagnostic_start")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [
            InlineKeyboardButton(text="📈 Прогресс", callback_data="progress"),
            InlineKeyboardButton(text="🏆 Достижения", callback_data="achievements"),
            InlineKeyboardButton(text="🏅 Рейтинг", callback_data="leaderboard"),
        ],
        [InlineKeyboardButton(text="🎡 Колесо удачи", callback_data="wheel:start")],
        [InlineKeyboardButton(text="💎 Подписка", callback_data="premium:open")],
        [
            InlineKeyboardButton(text="📚 Подготовка к экзамену", callback_data="exam_prep"),
            InlineKeyboardButton(text="📮 Связь с разработчиком", callback_data="contact_dev"),
        ],
        [InlineKeyboardButton(text="🧠 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🔄 Сброс", callback_data="reset")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ]
    return rows


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_base_menu_rows())


def main_menu_with_srs(due_words: int = 0) -> InlineKeyboardMarkup:
    """Главное меню с указанием количества слов для повторения."""
    return InlineKeyboardMarkup(inline_keyboard=_base_menu_rows(due_words))


def tutor_keyboard() -> InlineKeyboardMarkup:
    """Кнопки режима тьютора (RAG-грамматика): только выход."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏹️ Выйти из тьютора", callback_data="tutor:cancel")],
        ]
    )


def premium_upsell_keyboard(days: int = 7) -> InlineKeyboardMarkup:
    """Клавиатура-апселл при исчерпании квоты: кнопка покупки подписки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить подписку", callback_data=f"premium:buy:{days}")],
        ]
    )


def miniapp_lesson_keyboard(url: str | None = None) -> InlineKeyboardMarkup | None:
    """Выбор формата урока: Mini App (web_app) или классический урок в чате.

    None — если Mini App выключен (не задан WEBAPP_URL).
    """
    miniapp = miniapp_button(url)
    if miniapp is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [miniapp],
            [InlineKeyboardButton(text=CLASSIC_LESSON_BUTTON_TEXT, callback_data="lesson_start")],
        ]
    )


def lesson_keyboard() -> InlineKeyboardMarkup:
    """Кнопки навигации по уроку."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Дальше", callback_data="lesson:next")],
            [
                InlineKeyboardButton(text="🔁 Повторить", callback_data="lesson:repeat"),
                InlineKeyboardButton(text="⏹️ Завершить", callback_data="lesson:end"),
            ],
        ]
    )


def lesson_recap_keyboard() -> InlineKeyboardMarkup:
    """Кнопки на финальном шаге recap — только завершить."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить", callback_data="lesson:repeat")],
            [InlineKeyboardButton(text="🎓 Завершить урок", callback_data="lesson:end")],
        ]
    )


def diagnostic_keyboard() -> InlineKeyboardMarkup:
    """Кнопки диагностики: пропустить задание или завершить досрочно."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏭️ Пропустить", callback_data="diagnostic:skip"),
                InlineKeyboardButton(text="⏹️ Завершить досрочно", callback_data="diagnostic:end"),
            ]
        ]
    )


def reveal_keyboard(message_id: int = 0) -> InlineKeyboardMarkup:
    """Кнопка «Показать ошибку» — мягкий фидбек вместо вываливания всех ошибок сразу."""
    data = f"practice:reveal:{message_id}" if message_id else "practice:reveal"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Показать ошибку", callback_data=data)],
        ]
    )


def topic_proposals_keyboard(proposals: list[dict]) -> InlineKeyboardMarkup:
    """Кнопки выбора темы из предложений (Фаза 2)."""
    buttons = []
    for i, p in enumerate(proposals):
        topic = p["topic"]
        desc = p["description"]
        label = f"📚 {topic} — {desc}" if desc else f"📚 {topic}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"lesson:select_topic:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
