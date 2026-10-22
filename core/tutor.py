"""«Урок 0» — короткий разговор-знакомство с наставником.

Цель урока: познакомиться со студентом, выяснить его интересы и хобби,
по живым ответам оценить реальный уровень CEFR и сравнить его с самооценкой
из онбординга, а затем дать мягкую обратную связь.

Модуль не знает ни про FastAPI, ни про Telegram: только LLM, промпты и
устойчивый разбор JSON. Состояние диалога — обычный ``dict``, который
роутер сохраняет в ``tutor_sessions.state_json``.
"""

from __future__ import annotations

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

SUMMARY_SYSTEM_PROMPT = """You are an experienced English teacher. A short "Lesson 0" getting-to-know-you conversation is over.

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
    should_finish: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Публичное представление для API (как в контракте)."""
        return {
            "reply": self.reply,
            "kind": self.kind,
            "question": self.question,
            "correction": self.correction.to_dict() if self.correction else None,
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
) -> dict[str, Any]:
    """Пустое состояние новой сессии урока 0."""
    return {
        "character": character or "default",
        "mode": mode or "intro",
        "self_level": _normalize_level(self_level),
        "profile": profile or "",
        "max_turns": max(1, int(max_turns)),
        "turn_index": 0,
        "turns": [],
        "asked": [],
        "interests": [],
        "corrections": [],
        "level_signals": [],
    }


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
    return {
        **state,
        "turns": turns,
        "asked": asked,
        "interests": interests,
        "corrections": corrections,
        "level_signals": signals,
        "turn_index": int(state.get("turn_index") or 0) + 1,
    }


def student_messages(state: dict[str, Any]) -> list[str]:
    """Все реплики студента из состояния (для итоговой оценки)."""
    return [
        str(item.get("text") or "").strip()
        for item in state.get("turns") or []
        if item.get("role") == "student" and str(item.get("text") or "").strip()
    ]


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
) -> str:
    """Системный промпт: персонаж + правила урока + требование строгого JSON."""
    char = get_character(character) if isinstance(character, str) else character
    if char is None:
        char = get_character("default")

    level = _normalize_level(self_level) or "unknown"
    parts = [
        TUTOR_SYSTEM_PROMPT.replace("<<NAME>>", char.name_en or char.name or "your tutor").replace(
            "<<SELF_LEVEL>>", level
        )
    ]
    if mode and mode != "intro":
        parts.append(f'Lesson mode: "{mode}". Keep the same friendly getting-to-know-you format.')
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
    lines = [f"Lesson progress: {index} of {max_turns} tutor turns are done."]

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
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "system",
            "content": build_state_block(state) + "\n\n" + FORMAT_RULE,
        },
        {"role": "user", "content": user_text.strip() or FIRST_TURN_HINT},
    ]


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


def parse_turn(raw: str) -> TutorTurn | None:
    """Терпимо разбирает JSON-ход наставника. Битый JSON → ``None``."""
    try:
        payload = extract_json(raw)
    except (JsonParseError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    reply = _text(payload.get("reply"))
    question = _text_or_none(payload.get("question"))
    if not reply and not question:
        return None

    kind = str(payload.get("kind") or "ask").strip().lower()
    return TutorTurn(
        reply=reply,
        kind=kind if kind in TURN_KINDS else "ask",
        question=question,
        correction=TutorCorrection.from_dict(payload.get("correction")),
        interests=_string_list(payload.get("interests")),
        level_signal=_normalize_level(payload.get("level_signal")),
        should_finish=bool(payload.get("should_finish")),
    )


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

    def _normalize(self, turn: TutorTurn, state: dict[str, Any]) -> TutorTurn:
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
