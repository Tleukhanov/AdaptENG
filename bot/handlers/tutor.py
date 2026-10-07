"""Хэндлер /tutor — RAG-тьютор грамматики.

Отдельный режим (TutorState): внутри него вопросы по грамматике отвечает RAG
по корпусу правил. RAG ДОПОЛНЯЕТ адаптивную практику, не подменяя её:
обычные потоки (практика, уроки, диагностика, SRS) не затронуты — туда всё
попадает как раньше. Выход из тьютора — кнопкой или любой командой.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from core.rag import RAGGrammarTutor
from storage.repo import Repository

from ..flow import get_or_create_user
from ..keyboards import main_menu, tutor_keyboard
from ..quota import QUOTA_EXCEEDED_TEXT, QuotaExceeded, QuotaGuard

router = Router()
logger = logging.getLogger(__name__)

TUTOR_HELP = (
    "🎓 <b>Грамматика</b> — отвечу по нашим правилам и примерам.\n\n"
    "Спрашивай на русском или английском, например:\n"
    "«объясни разницу Present Perfect и Past Simple», «когда артикль the?»…\n\n"
    "Жми «⏹️ Выйти», чтобы вернуться к практике."
)


class TutorState(StatesGroup):
    waiting = State()


async def _profile_for(repo: Repository, user_id: int) -> dict:
    level = "B1"
    user = await repo.get_user(user_id)
    if user is not None and user.level:
        level = user.level
    interests: list[str] = []
    profile_row = await repo.get_profile(user_id)
    if profile_row is not None and profile_row.interests:
        interests = [part.strip() for part in profile_row.interests.split(",") if part.strip()]
    return {"level": level, "interests": interests}


@router.message(Command("tutor"))
async def cmd_tutor_start(message: Message, repo: Repository, state: FSMContext) -> None:
    await get_or_create_user(message, repo)
    await state.set_state(TutorState.waiting)
    await message.answer(TUTOR_HELP, reply_markup=tutor_keyboard())


@router.callback_query(F.data == "tutor:start")
async def cb_tutor_start(callback: CallbackQuery, repo: Repository, state: FSMContext) -> None:
    await callback.answer()
    await get_or_create_user(callback.message, repo)
    await state.set_state(TutorState.waiting)
    await callback.message.answer(TUTOR_HELP, reply_markup=tutor_keyboard())


@router.callback_query(F.data == "tutor:cancel")
async def cb_tutor_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "Грамматика закрыта. Возвращаемся к практике 🙂",
        reply_markup=main_menu(),
    )


@router.message(TutorState.waiting, F.text, ~F.text.startswith("/"))
async def on_tutor_question(
    message: Message,
    repo: Repository,
    tutor: RAGGrammarTutor,
    state: FSMContext,
    quota: QuotaGuard | None = None,
) -> None:
    question = message.text.strip()
    if not question:
        return

    user = await get_or_create_user(message, repo)
    profile = await _profile_for(repo, user.id)

    if quota is not None:
        try:
            await quota.check(user.id)
        except QuotaExceeded:
            await message.answer(QUOTA_EXCEEDED_TEXT, reply_markup=main_menu())
            return

    try:
        answer, mode, _citations = await tutor.answer(question, profile)
    except Exception:  # noqa: BLE001 — LLM недоступен
        logger.exception("RAG-tutor LLM error")
        await message.answer(
            "⚠️ Не получилось ответить. Попробуй ещё раз или выйди кнопкой ниже.",
            reply_markup=tutor_keyboard(),
        )
        return

    if quota is not None:
        try:
            await quota.consume(user.id, cost=1)
        except QuotaExceeded:
            await message.answer(QUOTA_EXCEEDED_TEXT, reply_markup=main_menu())
            return

    prefix = "📖 Разобрал по правилам:" if mode == "rag" else "💬 Отвечаю без справочника:"
    await message.answer(f"{prefix}\n\n{answer}", reply_markup=tutor_keyboard())
    await state.set_state(TutorState.waiting)