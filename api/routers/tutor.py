"""Наставник (web-продукт): «Урок 0» и персональный урок ``mode="lesson"``.

Три эндпоинта:

* ``POST /api/tutor/session`` — создать сессию и получить первый ход;
* ``POST /api/tutor/turn`` — ответ студента и следующий ход наставника;
* ``POST /api/tutor/finish`` — итог: оценка CEFR, интересы, мягкая обратная
  связь; для залогиненных — XP, заметка урока, новые слова в SRS и
  обновление профиля.

Работает и для гостя (подписанная cookie ``adapteng_tutor``), и для
залогиненного пользователя. Логика диалога — в ``core.tutor``, здесь только
HTTP, лимиты и интеграция с прогрессом.
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.analytics import track_event
from core.config import Settings
from core.lesson_plan import LessonPlan
from core.profile import to_profile_snippet
from core.progress import ProgressService
from core.srs import SRSService
from core.tutor import (
    DEFAULT_LESSON_TOPIC,
    first_turn,
    TutorService,
    TutorSummary,
    TutorTurn,
    apply_turn,
    fallback_summary,
    finalize,
    last_turn,
    new_state,
)
from core.weak_areas import WeakAreaService
from storage.repo import LessonNote, Repository, TutorSession, UserProfile

from ..deps import (
    client_key,
    current_user,
    get_llm,
    get_optional_user_id,
    get_repository,
    get_settings_dep,
)
from ..loadguard import QueueFull
from ..quota import QuotaExceeded, check_quota, consume_quota
from ..schemas import (
    TutorCorrectionOut,
    TutorFinishRequest,
    TutorFinishResponse,
    TutorIssueOut,
    TutorSessionRequest,
    TutorSessionResponse,
    TutorSummaryOut,
    TutorTurnOut,
    TutorTurnRequest,
    TutorTurnResponse,
)
from ..security import decode_tutor_token, new_guest_token, set_tutor_cookie
from .guest import guest_profile_from_request

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

logger = logging.getLogger(__name__)

LLM_MISSING_ERROR = "LLM не настроен"
LLM_ERROR = "Наставник задумался и не ответил — попробуй ещё раз через минуту"
QUEUE_FULL_ERROR = "Сейчас много запросов — очередь переполнена, попробуй через минуту"
THROTTLE_ERROR = "Слишком часто — дай наставнику секунду"
QUOTA_ERROR = "Дневной лимит исчерпан"
GUEST_LIMIT_ERROR = "На сегодня ходов достаточно — зарегистрируйся, чтобы продолжить заниматься"
SESSION_NOT_FOUND_ERROR = "Урок не найден"
SESSION_FINISHED_ERROR = "Урок уже завершён"
MAX_TURNS_ERROR = "Урок завершён — нажми «Завершить», чтобы получить итог"

#: Тема заметки урока в прогрессе.
TUTOR_TOPIC = "Урок 0: знакомство"
#: Префикс темы заметки для персонального урока (mode=lesson).
LESSON_NOTE_PREFIX = "Урок: "
#: XP за завершённый урок 0 (как +10 за урок в ProgressService).
TUTOR_XP = 10
#: Фолбэк числа ходов, если в состоянии сессии его нет (старые записи).
MAX_TURNS_DEFAULT = 7
#: Минимум ходов персонального урока: раньше 6-го хода урок не завершается.
LESSON_MIN_TURNS = 5


# ---------- утилиты ----------


def _service(settings: Settings, mode: str = "intro") -> TutorService:
    lesson = (mode or "intro").strip().lower() == "lesson"
    return TutorService(
        max_turns=settings.tutor_lesson_max_turns if lesson else settings.tutor_max_turns,
        min_turns=LESSON_MIN_TURNS if lesson else settings.tutor_min_turns,
    )


def _split_list(value: str) -> list[str]:
    """Строка «a, b, c» → список без пустых элементов."""
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _add_unique(items: list[str], additions: list[str]) -> list[str]:
    for item in additions:
        text = str(item).strip()
        if text and text not in items:
            items.append(text)
    return items


async def _lesson_context(
    repo: Repository,
    user_id: int,
    profile: UserProfile | None,
    last_note: LessonNote | None,
) -> tuple[list[str], list[str]]:
    """Прошлые ошибки и интересы для урока: профиль + weak_areas + заметка."""
    weak_areas = _split_list(profile.weak_areas) if profile else []
    interests = _split_list(profile.interests) if profile else []

    for area in await WeakAreaService(repo).get_weak_areas(user_id):
        _add_unique(weak_areas, [area.area])
    if last_note is not None:
        _add_unique(weak_areas, _split_list(last_note.mistakes))

    return weak_areas[:6], interests[:8]


#: Курированные темы для уроков 1+: всегда по-английски и «расширяют кругозор».
ENGLISH_LESSON_TOPICS = (
    "Small talk at work",
    "Coffee and food culture",
    "Travelling and airports",
    "Technology in daily life",
    "Movies and series worth discussing",
    "Healthy habits and sport",
    "Money and shopping",
    "City life: pros and cons",
    "Learning new skills",
    "Music that brings people together",
)


async def _pick_lesson_topic(
    repo: Repository,
    user_id: int | None,
    interests: list[str],
    weak_areas: list[str],
    requested: str | None,
) -> str:
    """Тема урока: запрос → план уроков → интересы → прошлые ошибки → дефолт."""
    if requested and requested.strip():
        return requested.strip()

    if user_id is not None:
        plan_row = await repo.get_lesson_plan(user_id)
        if plan_row is not None:
            plan = LessonPlan.from_json(plan_row.plan_json)
            if plan.lessons:
                completed = await repo.count_finished_lessons(user_id)
                offset = max(completed - int(plan_row.based_on_lessons or 0), 0)
                lesson = plan.lessons[min(offset, len(plan.lessons) - 1)]
                if lesson.topic.strip():
                    return lesson.topic.strip()

    # Интересы используем как источник примеров в промпте, а не как название
    # темы: интерес может быть записан по-русски («шахматы»), а тема урока
    # должна звучать по-английски. Поэтому берём тему из курированного списка.
    if interests or weak_areas:
        base = user_id if user_id is not None else len(interests) + len(weak_areas)
        return ENGLISH_LESSON_TOPICS[base % len(ENGLISH_LESSON_TOPICS)]
    return DEFAULT_LESSON_TOPIC


def _last_note_snippet(note: LessonNote) -> str:
    """Короткая строка о прошлом уроке для системного промпта."""
    parts: list[str] = []
    if note.topic:
        parts.append(f"Last lesson topic: {note.topic}")
    if note.vocabulary:
        parts.append(f"words: {note.vocabulary}")
    if note.mistakes:
        parts.append(f"mistakes: {note.mistakes}")
    if note.recommendation:
        parts.append(f"recommended next step: {note.recommendation}")
    return "; ".join(parts)


def _load_state(session: TutorSession) -> dict:
    """Состояние сессии; битый JSON → пустое состояние (сессия не падает)."""
    try:
        state = json.loads(session.state_json or "{}")
    except (TypeError, ValueError):
        logger.warning("Битый state_json у tutor-сессии %s", session.id)
        return new_state(
            character=session.character,
            mode=session.mode,
            max_turns=MAX_TURNS_DEFAULT,
        )
    return state if isinstance(state, dict) else new_state()


def _state_json(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False)


def _turn_out(turn: TutorTurn) -> TutorTurnOut:
    correction = None
    if turn.correction is not None:
        correction = TutorCorrectionOut(
            corrected_text=turn.correction.corrected_text,
            issues=[
                TutorIssueOut(problem=issue.problem, suggestion=issue.suggestion)
                for issue in turn.correction.issues
            ],
        )
    return TutorTurnOut(
        reply=turn.reply,
        kind=turn.kind,
        question=turn.question,
        correction=correction,
        interests=list(turn.interests),
        level_signal=turn.level_signal,
        new_words=list(turn.new_words),
        should_finish=turn.should_finish,
    )


def _summary_out(summary: TutorSummary) -> TutorSummaryOut:
    return TutorSummaryOut(**summary.to_dict())


def _owned(session: TutorSession, user_id: int | None, guest_token: str | None) -> bool:
    """Сессия принадлежит этому пользователю/гостю."""
    if user_id is not None:
        return session.user_id == user_id
    return bool(guest_token) and session.guest_token == guest_token


async def _user_or_none(repo: Repository, user_id: int | None):
    """Пользователь по id; неизвестный id (битый токен) → 401."""
    if user_id is None:
        return None
    user = await current_user(repo, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def _guest_token(request: Request, settings: Settings) -> str | None:
    return decode_tutor_token(settings, request.cookies.get(settings.tutor_cookie_name))


def _guest_limiter(request: Request):
    return getattr(request.app.state, "tutor_guest_limiter", None)


async def _check_user_limits(request: Request, settings: Settings, repo: Repository, user) -> None:
    """Квота + троттлинг залогиненного (как в /api/chat)."""
    try:
        await check_quota(repo, settings, user.id)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=QUOTA_ERROR) from exc
    throttle = getattr(request.app.state, "action_throttle", None)
    if throttle is not None and not throttle.allow(f"tutor:{user.id}"):
        raise HTTPException(status_code=429, detail=THROTTLE_ERROR)


def _check_guest_limit(request: Request) -> None:
    """Не больше N ходов в сутки на IP для гостей."""
    limiter = _guest_limiter(request)
    if limiter is not None and not limiter.allow(client_key(request)):
        raise HTTPException(status_code=429, detail=GUEST_LIMIT_ERROR)


async def _generate_turn(
    request: Request,
    service: TutorService,
    state: dict,
    user_text: str,
) -> TutorTurn:
    """Один LLM-вызов в очереди; ошибки/таймауты → 502 (сессия цела)."""
    llm = get_llm(request)
    if llm is None:
        raise HTTPException(status_code=503, detail=LLM_MISSING_ERROR)

    guard = getattr(request.app.state, "llm_guard", None)
    try:
        with_guard = guard.slot() if guard is not None else nullcontext()
        async with with_guard:
            turn = await service.next_turn(llm, state, user_text)
    except QueueFull:
        logger.warning("Очередь LLM переполнена (tutor)")
        raise HTTPException(status_code=429, detail=QUEUE_FULL_ERROR)
    except HTTPException:
        raise
    except Exception:
        logger.warning("Урок 0: LLM не ответил", exc_info=True)
        raise HTTPException(status_code=502, detail=LLM_ERROR)
    if turn is None:
        logger.warning("Урок 0: LLM вернул невалидный JSON")
        raise HTTPException(status_code=502, detail=LLM_ERROR)
    return turn


async def _consume_user(repo: Repository, settings: Settings, user) -> None:
    if user is None:
        return
    try:
        await consume_quota(repo, settings, user.id)
    except QuotaExceeded:
        logger.warning("Урок 0: гонка квоты при списании user=%s", user.id)


def _start_response(session: TutorSession, turn: TutorTurn, state: dict) -> TutorSessionResponse:
    return TutorSessionResponse(
        session_id=session.id,
        turn=_turn_out(turn),
        turn_index=int(state.get("turn_index") or 0),
        max_turns=int(state.get("max_turns") or MAX_TURNS_DEFAULT),
    )


# ---------- POST /api/tutor/session ----------


@router.post("/session", response_model=TutorSessionResponse)
async def start_session(
    request: Request,
    response: Response,
    body: TutorSessionRequest,
    user_id: int | None = Depends(get_optional_user_id),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> TutorSessionResponse:
    """Создаёт сессию наставника и делает первый ход.

    ``mode="intro"`` — знакомство («Урок 0»), ``mode="lesson"`` — обычный
    персональный урок с темой, повтором прошлой ошибки и SRS в конце.
    Если у пользователя/гостя уже есть активная сессия — возвращает её
    текущий ход (защита от спама повторными нажатиями).
    """
    user = await _user_or_none(repo, user_id)
    # Токен гостя: существующий из cookie либо новый — но cookie ставим только
    # после успешного создания сессии (иначе битый первый ход оставил бы
    # «пустого гостя» с cookie).
    guest_token = None if user is not None else _guest_token(request, settings)

    if user is not None:
        existing = await repo.get_active_tutor_session(user_id=user.id)
    elif guest_token is not None:
        existing = await repo.get_active_tutor_session(guest_token=guest_token)
    else:
        existing = None

    if existing is not None:
        state = _load_state(existing)
        turn = last_turn(state)
        if turn is not None:
            return _start_response(existing, turn, state)

    if user is not None:
        await _check_user_limits(request, settings, repo, user)
    else:
        _check_guest_limit(request)

    mode = body.mode
    lesson = mode == "lesson"
    max_turns = settings.tutor_lesson_max_turns if lesson else settings.tutor_max_turns

    profile_snippet = ""
    self_level = ""
    character = "default"
    topic = (body.topic or "").strip() if lesson else ""
    weak_areas: list[str] = []
    interests: list[str] = []
    if user is not None:
        profile = await repo.get_profile(user.id)
        if profile is not None:
            profile_snippet = to_profile_snippet(profile)
            self_level = profile.self_level
            character = profile.character or "default"
        if not self_level:
            self_level = user.level or ""
        if lesson:
            notes = await repo.get_lesson_notes(user.id, limit=1)
            last_note = notes[0] if notes else None
            weak_areas, interests = await _lesson_context(
                repo, user.id, profile, last_note
            )
            if last_note is not None:
                snippet = _last_note_snippet(last_note)
                if snippet:
                    profile_snippet = f"{profile_snippet} {snippet}".strip()
                    if not profile_snippet.endswith("."):
                        profile_snippet += "."
            topic = await _pick_lesson_topic(
                repo, user.id, interests, weak_areas, body.topic
            )
    elif lesson:
        # У гостя нет серверной истории, но самооценка из онбординга есть.
        guest = guest_profile_from_request(request, settings)
        if guest is not None:
            self_level = str(guest.get("level") or "")
        topic = topic or DEFAULT_LESSON_TOPIC

    state = new_state(
        character=character,
        mode=mode,
        self_level=self_level,
        profile=profile_snippet,
        max_turns=max_turns,
        topic=topic,
        weak_areas=weak_areas,
        interests=interests,
    )

    # Первый ход — статический: сессия стартует мгновенно и не зависит от
    # 429/таймаута LLM (провайдеры часто лимитируют пул модели).
    turn = first_turn(
        character=character,
        self_level=self_level,
        mode=mode,
        weak_areas=weak_areas,
        interests=interests,
        topic=topic,
    )
    state = apply_turn(state, turn, "")
    state_json = _state_json(state)

    if user is None and guest_token is None:
        guest_token = new_guest_token()

    if existing is not None:
        # Активная сессия была, но без валидного хода (например, сбой при
        # создании) — переиспользуем её, чтобы не плодить дубли.
        session = existing
        await repo.save_tutor_state(session.id, state_json, turn_index=state["turn_index"])
        session.state_json = state_json
    else:
        session = await repo.create_tutor_session(
            user_id=user.id if user is not None else None,
            guest_token=guest_token,
            character=character,
            mode=mode,
            state_json=state_json,
        )

    if user is None and guest_token is not None:
        set_tutor_cookie(response, settings, guest_token)

    await _consume_user(repo, settings, user)
    if user is not None:
        await track_event(
            repo,
            user.id,
            "tutor_session_started",
            {"session_id": session.id, "mode": body.mode, "character": character},
        )
    return _start_response(session, turn, state)


# ---------- POST /api/tutor/turn ----------


@router.post("/turn", response_model=TutorTurnResponse)
async def next_turn(
    request: Request,
    body: TutorTurnRequest,
    user_id: int | None = Depends(get_optional_user_id),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> TutorTurnResponse:
    """Ход наставника по ответу студента (1..600 символов)."""
    user = await _user_or_none(repo, user_id)
    guest_token = None if user is not None else _guest_token(request, settings)

    session = await repo.get_tutor_session(body.session_id)
    if session is None or not _owned(session, user.id if user else None, guest_token):
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND_ERROR)
    if session.status != "active":
        raise HTTPException(status_code=409, detail=SESSION_FINISHED_ERROR)

    state = _load_state(session)
    mode = str(state.get("mode") or session.mode or "intro")
    default_max = (
        settings.tutor_lesson_max_turns if mode == "lesson" else settings.tutor_max_turns
    )
    max_turns = int(state.get("max_turns") or default_max)
    if int(state.get("turn_index") or 0) >= max_turns:
        raise HTTPException(status_code=409, detail=MAX_TURNS_ERROR)

    if user is not None:
        await _check_user_limits(request, settings, repo, user)
    else:
        _check_guest_limit(request)

    service = _service(settings, mode)
    turn = await _generate_turn(request, service, state, body.text)

    state = apply_turn(state, turn, body.text)
    await repo.save_tutor_state(session.id, _state_json(state), turn_index=state["turn_index"])
    await _consume_user(repo, settings, user)
    if user is not None:
        await track_event(
            repo,
            user.id,
            "tutor_turn",
            {
                "session_id": session.id,
                "turn_index": state["turn_index"],
                "kind": turn.kind,
            },
        )
    return TutorTurnResponse(
        turn=_turn_out(turn),
        turn_index=int(state["turn_index"]),
        max_turns=max_turns,
        should_finish=bool(turn.should_finish),
    )


# ---------- POST /api/tutor/finish ----------


async def _build_summary(
    request: Request,
    settings: Settings,
    repo: Repository,
    state: dict,
    user,
) -> TutorSummary:
    """Итог через LLM; при любой проблеме — эвристика по ответам (без 502)."""
    self_level = str(state.get("self_level") or "")
    llm = get_llm(request)
    summary: TutorSummary | None = None

    if llm is not None:
        allowed = True
        if user is not None:
            try:
                await check_quota(repo, settings, user.id)
            except QuotaExceeded:
                allowed = False
                logger.info("Урок 0: итог без LLM, квота исчерпана user=%s", user.id)

        if allowed:
            guard = getattr(request.app.state, "llm_guard", None)
            try:
                with_guard = guard.slot() if guard is not None else nullcontext()
                async with with_guard:
                    summary = await _service(
                        settings, str(state.get("mode") or "intro")
                    ).summarize(llm, state)
            except QueueFull:
                logger.warning("Очередь LLM переполнена (tutor finish)")
            except Exception:
                logger.warning("Урок 0: LLM-итог не удался", exc_info=True)
            if summary is not None and user is not None:
                await _consume_user(repo, settings, user)

    if summary is None:
        summary = fallback_summary(state, self_level)
    return finalize(state, summary, self_level)


def _parse_new_words(raw: list | None) -> list[dict[str, str]]:
    """«word — перевод» из состояния → записи для SRS (битые строки пропускаем)."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw or []:
        text = str(item).strip()
        if not text:
            continue
        word, translation = text, ""
        for separator in (" — ", " – ", " - ", "—", "–", ":", " -"):
            if separator in text:
                head, _, tail = text.partition(separator)
                if head.strip():
                    word, translation = head.strip(), tail.strip()
                break
        key = word.lower()
        if not word or key in seen:
            continue
        seen.add(key)
        entries.append({"word": word, "translation": translation, "example": ""})
    return entries


async def _apply_progress(
    repo: Repository,
    user,
    session: TutorSession,
    state: dict,
    summary: TutorSummary,
) -> tuple[int, int]:
    """Интересы/уровень → профиль, заметка урока → XP. Возвращает (xp, streak)."""
    now = datetime.now(timezone.utc).isoformat()
    progress = ProgressService(repo)

    profile = await repo.get_profile(user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
    interests: list[str] = [
        item.strip() for item in (profile.interests or "").split(",") if item.strip()
    ]
    for interest in summary.interests:
        text = str(interest).strip()
        if text and text not in interests:
            interests.append(text)
    profile.interests = ", ".join(interests[:12])
    profile.updated_at = now
    await repo.save_profile(profile)

    if summary.level and summary.level != user.level:
        await repo.set_level(user.id, summary.level)

    before = (await progress.get_progress(user.id, level=user.level)).xp

    problems: list[str] = []
    for correction in state.get("corrections") or []:
        if not isinstance(correction, dict):
            continue
        for issue in correction.get("issues") or []:
            if isinstance(issue, dict):
                problem = str(issue.get("problem") or "").strip()
                if problem and problem not in problems:
                    problems.append(problem)

    lesson = str(state.get("mode") or "intro") == "lesson"
    lesson_topic = str(state.get("topic") or "").strip()
    note_topic = (
        f"{LESSON_NOTE_PREFIX}{lesson_topic or DEFAULT_LESSON_TOPIC}"
        if lesson
        else TUTOR_TOPIC
    )
    new_words = _parse_new_words(state.get("new_words"))
    vocabulary = ", ".join(entry["word"] for entry in new_words)

    lesson_row = await repo.start_lesson(
        user.id,
        note_topic,
        json.dumps({"tutor_session_id": session.id}, ensure_ascii=False),
    )
    try:
        note = LessonNote(
            user_id=user.id,
            lesson_id=lesson_row.id,
            topic=note_topic,
            vocabulary=vocabulary,
            grammar="",
            speaking=summary.praise or f"{note_topic}: уровень {summary.level}",
            mistakes=", ".join(problems[:5]),
            recommendation=summary.recommendation,
            created_at=now,
        )
        await repo.add_lesson_note(note)
    finally:
        try:
            await repo.finish_lesson(lesson_row.id)
        except Exception:
            logger.warning("Урок 0: не удалось закрыть lesson_sessions %s", lesson_row.id)

    if new_words:
        try:
            added = await SRSService(repo).add_words(
                user.id, new_words, lesson_id=lesson_row.id
            )
            if added:
                logger.info("Урок: %s новых слов добавлено в словарь user=%s", added, user.id)
        except Exception:
            logger.exception("Урок: не удалось добавить слова в SRS user=%s", user.id)

    after_progress = await progress.get_progress(user.id, level=summary.level)
    xp = max(after_progress.xp - before, 0)
    return xp, after_progress.streak_days


@router.post("/finish", response_model=TutorFinishResponse)
async def finish_session(
    request: Request,
    body: TutorFinishRequest,
    user_id: int | None = Depends(get_optional_user_id),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repository),
) -> TutorFinishResponse:
    """Итог урока: оценка уровня + мягкая обратная связь.

    Гость получает только оценку (``registered=false``), прогресс не пишется.
    Залогиненному обновляются интересы/уровень, создаётся заметка урока и XP;
    в режиме ``lesson`` новые слова из состояния попадают в SRS.
    """
    user = await _user_or_none(repo, user_id)
    guest_token = None if user is not None else _guest_token(request, settings)

    session = await repo.get_tutor_session(body.session_id)
    if session is None or not _owned(session, user.id if user else None, guest_token):
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND_ERROR)
    if session.status != "active":
        raise HTTPException(status_code=409, detail=SESSION_FINISHED_ERROR)

    state = _load_state(session)
    summary = await _build_summary(request, settings, repo, state, user)
    turns = int(state.get("turn_index") or 0)

    xp = 0
    streak_days = 0
    registered = user is not None
    if user is not None:
        try:
            xp, streak_days = await _apply_progress(repo, user, session, state, summary)
        except Exception:
            logger.exception("Урок 0: не удалось записать прогресс user=%s", user.id)
            xp, streak_days = 0, 0
    else:
        # Гость видит, сколько XP получил бы, но в прогресс ничего не пишем.
        xp = TUTOR_XP
        streak_days = 1

    state = {**state, "summary": summary.to_dict()}
    try:
        await repo.save_tutor_state(session.id, _state_json(state), turn_index=turns)
        await repo.finish_tutor_session(session.id)
    except Exception:
        logger.exception("Урок 0: не удалось закрыть tutor-сессию %s", session.id)

    if user is not None:
        await track_event(
            repo,
            user.id,
            "tutor_session_finished",
            {
                "session_id": session.id,
                "turns": turns,
                "level": summary.level,
                "xp": xp,
            },
        )

    return TutorFinishResponse(
        summary=_summary_out(summary),
        turns=turns,
        xp=xp,
        streak_days=streak_days,
        registered=registered,
    )
