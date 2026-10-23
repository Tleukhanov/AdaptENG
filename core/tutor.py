"""Наставник: «Урок 0» (знакомство) и обычный персональный урок.

«Урок 0» — короткий разговор-знакомство: познакомиться со студентом, выяснить
интересы и хобби, по живым ответам оценить реальный уровень CEFR.

``mode="lesson"`` — урок 1+: короткий повтор прошлой ошибки, новая тема,
практика и итог. Первый ход в обоих режимах статический (без LLM).

Модуль не знает ни про FastAPI, ни про Telegram: только LLM, промпты и
устойчивый разбор JSON. Состояние диалога — обычный ``dict``, который
роутер сохраняет в ``tutor_sessions.state_json``.

Для стриминга (SSE) модель отвечает «текст реплики → ``<<<META>>>`` → JSON»:
``stream_turn`` отдаёт текст по мере генерации, а meta-блок разбирает после
маркера; старый формат (чистый JSON) поддерживается как один кусок.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from providers.base import LLMProvider

from .characters import Character, get_character
from .diagnostic import estimate_level_heuristic
from .json_utils import JsonParseError, extract_json

#: Допустимые уровни CEFR для оценки урока 0.
TUTOR_LEVELS = ("A1", "A2", "B1", "B2", "C1")

#: Допустимые виды хода наставника.
TURN_KINDS = ("ask", "teach", "correct", "praise", "finish")

#: Режимы наставника: знакомство («Урок 0») и обычный персональный урок.
TUTOR_MODES = ("intro", "lesson")

#: Фазы урока: повтор ошибки → новая тема → практика → итог.
LESSON_PHASES = ("review", "teach", "practice", "wrap")

#: Тема урока по умолчанию, если профиль и план ничего не подсказали.
DEFAULT_LESSON_TOPIC = "Everyday English: small talk"

#: Сколько новых слов наставник может ввести за один ход.
MAX_NEW_WORDS_PER_TURN = 2

#: Сколько последних ответов студента показывать модели в блоке состояния.
MAX_STATE_ANSWERS = 7


TUTOR_SYSTEM_PROMPT = """You are <<NAME>>, an English tutor running "Lesson 0" — a short, warm getting-to-know-you conversation with a Russian-speaking student.

Goals of this lesson:
1. Introduce yourself and make the student comfortable.
2. Learn about the student's life, interests and hobbies.
3. From what the student actually writes, estimate their real CEFR level (A1, A2, B1, B2 or C1) and compare it with their self-assessment (<<SELF_LEVEL>>).
4. Give gentle, encouraging feedback.

Lesson rules:
- The lesson has 5 to 7 tutor turns. On every turn write a short natural reaction and ask EXACTLY ONE question.
- Adapt the language to the student's level: for A1/A2 use short simple English sentences and add brief explanations in Russian in brackets; for B1+ use mostly English, richer vocabulary, synonyms and follow-up nuances.
- Correct gently: at most ONE mistake per turn. Praise the attempt before correcting. Never shame the student.
- Notice interests and hobbies the student mentions and return them in the "interests" field.
- Start with a greeting and a question about who the student is and what they love doing.
- On the very last turn set "should_finish" to true and give a warm wrap-up with a light compliment.
- Never ask more than one question per turn and never repeat a question that was already asked.

Respond ONLY with a single valid JSON object. No markdown, no extra text, no code fences.

JSON schema:
{
  "reply": "what the tutor says out loud (for text-to-speech), in English",
  "kind": "ask | teach | correct | praise | finish",
  "question": "the single question for the student, or null",
  "correction": {"corrected_text": "the student's sentence corrected", "issues": [{"problem": "short explanation in Russian", "suggestion": "how to say it better, in English"}]} | null,
  "interests": ["interests or hobbies the student mentioned"],
  "level_signal": "A1 | A2 | B1 | B2 | C1 | none",
  "should_finish": false
}

Rules for the JSON:
- "correction" is null when the student made no noticeable mistake.
- "issues" contains at most one item.
- "level_signal" is your current estimate of the student's level from their messages, or an empty string when there is not enough evidence yet.
- "interests" may be an empty array.
"""

LESSON_SYSTEM_PROMPT = """You are <<NAME>>, a friendly English tutor running a full personalised lesson for a Russian-speaking student.

Lesson scenario — follow this order:
1. REVIEW: if the student has weak areas from previous lessons, start with a short review (about 5 minutes) of the most important mistake. Ask the student to make their own example, using their interests for context.
2. TEACH: introduce the new topic <<TOPIC>> with 1-2 useful new words or phrases and one interesting fact that broadens the student's horizons.
3. PRACTICE: ask 2-3 questions about the topic, react naturally and correct mistakes gently.
4. WRAP: on the last turn summarise what was learned, praise the student, say what to review next and set "should_finish" to true.

Lesson rules:
- The lesson has 6 to 9 tutor turns. On every turn write a short natural reaction and ask EXACTLY ONE question; the final wrap-up needs no question.
- REVIEW comes first and must be brief: one quick example, one question, then move on to the new topic.
- Adapt the language to the student's level: for A1/A2 use short simple English sentences and add brief explanations in Russian in brackets; for B1+ use mostly English with richer vocabulary, synonyms and nuances.
- Introduce at most 2 new words or phrases per turn and put them in "new_words" as strings like "word — краткий перевод". Do not repeat words that were already introduced.
- Use the student's interests for examples and questions: <<INTERESTS>>.
- Correct gently: at most ONE mistake per turn. Praise the attempt before correcting. Never shame the student.
- Never ask more than one question per turn and never repeat a question that was already asked.

Respond ONLY with a single valid JSON object. No markdown, no extra text, no code fences.

JSON schema:
{
  "reply": "what the tutor says out loud (for text-to-speech), in English",
  "kind": "ask | teach | correct | praise | finish",
  "question": "the single question for the student, or null",
  "correction": {"corrected_text": "the student's sentence corrected", "issues": [{"problem": "short explanation in Russian", "suggestion": "how to say it better, in English"}]} | null,
  "interests": ["interests or hobbies the student mentioned"],
  "level_signal": "A1 | A2 | B1 | B2 | C1 | none",
  "new_words": ["word — краткий перевод"],
  "should_finish": false
}

Rules for the JSON:
- "correction" is null when the student made no noticeable mistake.
- "issues" contains at most one item.
- "level_signal" is your current estimate of the student's level from their messages, or an empty string when there is not enough evidence yet.
- "new_words" contains at most 2 items and may be an empty array.
- "interests" may be an empty array.
"""

SUMMARY_SYSTEM_PROMPT = """You are an experienced English teacher. A short English lesson is over.

Assess the student's CEFR level (A1, A2, B1, B2 or C1) from the student's OWN messages only: grammar control and range, vocabulary breadth, sentence complexity, fluency and how well they express personal ideas.

Be conservative: when in doubt, prefer the lower level. An honest A2 is better than an inflated B1.

Respond ONLY with a single valid JSON object. No markdown, no extra text, no code fences.

JSON schema:
{
  "level": "B1",
  "confidence": 0.6,
  "interests": ["chess"],
  "strengths": ["short strength in Russian"],
  "weaknesses": ["short weakness in Russian"],
  "recommendation": "one short actionable sentence in Russian",
  "praise": "one warm encouraging sentence in Russian"
}

Rules:
- "level" is one of: A1, A2, B1, B2, C1.
- "confidence" is a number from 0 to 1.
- "interests" — topics and hobbies the student mentioned, in their original language; may be empty.
- "strengths" and "weaknesses" — 1 to 3 short phrases each; may be empty.
- "recommendation" and "praise" must be in Russian.
"""

FORMAT_RULE = (
    "CRITICAL FORMAT RULE — this overrides all other instructions: "
    "your response MUST be ONLY a single valid JSON object matching the schema. "
    "No markdown, no code fences, no text outside JSON. "
    "If you break this rule the student sees an error."
)

#: Маркер, отделяющий текст реплики от служебного JSON в стриминговом ответе.
META_MARKER = "<<<META>>>"

#: Правило формата для стриминга: сначала текст реплики, затем meta-блок.
STREAM_FORMAT_RULE = (
    "CRITICAL OUTPUT FORMAT — this overrides all other instructions: "
    "first write ONLY what the tutor says to the student, as plain text "
    "(the same text that would go into the \"reply\" field), "
    f"then a new line with exactly {META_MARKER}, "
    "then ONE compact JSON object with the fields \"kind\", \"question\", "
    "\"correction\", \"interests\", \"level_signal\", \"new_words\", \"should_finish\". "
    "No markdown, no code fences, no text after the JSON. Example:\n"
    "Great job! What did you do at the weekend?\n"
    f"{META_MARKER}\n"
    '{"kind": "ask", "question": "What did you do at the weekend?", "correction": null, '
    '"interests": [], "level_signal": "B1", "new_words": [], "should_finish": false}'
)

#: Температура хода наставника (та же, что в обычном ``/turn``).
TURN_TEMPERATURE = 0.7

#: Строка «только JSON» из базовых промптов — в стриме её заменяем на meta-формат.
JSON_ONLY_RULE = (
    "Respond ONLY with a single valid JSON object. No markdown, no extra text, no code fences."
)
STREAM_JSON_REPLACEMENT = "Follow the OUTPUT FORMAT rule at the end of this message."

FIRST_TURN_HINT = (
    "Start the lesson now: introduce yourself briefly and ask your first question "
    "about who the student is and what they enjoy doing."
)


# ---------- модели данных ----------


@dataclass
class TutorIssue:
    """Одна замеченная ошибка."""

    problem: str = ""  # объяснение по-русски
    suggestion: str = ""  # как сказать правильно

    def to_dict(self) -> dict[str, str]:
        return {"problem": self.problem, "suggestion": self.suggestion}

    @classmethod
    def from_dict(cls, payload: Any) -> "TutorIssue":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            problem=str(payload.get("problem", "")).strip(),
            suggestion=str(payload.get("suggestion", "")).strip(),
        )


@dataclass
class TutorCorrection:
    """Мягкая правка ответа студента: не больше одной ошибки за ход."""

    corrected_text: str = ""
    issues: list[TutorIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corrected_text": self.corrected_text,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "TutorCorrection | None":
        if not isinstance(payload, dict):
            return None
        issues = [
            TutorIssue.from_dict(item)
            for item in payload.get("issues") or []
            if isinstance(item, dict)
        ]
        corrected = str(payload.get("corrected_text", "")).strip()
        if not corrected and not issues:
            return None
        return cls(corrected_text=corrected, issues=issues)


@dataclass
class TutorTurn:
    """Один ход наставника."""

    reply: str = ""
    kind: str = "ask"
    question: str | None = None
    correction: TutorCorrection | None = None
    interests: list[str] = field(default_factory=list)
    level_signal: str = ""
    new_words: list[str] = field(default_factory=list)
    should_finish: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Публичное представление для API (как в контракте)."""
        return {
            "reply": self.reply,
            "kind": self.kind,
            "question": self.question,
            "correction": self.correction.to_dict() if self.correction else None,
            "new_words": list(self.new_words),
            "should_finish": self.should_finish,
        }

    def to_state(self) -> dict[str, Any]:
        """Как ход хранится в ``state_json`` (плюс сигналы для промпта)."""
        payload = self.to_dict()
        payload.update(
            {
                "role": "tutor",
                "interests": list(self.interests),
                "level_signal": self.level_signal,
            }
        )
        return payload

    @classmethod
    def from_state(cls, payload: dict[str, Any]) -> "TutorTurn":
        kind = str(payload.get("kind") or "ask").strip().lower()
        return cls(
            reply=str(payload.get("reply") or "").strip(),
            kind=kind if kind in TURN_KINDS else "ask",
            question=_text_or_none(payload.get("question")),
            correction=TutorCorrection.from_dict(payload.get("correction")),
            interests=_string_list(payload.get("interests")),
            level_signal=_normalize_level(payload.get("level_signal")),
            new_words=_string_list(
                payload.get("new_words"), limit=MAX_NEW_WORDS_PER_TURN
            ),
            should_finish=bool(payload.get("should_finish")),
        )


@dataclass
class TutorSummary:
    """Итог урока 0: оценка уровня и мягкая обратная связь."""

    level: str = "B1"
    confidence: float = 0.0
    matches_self_level: bool = False
    interests: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendation: str = ""
    praise: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "confidence": self.confidence,
            "matches_self_level": self.matches_self_level,
            "interests": list(self.interests),
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "recommendation": self.recommendation,
            "praise": self.praise,
        }


# ---------- утилиты ----------


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _text_or_none(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _string_list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _normalize_level(value: Any) -> str:
    level = str(value or "").strip().upper()
    return level if level in TUTOR_LEVELS else ""


def _merge_unique(existing: list[str], additions: list[str], limit: int = 12) -> list[str]:
    merged = [item for item in existing if item]
    for item in additions:
        text = str(item).strip()
        if text and text not in merged:
            merged.append(text)
        if len(merged) >= limit:
            break
    return merged


# ---------- состояние урока ----------


def new_state(
    *,
    character: str = "default",
    mode: str = "intro",
    self_level: str = "",
    profile: str = "",
    max_turns: int = 7,
    topic: str = "",
    weak_areas: list[str] | None = None,
    interests: list[str] | None = None,
    plan: list[str] | None = None,
) -> dict[str, Any]:
    """Пустое состояние новой сессии урока.

    Для режима ``lesson`` дополнительно хранит тему, фазу, план и список
    прошлых ошибок: по ним строится статический первый ход, системный промпт
    и итоговая заметка.
    """
    normalized_mode = (mode or "intro").strip().lower()
    lesson = normalized_mode == "lesson"
    areas = _merge_unique([], weak_areas or [], limit=6)
    lesson_plan = [str(item).strip() for item in (plan or []) if str(item).strip()]
    if lesson and not lesson_plan:
        lesson_plan = build_lesson_plan(topic or DEFAULT_LESSON_TOPIC, areas)
    return {
        "character": character or "default",
        "mode": normalized_mode,
        "self_level": _normalize_level(self_level),
        "profile": profile or "",
        "max_turns": max(1, int(max_turns)),
        "turn_index": 0,
        "turns": [],
        "asked": [],
        "interests": _merge_unique([], interests or []),
        "corrections": [],
        "level_signals": [],
        "topic": (topic or "").strip() if lesson else "",
        "phase": "review" if lesson and areas else ("teach" if lesson else ""),
        "plan": lesson_plan if lesson else [],
        "weak_areas": areas if lesson else [],
        "new_words": [],
    }


def build_lesson_plan(topic: str, weak_areas: list[str] | None = None) -> list[str]:
    """План урока из 2–4 пунктов: повтор → тема → практика → итог."""
    areas = [str(item).strip() for item in (weak_areas or []) if str(item).strip()]
    items: list[str] = []
    if areas:
        items.append(f"Review the previous mistake: {areas[0]}")
    items.append(f"New topic: {topic}")
    items.append(f"Practice: 2-3 questions about {topic}")
    items.append("Wrap-up: key words, feedback and what to review next")
    return items[:4]


def next_phase(state: dict[str, Any]) -> str:
    """Фаза следующего хода наставника (для режима ``lesson``)."""
    if str(state.get("mode") or "intro") != "lesson":
        return ""
    upcoming = int(state.get("turn_index") or 0) + 1
    max_turns = int(state.get("max_turns") or 9)
    if upcoming >= max_turns:
        return "wrap"
    if upcoming <= 2:
        return "teach"
    return "practice"


def apply_turn(state: dict[str, Any], turn: TutorTurn, user_text: str) -> dict[str, Any]:
    """Возвращает новое состояние: ответ студента + ход наставника и сигналы."""
    turns = list(state.get("turns") or [])
    if user_text.strip():
        turns.append({"role": "student", "text": user_text.strip()})

    asked = _merge_unique(list(state.get("asked") or []), [turn.question or ""])
    interests = _merge_unique(list(state.get("interests") or []), turn.interests)
    corrections = list(state.get("corrections") or [])
    if turn.correction is not None:
        corrections.append(turn.correction.to_dict())
    signals = list(state.get("level_signals") or [])
    if turn.level_signal and turn.level_signal not in signals:
        signals.append(turn.level_signal)

    turns.append(turn.to_state())
    new_words = _merge_unique(
        list(state.get("new_words") or []),
        list(turn.new_words),
        limit=24,
    )
    updated = {
        **state,
        "turns": turns,
        "asked": asked,
        "interests": interests,
        "corrections": corrections,
        "level_signals": signals,
        "new_words": new_words,
        "turn_index": int(state.get("turn_index") or 0) + 1,
    }
    if str(updated.get("mode") or "intro") == "lesson":
        updated["phase"] = next_phase(updated)
    return updated


def student_messages(state: dict[str, Any]) -> list[str]:
    """Все реплики студента из состояния (для итоговой оценки)."""
    return [
        str(item.get("text") or "").strip()
        for item in state.get("turns") or []
        if item.get("role") == "student" and str(item.get("text") or "").strip()
    ]


def first_turn(
    character: str = "default",
    self_level: str = "",
    *,
    mode: str = "intro",
    weak_areas: list[str] | None = None,
    interests: list[str] | None = None,
    topic: str = "",
) -> TutorTurn:
    """Первый ход урока — БЕЗ вызова LLM.

    Так сессия стартует мгновенно и не зависит от 429/таймаута провайдера.
    Для ``intro`` — приветствие + вопрос «расскажи о себе». Для ``lesson`` —
    короткий повтор прошлой ошибки (если она известна), объявление новой темы
    и первый вопрос. Язык — по самооценке: до B1 простая английская фраза с
    подсказкой по-русски, B1+ — по-английски.
    """
    char = get_character(character) if character else get_character("default")
    level = _normalize_level(self_level)
    simple = level in ("", "A1", "A2")
    emoji = getattr(char, "emoji", "📚") if char else "📚"

    if (mode or "intro").strip().lower() == "lesson":
        return _lesson_first_turn(
            emoji=emoji,
            level=level,
            simple=simple,
            weak_areas=weak_areas or [],
            interests=interests or [],
            topic=(topic or "").strip() or DEFAULT_LESSON_TOPIC,
        )

    if simple:
        reply = (
            f"{emoji} Hi! I'm your English mentor. Nice to meet you!\n"
            "Tell me about yourself in English: what do you do, and what do you like doing?\n"
            "Можно простыми фразами — я помогу, если что-то не получится."
        )
        question = "Tell me about yourself: what do you do and what do you like doing?"
    else:
        reply = (
            f"{emoji} Hi! I'm your English mentor — great to meet you.\n"
            "Let's start easy: tell me a bit about yourself. What do you do, "
            "and what do you enjoy doing outside work or school?"
        )
        question = "What do you do, and what do you enjoy doing outside work or school?"
    return TutorTurn(
        reply=reply,
        kind="ask",
        question=question,
        correction=None,
        interests=[],
        level_signal=level,
        should_finish=False,
    )


def _lesson_first_turn(
    *,
    emoji: str,
    level: str,
    simple: bool,
    weak_areas: list[str],
    interests: list[str],
    topic: str,
) -> TutorTurn:
    """Статический первый ход урока: повтор ошибки → тема → первый вопрос."""
    interest = interests[0] if interests else ""
    area = weak_areas[0] if weak_areas else ""

    lines = [f'{emoji} Hi! Today we have a full lesson: "{topic}".']
    if simple:
        lines.append("Сегодня обычный урок — с повторением и новой темой.")

    if area:
        lines.append(
            f"Before we start, a quick review (5 minutes): last time you made a "
            f"mistake with {area}."
        )
        lines.append(_interest_example(interest))
        question = (
            f"Your turn: make one sentence about {interest or 'your day'} "
            f"using {area}."
        )
        lines.append(f"After that we'll move on to the new topic: {topic}.")
        lines.append(question)
    else:
        lines.append(f"Today's topic is {topic} — we'll learn a few useful words.")
        question = (
            f"What do you already know about {topic}, and what would you like to learn?"
        )
        lines.append(question)

    if simple:
        lines.append("Можно простыми фразами — я помогу, если что-то не получится.")

    return TutorTurn(
        reply="\n".join(lines),
        kind="ask",
        question=question,
        correction=None,
        interests=[],
        level_signal=level,
        new_words=[],
        should_finish=False,
    )


def _interest_example(interest: str) -> str:
    """Короткий пример в Present Simple, привязанный к интересам студента."""
    topic = interest.strip()
    if topic:
        return (
            f'Example from your interests: "I usually spend an hour on {topic} '
            'every evening, and I often talk about it with my friends."'
        )
    return (
        'Example: "I usually practise English for ten minutes every evening, '
        'and I often watch films in English."'
    )


def last_turn(state: dict[str, Any]) -> TutorTurn | None:
    """Последний ход наставника (чтобы вернуть текущий ход сессии)."""
    for item in reversed(state.get("turns") or []):
        if item.get("role") == "tutor":
            return TutorTurn.from_state(item)
    return None


# ---------- промпты ----------


def build_system_prompt(
    character: Character | str | None,
    profile: str,
    mode: str,
    self_level: str,
    *,
    topic: str = "",
    weak_areas: list[str] | None = None,
    interests: list[str] | None = None,
    plan: list[str] | None = None,
) -> str:
    """Системный промпт: персонаж + правила режима + требование строгого JSON."""
    char = get_character(character) if isinstance(character, str) else character
    if char is None:
        char = get_character("default")

    level = _normalize_level(self_level) or "unknown"
    normalized_mode = (mode or "intro").strip().lower()
    name = char.name_en or char.name or "your tutor"

    if normalized_mode == "lesson":
        lesson_topic = (topic or "").strip() or DEFAULT_LESSON_TOPIC
        lesson_interests = ", ".join(
            str(item).strip() for item in (interests or []) if str(item).strip()
        ) or "not known yet — ask the student"
        parts = [
            LESSON_SYSTEM_PROMPT.replace("<<NAME>>", name)
            .replace("<<TOPIC>>", lesson_topic)
            .replace("<<INTERESTS>>", lesson_interests)
        ]
        context = [
            f"Current lesson topic: {lesson_topic}.",
            f"Student level (self-assessed): {level}.",
        ]
        areas = [str(item).strip() for item in (weak_areas or []) if str(item).strip()]
        if areas:
            context.append(
                "Previous mistakes to review briefly at the start: " + "; ".join(areas[:4]) + "."
            )
        plan_items = [str(item).strip() for item in (plan or []) if str(item).strip()]
        if plan_items:
            context.append(
                "Lesson plan: "
                + " → ".join(f"{index}) {item}" for index, item in enumerate(plan_items, 1))
            )
        parts.append("\n".join(context))
    else:
        parts = [
            TUTOR_SYSTEM_PROMPT.replace("<<NAME>>", name).replace("<<SELF_LEVEL>>", level)
        ]
        if normalized_mode and normalized_mode != "intro":
            parts.append(
                f'Lesson mode: "{normalized_mode}". Keep the same friendly getting-to-know-you format.'
            )

    if profile:
        parts.append(
            f"{profile}\n"
            "Use this only to choose better topics and examples; still verify the real level "
            "from what the student writes in this lesson."
        )
    if char.prompt_suffix:
        parts.append(
            "CHARACTER STYLE — express this personality ONLY through the \"reply\" and "
            f"\"question\" fields:\n{char.prompt_suffix}"
        )
    parts.append(FORMAT_RULE)
    return "\n\n".join(parts)


def build_state_block(state: dict[str, Any]) -> str:
    """Компактный блок «что спросили / что ответили / интересы и ошибки»."""
    max_turns = int(state.get("max_turns") or 7)
    index = int(state.get("turn_index") or 0)
    mode = str(state.get("mode") or "intro")
    lines = [f"Lesson progress: {index} of {max_turns} tutor turns are done."]

    if mode == "lesson":
        topic = str(state.get("topic") or "").strip() or DEFAULT_LESSON_TOPIC
        phase = str(state.get("phase") or "teach")
        lines.append(
            f'Full personalised lesson. Topic: "{topic}". Current phase: {phase}.'
        )
        if phase == "review":
            lines.append(
                "The first turn already asked for a quick review of a previous mistake; "
                "acknowledge the answer briefly and move on to the new topic."
            )
        elif phase == "teach":
            lines.append(
                "Introduce the new topic with 1-2 useful words and one interesting fact."
            )
        elif phase == "practice":
            lines.append("Practise: ask about the student's own experience and opinions.")
        elif phase == "wrap":
            lines.append(
                "Wrap up now: summarise, praise the student and set should_finish=true."
            )

        areas = [
            str(item).strip()
            for item in state.get("weak_areas") or []
            if str(item).strip()
        ]
        if areas:
            lines.append("Previous mistakes to review: " + "; ".join(areas[:4]))

        plan_items = [
            str(item).strip() for item in state.get("plan") or [] if str(item).strip()
        ]
        if plan_items:
            lines.append("Lesson plan: " + " → ".join(plan_items))

        new_words = [
            str(item).strip() for item in state.get("new_words") or [] if str(item).strip()
        ]
        if new_words:
            lines.append(
                "Words already introduced (do NOT introduce them again): "
                + "; ".join(new_words[-8:])
            )

    asked = [str(item).strip() for item in state.get("asked") or [] if str(item).strip()]
    if asked:
        lines.append("Questions already asked (do NOT repeat): " + " | ".join(asked[-6:]))

    interests = [str(item).strip() for item in state.get("interests") or [] if str(item).strip()]
    if interests:
        lines.append("Interests and hobbies noticed: " + ", ".join(interests))

    problems: list[str] = []
    for correction in state.get("corrections") or []:
        if not isinstance(correction, dict):
            continue
        for issue in correction.get("issues") or []:
            if isinstance(issue, dict):
                problem = str(issue.get("problem") or "").strip()
                if problem and problem not in problems:
                    problems.append(problem)
    if problems:
        lines.append(
            "Mistakes already corrected (do NOT repeat the same correction): "
            + "; ".join(problems[-4:])
        )

    signals = [str(item) for item in state.get("level_signals") or [] if str(item).strip()]
    if signals:
        lines.append("Level signals so far: " + ", ".join(signals[-4:]))

    answers = student_messages(state)
    if answers:
        shown = answers[-MAX_STATE_ANSWERS:]
        lines.append(
            "Student's answers so far:\n"
            + "\n".join(f"- {answer[:200]}" for answer in shown)
        )
    return "\n".join(lines)


def build_turn_messages(state: dict[str, Any], user_text: str) -> list[dict[str, str]]:
    """Сообщения для одного хода наставника."""
    system = build_system_prompt(
        state.get("character") or "default",
        str(state.get("profile") or ""),
        str(state.get("mode") or "intro"),
        str(state.get("self_level") or ""),
        topic=str(state.get("topic") or ""),
        weak_areas=list(state.get("weak_areas") or []),
        interests=list(state.get("interests") or []),
        plan=list(state.get("plan") or []),
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "system",
            "content": build_state_block(state) + "\n\n" + FORMAT_RULE,
        },
        {"role": "user", "content": user_text.strip() or FIRST_TURN_HINT},
    ]


def build_stream_prompt(state: dict[str, Any], user_text: str) -> list[dict[str, str]]:
    """Сообщения для стримингового хода.

    Тот же системный промпт и блок состояния, что у ``build_turn_messages``,
    но требование формата заменено на «текст реплики, затем ``<<<META>>>`` и
    JSON»: строгий JSON mode не даёт стримить реплику по мере генерации.
    """
    messages = build_turn_messages(state, user_text)
    return [
        {
            "role": "system",
            "content": _stream_system_text(messages[0]["content"]),
        },
        {
            "role": "system",
            "content": _stream_system_text(messages[1]["content"]),
        },
        messages[2],
    ]


def _stream_system_text(text: str) -> str:
    """Системный текст под стрим: JSON-only правило → формат с ``<<<META>>>``."""
    return (
        text.replace(JSON_ONLY_RULE, STREAM_JSON_REPLACEMENT)
        .replace(FORMAT_RULE, STREAM_FORMAT_RULE)
    )


def build_summary_messages(state: dict[str, Any]) -> list[dict[str, str]]:
    """Сообщения для итоговой оценки уровня урока 0."""
    answers = student_messages(state)
    dialogue = "\n".join(f"- {answer}" for answer in answers) or "(the student said nothing)"
    self_level = _normalize_level(state.get("self_level")) or "not stated"
    user_message = (
        f"Self-assessed level from onboarding: {self_level}\n\n"
        f"{build_state_block(state)}\n\n"
        f"Student's own messages:\n{dialogue}\n\n"
        "Assess the student and produce the summary JSON."
    )
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


# ---------- разбор ответов LLM ----------


def split_stream_text(buffer: str) -> tuple[str, str]:
    """Делит накопленный буфер стрима на безопасный текст и остаток.

    Возвращает ``(safe_text, rest)``: ``safe_text`` можно сразу отправлять
    клиенту, ``rest`` — хвост, который может оказаться началом маркера
    ``<<<META>>>`` (держим до следующего чанка) либо уже начавшимся
    meta-блоком — тогда он начинается с маркера.
    """
    index = buffer.find(META_MARKER)
    if index != -1:
        return buffer[:index], buffer[index:]

    keep = 0
    for size in range(min(len(buffer), len(META_MARKER) - 1), 0, -1):
        if META_MARKER.startswith(buffer[-size:]):
            keep = size
            break
    if keep:
        return buffer[:-keep], buffer[-keep:]
    return buffer, ""


def _turn_from_payload(payload: dict[str, Any]) -> TutorTurn:
    """Нормализует поля JSON-хода (общая часть parse_turn и parse_meta_block)."""
    kind = str(payload.get("kind") or "ask").strip().lower()
    return TutorTurn(
        reply=_text(payload.get("reply")),
        kind=kind if kind in TURN_KINDS else "ask",
        question=_text_or_none(payload.get("question")),
        correction=TutorCorrection.from_dict(payload.get("correction")),
        interests=_string_list(payload.get("interests")),
        level_signal=_normalize_level(payload.get("level_signal")),
        new_words=_string_list(
            payload.get("new_words"), limit=MAX_NEW_WORDS_PER_TURN
        ),
        should_finish=bool(payload.get("should_finish")),
    )


def _meta_from_turn(turn: TutorTurn) -> dict[str, Any]:
    """Служебные поля хода без текста реплики (payload события ``meta``)."""
    return {
        "kind": turn.kind,
        "question": turn.question,
        "correction": turn.correction.to_dict() if turn.correction else None,
        "interests": list(turn.interests),
        "new_words": list(turn.new_words),
        "level_signal": turn.level_signal,
        "should_finish": bool(turn.should_finish),
    }


def turn_from_meta(reply: str, meta: dict[str, Any]) -> TutorTurn:
    """Собирает ход из накопленного текста реплики и разобранного meta-блока."""
    turn = _turn_from_payload(meta if isinstance(meta, dict) else {})
    turn.reply = _text(reply)
    return turn


def parse_meta_block(raw: str) -> dict[str, Any] | None:
    """Терпимо разбирает meta-блок после ``<<<META>>>``.

    Переживает ```json-обёртки и лишний текст (как ``parse_turn``), а также
    чистый JSON без маркера. Битый JSON или не-объект → ``None``.
    """
    text = raw.strip()
    if META_MARKER in text:
        text = text.split(META_MARKER, 1)[1].strip()
    if not text:
        return None
    try:
        payload = extract_json(text)
    except (JsonParseError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _meta_from_turn(_turn_from_payload(payload))


def parse_turn(raw: str) -> TutorTurn | None:
    """Терпимо разбирает JSON-ход наставника. Битый JSON → ``None``."""
    try:
        payload = extract_json(raw)
    except (JsonParseError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    turn = _turn_from_payload(payload)
    if not turn.reply and not turn.question:
        return None
    return turn


def parse_summary(raw: str) -> TutorSummary | None:
    """Терпимо разбирает итоговый JSON. Битый JSON → ``None``."""
    try:
        payload = extract_json(raw)
    except (JsonParseError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    level = _normalize_level(payload.get("level")) or "B1"
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)

    return TutorSummary(
        level=level,
        confidence=confidence,
        interests=_string_list(payload.get("interests")),
        strengths=_string_list(payload.get("strengths")),
        weaknesses=_string_list(payload.get("weaknesses")),
        recommendation=_text(payload.get("recommendation")),
        praise=_text(payload.get("praise")),
    )


def finalize(state: dict[str, Any], summary: TutorSummary, self_level: str = "") -> TutorSummary:
    """Дополняет итог данными из состояния: интересы и сравнение с самооценкой."""
    level = _normalize_level(summary.level) or "B1"
    self_value = _normalize_level(self_level or state.get("self_level"))
    summary.level = level
    summary.matches_self_level = bool(self_value) and level == self_value
    summary.interests = _merge_unique(
        list(state.get("interests") or []),
        list(summary.interests or []),
    )
    return summary


def fallback_summary(state: dict[str, Any], self_level: str = "") -> TutorSummary:
    """Итог без LLM (модель недоступна или вернула мусор): эвристика по ответам."""
    answers = student_messages(state)
    problems: list[str] = []
    for correction in state.get("corrections") or []:
        if not isinstance(correction, dict):
            continue
        for issue in correction.get("issues") or []:
            if isinstance(issue, dict):
                problem = str(issue.get("problem") or "").strip()
                if problem and problem not in problems:
                    problems.append(problem)

    summary = TutorSummary(
        level=estimate_level_heuristic(answers),
        confidence=0.3 if answers else 0.1,
        interests=_merge_unique([], list(state.get("interests") or [])),
        strengths=[],
        weaknesses=problems[:3],
        recommendation="Продолжай короткие разговоры каждый день — так уровень растёт быстрее всего.",
        praise="Спасибо за разговор! Ты уже сделал главное — начал говорить.",
    )
    return finalize(state, summary, self_level)


# ---------- сервис ----------


async def _stream_chunks(
    llm: LLMProvider,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    """Куски ответа: ``chat_stream`` провайдера либо один чанк из ``chat()``.

    Провайдеры без стриминга (и фейки в тестах) обходятся обычным вызовом —
    тогда весь текст приходит одним куском.
    """
    stream = getattr(llm, "chat_stream", None)
    if stream is not None:
        emitted = False
        try:
            async for chunk in stream(
                messages, temperature=TURN_TEMPERATURE, json_mode=False
            ):
                if chunk:
                    emitted = True
                    yield chunk
            return
        except NotImplementedError:
            if emitted:
                raise
        # Метод объявлен, но не реализован — идём в обычный chat().

    raw = await llm.chat(messages, temperature=TURN_TEMPERATURE, json_mode=False)
    if raw:
        yield raw


async def stream_turn(
    llm: LLMProvider,
    state: dict[str, Any],
    user_text: str,
) -> AsyncIterator[tuple[str, dict[str, Any] | None]]:
    """Стрим хода наставника: куски текста, затем разобранный meta-блок.

    Модель отвечает «текст реплики → ``<<<META>>>`` → JSON». Текст уходит
    клиенту по мере генерации; meta разбирается после маркера. Обратная
    совместимость: чистый JSON (старый формат) отдаётся одним куском.

    Финальный кортеж — ``("", meta)``; ``meta is None`` означает, что ответ
    модели не разобрался (битый JSON) и ход сохранять нельзя.
    """
    messages = build_stream_prompt(state, user_text)
    buffer = ""
    mode: str | None = None  # "text" | "json"

    async for chunk in _stream_chunks(llm, messages):
        buffer += chunk
        if mode is None:
            probe = buffer.lstrip()
            if not probe:
                continue
            mode = "json" if probe.startswith("{") else "text"
        if mode == "json":
            # Чистый JSON нельзя стримить по кускам: копим и разбираем целиком.
            continue
        safe, buffer = split_stream_text(buffer)
        if safe:
            yield safe, None

    if mode == "json":
        turn = parse_turn(buffer)
        if turn is None:
            yield "", None
            return
        if turn.reply:
            yield turn.reply, None
        yield "", _meta_from_turn(turn)
        return

    if META_MARKER in buffer:
        yield "", parse_meta_block(buffer)
        return

    # Ответ без meta: отдаём придержанный хвост, но ход сохранить нечем.
    if buffer:
        yield buffer, None
    yield "", None


class TutorService:
    """Один LLM-вызов на ход урока 0 и один — на итоговую оценку.

    Сервис не держит LLM: провайдер передаётся в метод, поэтому тесты и
    роутеры могут подменять его независимо.
    """

    def __init__(self, max_turns: int = 7, min_turns: int = 4) -> None:
        self.max_turns = max(1, int(max_turns))
        self.min_turns = max(1, int(min_turns))

    async def next_turn(
        self,
        llm: LLMProvider,
        state: dict[str, Any],
        user_text: str,
    ) -> TutorTurn | None:
        """Ход наставника. ``None`` — модель вернула невалидный JSON."""
        raw = await llm.chat(build_turn_messages(state, user_text), temperature=0.7, json_mode=True)
        turn = parse_turn(raw)
        if turn is None:
            return None
        return self._normalize(turn, state)

    async def summarize(self, llm: LLMProvider, state: dict[str, Any]) -> TutorSummary | None:
        """Итоговая оценка уровня. ``None`` — модель вернула невалидный JSON."""
        raw = await llm.chat(build_summary_messages(state), temperature=0.2, json_mode=True)
        return parse_summary(raw)

    def normalize_turn(self, turn: TutorTurn, state: dict[str, Any]) -> TutorTurn:
        """Гарантирует 5–7 ходов: последний завершает урок, ранний — нет.

        ``min_turns`` — минимум ответов студента ПОСЛЕ приветствия, поэтому
        урок не может закончиться раньше ``min_turns + 1`` хода наставника.
        """
        next_index = int(state.get("turn_index") or 0) + 1
        if next_index >= self.max_turns:
            turn.should_finish = True
        if next_index < self.min_turns + 1:
            turn.should_finish = False
        if turn.should_finish:
            turn.kind = "finish"
        elif turn.kind == "finish":
            turn.kind = "ask"
        return turn

    #: Совместимость: старое приватное имя использовалось в тестах и коде.
    _normalize = normalize_turn
