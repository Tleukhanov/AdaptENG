"""API уроков Mini App для web-продукта (Phase C).

Порт ``bot/mini_api.py`` на FastAPI: генерация деки, проверка ответа квиза,
финализация урока и голосовая реплика. Бизнес-логика берётся из
``core``/``storage`` — импорта из ``bot`` нет. Сетевые провайдеры (LLM/STT)
инжектятся из app.state, собранного в lifespan.

Контракт ответов точно совпадает с мини-app, чтобы фронт читал одни и те же
ключи. Ошибки — ``HTTPException`` (фронт читает ``detail``).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from core.analytics import track_event
from core.characters import character_prompt
from core.deck import DECK_PRESETS, Deck, deck_from_json, generate_deck
from core.lesson_plan import (
    PLAN_LESSON_COUNT,
    LessonPlan,
    LessonPlanService,
    next_plan_index,
)
from core.profile import to_profile_snippet
from core.progress import ProgressService
from core.srs import SRSService
from core.weak_areas import WeakAreaService
from storage.repo import LessonNote, LessonPlanRow

from ..deps import get_current_tg_id, get_repository, get_settings_dep, get_stt
from ..quota import QuotaExceeded, check_quota, consume_quota
from ..schemas import (
    DeckAnswerRequest,
    DeckFinishRequest,
    DeckNewRequest,
    VoiceAnswerRequest,
)

try:  # pragma: no cover - импорт зависит от наличия imageio-ffmpeg
    from providers.audio import to_wav
except ImportError:  # pragma: no cover
    to_wav = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["lessons"])

DEFAULT_PRESET = "mixed"
MAX_AUDIO_BYTES = 8 * 1024 * 1024

LLM_MISSING_ERROR = "LLM не настроен"
DECK_GENERATION_ERROR = "Не удалось сгенерировать урок"
SESSION_NOT_FOUND_ERROR = "Активный урок не найден"
CORRUPT_DECK_ERROR = "Урок повреждён"
STT_MISSING_ERROR = "STT не настроен"
NO_SPEECH_ERROR = "Не распознана речь"
AUDIO_MISSING_ERROR = "Аудио не получено"
STT_FAILED_ERROR = "Не удалось распознать речь"

_TIP_EXCELLENT = "Отлично произнесено!"
_TIP_GOOD = "Хорошо, но можно точнее повторить интонацию и звуки."
_TIP_WEAK = "Повтори фразу ещё раз — медленнее и ближе к микрофону."


# ---------- утилиты разбора ----------


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _text_or_none(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _preset_or_default(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in DECK_PRESETS:
        return value.strip().lower()
    return DEFAULT_PRESET


# ---------- контекст генерации (как в bot/lessons.py) ----------


async def _lesson_context(repo, user) -> dict[str, Any]:
    """Профиль, персонаж, слабые области и недавние темы — как у бота."""
    profile = await repo.get_profile(user.id)
    recent_notes = await repo.get_lesson_notes(user.id, limit=50)
    recent_topics = list(reversed([note.topic for note in recent_notes])) if recent_notes else None
    weak_prompt = await WeakAreaService(repo).get_top_for_prompt(user.id)
    return {
        "level": user.level,
        "profile": to_profile_snippet(profile) or None,
        "recent_topics": recent_topics,
        "character_prompt": character_prompt(profile.character if profile else ""),
        "weak_areas_prompt": weak_prompt or None,
    }


async def _planned_topic(repo, user) -> tuple[str | None, str | None]:
    """Тема и plan_hint из плана уроков (когда фронт не прислал тему)."""
    try:
        completed = await repo.count_finished_lessons(user.id)
        row = await repo.get_lesson_plan(user.id)
        if row is None:
            return None, None
        plan = LessonPlan.from_json(row.plan_json)
        idx = next_plan_index(row.based_on_lessons, completed, row.horizon)
        if idx is None or idx >= len(plan.lessons):
            return None, None
        planned = plan.lessons[idx]
        hint = f"Plan lesson {idx + 1}/{row.horizon}: {planned.topic}. Focus: {planned.focus}"
        return planned.topic, hint
    except Exception:
        logger.warning("Не удалось применить план уроков user=%s", user.id, exc_info=True)
        return None, None


async def _active_session(repo, user_id: int):
    """Активная mini-сессия пользователя или ``HTTPException`` 404."""
    session = await repo.get_active_mini_lesson(user_id)
    if session is None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND_ERROR)
    return session


# ---------- POST /api/lesson/new ----------


@router.post("/lesson/new")
async def lesson_new(
    request: Request,
    body: DeckNewRequest,
    tg_id: int = Depends(get_current_tg_id),
    settings=Depends(get_settings_dep),
    repo=Depends(get_repository),
) -> dict[str, Any]:
    """Новый урок: квота → одна LLM-генерация деки → session."""
    if getattr(request.app.state, "llm", None) is None:
        raise HTTPException(status_code=503, detail=LLM_MISSING_ERROR)

    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    topic = _text_or_none(body.topic)
    plan_hint: str | None = None
    if not topic:
        topic, plan_hint = await _planned_topic(repo, user)
    preset = _preset_or_default(body.preset)

    # Квота проверяется ДО генерации: при исчерпанном лимите LLM не дёргаем.
    try:
        await check_quota(repo, settings, user.id)
    except QuotaExceeded:
        raise HTTPException(status_code=429, detail="Дневной лимит исчерпан")

    llm = request.app.state.llm
    try:
        context = await _lesson_context(repo, user)
        deck = await generate_deck(llm, topic=topic, plan_hint=plan_hint, preset=preset, **context)
    except Exception:
        logger.exception("Ошибка генерации деки: user=%s topic=%s", user.id, topic)
        raise HTTPException(status_code=502, detail=DECK_GENERATION_ERROR)
    if deck is None:
        raise HTTPException(status_code=502, detail=DECK_GENERATION_ERROR)

    try:
        await consume_quota(repo, settings, user.id)
    except QuotaExceeded:
        logger.warning("Гонка квоты при списании деки: user=%s", user.id)

    try:
        session = await repo.start_mini_lesson(user.id, deck.topic, deck.to_json(), deck.preset)
    except Exception:
        logger.exception("Не удалось сохранить сессию урока: user=%s", user.id)
        raise HTTPException(status_code=500, detail="Не удалось сохранить урок")

    await track_event(repo, user.id, "miniapp_deck_new", {"preset": deck.preset})
    logger.info("Mini App урок: user=%s topic=%s session=%s", user.id, deck.topic, session.id)
    return {
        "deck": deck.to_dict(),
        "session_id": session.id,
        "preset": deck.preset,
        "topic": deck.topic,
        "plan_hint": plan_hint,
    }


# ---------- POST /api/lesson/answer ----------


@router.post("/lesson/answer")
async def lesson_answer(
    body: DeckAnswerRequest,
    tg_id: int = Depends(get_current_tg_id),
    repo=Depends(get_repository),
) -> dict[str, Any]:
    """Мгновенная проверка ответа квиза. В БД не пишем — итог приходит в finish."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    session = await _active_session(repo, user.id)
    deck = deck_from_json(session.content_json)
    if deck is None:
        raise HTTPException(status_code=409, detail=CORRUPT_DECK_ERROR)
    if not 0 <= body.quiz_index < len(deck.quiz):
        raise HTTPException(status_code=400, detail="Неверный вопрос")
    item = deck.quiz[body.quiz_index]
    return {
        "correct": body.chosen == item.answer_index,
        "answer_index": item.answer_index,
        "explanation": item.explanation_ru,
        "explanation_ru": item.explanation_ru,
    }


# ---------- POST /api/lesson/finish ----------


def _quiz_results(answers) -> list[dict[str, Any]]:
    """Нормализует ответы фронта в ``[{quiz_index, chosen, correct}]`` для score_json."""
    results: list[dict[str, Any]] = []
    for position, item in enumerate(answers or []):
        quiz_index = item.quiz_index
        if quiz_index is None:
            quiz_index = position
        results.append(
            {
                "quiz_index": quiz_index,
                "chosen": item.chosen,
                "correct": bool(item.correct),
            }
        )
    return results


def _repeat_words(flashcards) -> list[str]:
    """Слова, отмеченные фронтом как «повторю» (для ответа и SRS-подсказки)."""
    if not isinstance(flashcards, dict):
        return []
    return [str(word).strip() for word, known in flashcards.items() if known is False and str(word).strip()]


@router.post("/lesson/finish")
async def lesson_finish(
    request: Request,
    body: DeckFinishRequest,
    tg_id: int = Depends(get_current_tg_id),
    settings=Depends(get_settings_dep),
    repo=Depends(get_repository),
) -> dict[str, Any]:
    """Финал урока: score_json, SRS, заметка/XP, план. Никогда не отдаёт 500 из-за сбоя."""
    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    score = body.score or 0
    preset = _preset_or_default(body.preset)
    results = _quiz_results(body.quiz_answers)
    score_json = json.dumps(results, ensure_ascii=False)
    session_id = body.session_id

    session = None
    try:
        session = await repo.get_active_mini_lesson(user.id)
    except Exception:
        logger.exception("Не удалось прочитать mini-сессию: user=%s", user.id)

    if session is not None and session_id is not None and session.id != session_id:
        # Фронт повторно отправил финал уже закрытой сессии — не мешаем закрытию.
        logger.info("Mini App финал: session %s уже не активна (активна %s)", session_id, session.id)
    deck = deck_from_json(session.content_json) if session is not None else None

    repeat = _repeat_words(body.flashcards)

    if session is not None:
        try:
            await repo.finish_mini_lesson(session.id, score_json)
        except Exception:
            logger.exception("Не удалось закрыть mini-сессию: %s", session.id)

    try:
        await _save_vocabulary(repo, user.id, deck, session.id if session else 0)
    except Exception:
        logger.exception("Не удалось сохранить слова урока в SRS: user=%s", user.id)

    xp = 0
    try:
        xp = await _finalize_progress(repo, user, session, deck, score)
    except Exception:
        logger.exception("Не удалось начислить итоги урока: user=%s", user.id)

    next_topic = ""
    try:
        next_topic = await _maybe_generate_plan(request, settings, repo, user)
    except Exception:
        logger.exception("Не удалось обновить план уроков: user=%s", user.id)

    await track_event(
        repo,
        user.id,
        "miniapp_deck_finish",
        {"score": score, "preset": preset, "correct": sum(1 for item in results if item["correct"])},
    )
    logger.info(
        "Mini App финал: user=%s session=%s score=%s xp=%s",
        user.id,
        session.id if session else None,
        score,
        xp,
    )
    return {
        "score": score,
        "xp": xp,
        "next_topic": next_topic,
        "preset": preset,
        "repeat_words": repeat,
    }


async def _save_vocabulary(repo, user_id: int, deck: Deck | None, session_id: int) -> int:
    """Слова деки → SRS (как _save_lesson_vocabulary в bot/lessons.py)."""
    if deck is None or not deck.vocabulary:
        return 0
    srs = SRSService(repo)
    words = [
        {"word": card.word, "translation": card.translation, "example": card.example}
        for card in deck.vocabulary
        if card.word
    ]
    if not words:
        return 0
    added = await srs.add_words(user_id, words, lesson_id=session_id)
    if added:
        logger.info("SRS: добавлено %d слов из деки user=%s", added, user_id)
    return added


async def _finalize_progress(repo, user, session, deck: Deck | None, score: int) -> int:
    """Заметка урока → прогресс/XP/достижения. Возвращает НОВЫЙ XP (дельта)."""
    service = ProgressService(repo)
    before = (await service.get_progress(user.id, level=user.level)).xp
    if session is not None and deck is not None:
        note = _build_note(user.id, session, deck, score)
        await repo.add_lesson_note(note)
    after = (await service.get_progress(user.id, level=user.level)).xp
    return max(after - before, 0)


def _build_note(user_id: int, session, deck: Deck, score: int) -> LessonNote:
    """Заметка урока по деке — без LLM-вызова (квота уже списана за деку)."""
    words = [card.word for card in deck.vocabulary if card.word]
    vocabulary = f"+{len(words)} новых слов"
    if words:
        vocabulary += ": " + ", ".join(words[:10])
    return LessonNote(
        user_id=user_id,
        lesson_id=session.id,
        topic=session.topic or deck.topic,
        vocabulary=vocabulary,
        grammar="",
        speaking="",
        mistakes="",
        recommendation=f"Mini App: квиз {score}/{len(deck.quiz)}. Повтори слова и пройди новую тему.",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


async def _maybe_generate_plan(request: Request, settings, repo, user) -> str:
    """Логика _maybe_generate_plan из bot/lessons.py, но без сообщения в чат.

    Возвращает тему следующего урока из плана (пустая строка — плана нет).
    LLM берётся из app.state: если он не настроен — план тихо пропускается.
    """
    llm = getattr(request.app.state, "llm", None)
    next_topic = ""
    try:
        row = await repo.get_lesson_plan(user.id)
        if row is not None:
            plan = LessonPlan.from_json(row.plan_json)
            completed = await repo.count_finished_lessons(user.id)
            idx = next_plan_index(row.based_on_lessons, completed, row.horizon)
            if idx is not None and idx < len(plan.lessons):
                next_topic = plan.lessons[idx].topic
    except Exception:
        logger.warning("Не удалось прочитать план уроков user=%s", user.id, exc_info=True)

    if llm is None:
        return next_topic
    try:
        completed = await repo.count_finished_lessons(user.id)
        if completed < PLAN_LESSON_COUNT:
            return next_topic
        row = await repo.get_lesson_plan(user.id)
        if row is not None and row.based_on_lessons + row.horizon > completed:
            return next_topic  # план ещё актуален
        await check_quota(repo, settings, user.id)
        recent_notes = await repo.get_lesson_notes(user.id, limit=50)
        recent_topics = list(reversed([note.topic for note in recent_notes])) if recent_notes else []
        profile = await repo.get_profile(user.id)
        plan_service = LessonPlanService(llm)
        plan = await plan_service.generate(
            level=user.level,
            profile=to_profile_snippet(profile) or None,
            recent_topics=recent_topics,
            completed_lessons=completed,
        )
        if not plan.lessons:
            return next_topic
        await repo.save_lesson_plan(
            LessonPlanRow(
                user_id=user.id,
                plan_json=plan.to_json(),
                horizon=PLAN_LESSON_COUNT,
                based_on_lessons=completed,
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        await consume_quota(repo, settings, user.id)
        idx = next_plan_index(completed, completed, PLAN_LESSON_COUNT)
        next_topic = plan.lessons[idx or 0].topic if plan.lessons else next_topic
        logger.info(
            "План уроков сгенерирован после Mini App урока: user=%s completed=%s", user.id, completed
        )
    except QuotaExceeded:
        logger.debug("План урока пропущен (квота исчерпана): user=%s", user.id)
    except Exception:
        logger.exception("Не удалось сгенерировать план уроков user=%s", user.id)
    return next_topic


# ---------- POST /api/lesson/voice ----------


def _decode_audio(raw: str) -> bytes | None:
    """base64 из тела → байты аудио; лимит 8 МБ."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > MAX_AUDIO_BYTES:
        return None
    return data


def _normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


def _phrase_rating(transcript: str, expected: str) -> int | None:
    """Доля слов фразы, которые юзер произнёс (без LLM и списания квоты)."""
    if not expected or not expected.strip():
        return None
    expected_tokens = _normalize_tokens(expected)
    spoken_tokens = _normalize_tokens(transcript)
    if not expected_tokens:
        return None
    if not spoken_tokens:
        return 0
    spoken_set = set(spoken_tokens)
    matched = sum(1 for token in expected_tokens if token in spoken_set)
    return round(100 * matched / len(expected_tokens))


def _rating_tip(rating: int | None) -> str:
    if rating is None:
        return ""
    if rating >= 70:
        return _TIP_EXCELLENT
    if rating >= 40:
        return _TIP_GOOD
    return _TIP_WEAK


async def _convert_to_wav(src: str, dst: str) -> None:
    """to_wav через модульную ссылку (тесты подменяют api.routers.lessons.to_wav)."""
    if to_wav is not None:
        await to_wav(src, dst)
        return
    from providers.audio import to_wav as _to_wav  # pragma: no cover - резерв

    await _to_wav(src, dst)


@router.post("/lesson/voice")
async def lesson_voice(
    body: VoiceAnswerRequest,
    tg_id: int = Depends(get_current_tg_id),
    repo=Depends(get_repository),
    stt=Depends(get_stt),
) -> dict[str, Any]:
    """Голосовая реплика: аудио (base64) → STT → оценка близости к фразе."""
    audio = _decode_audio(body.audio_base64)
    if audio is None:
        raise HTTPException(status_code=400, detail=AUDIO_MISSING_ERROR)

    if stt is None:
        raise HTTPException(status_code=503, detail=STT_MISSING_ERROR)

    user = await repo.get_or_create_user(tg_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    session = await _active_session(repo, user.id)

    fd, raw_path = tempfile.mkstemp(suffix=".webm")
    os.close(fd)
    wav_path = raw_path + ".wav"
    try:
        Path(raw_path).write_bytes(audio)
        await _convert_to_wav(raw_path, wav_path)
        transcript = (await stt.transcribe(wav_path)).strip()
    except Exception:
        logger.exception("Ошибка STT голосовой реплики: user=%s", user.id)
        raise HTTPException(status_code=502, detail=STT_FAILED_ERROR)
    finally:
        for path in (raw_path, wav_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                logger.warning("Не удалось удалить временное аудио: %s", path)

    if not transcript:
        raise HTTPException(status_code=400, detail=NO_SPEECH_ERROR)

    expected = _text(body.expected_line)
    rating = _phrase_rating(transcript, expected)
    tip = _rating_tip(rating)

    word = (_text(body.word) or expected or transcript)[:120]
    try:
        await repo.save_audio_answer(
            session.id,
            word=word,
            audio_file="",  # аудио не персистим в MVP — храним расшифровку и оценку
            transcript=transcript[:500],
            rating=rating,
        )
        await track_event(
            repo,
            getattr(session, "user_id", user.id),
            "miniapp_voice_answer",
            {"rating": rating, "matched": expected},
        )
    except Exception:
        logger.exception("Не удалось сохранить голосовую реплику: session=%s", session.id)

    return {
        "transcript": transcript,
        "rating": rating,
        "tip": tip,
        "expected_line": expected,
    }
