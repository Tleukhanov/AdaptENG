"""Генерация цельной деки урока для Telegram Mini App."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from providers.base import LLMProvider

from .json_utils import JsonParseError
from .lessons import LEVEL_DESCRIPTIONS, LEVEL_RULES

DeckParseError = JsonParseError
logger = logging.getLogger(__name__)

DECK_PRESETS = ("presentation", "cards", "quiz", "dialogue", "mixed")
MAX_SLIDES = 4
MAX_VOCABULARY = 4
MAX_QUIZ_ITEMS = 3
MAX_DIALOGUE_LINES = 6
MAX_DIALOGUE_CHOICES = 6
MAX_DIALOGUE_TURNS = 2

DECK_SYSTEM_PROMPT = """You are an English teacher creating one complete interactive lesson deck for a Russian-speaking student at the __LEVEL_DESC__ level.

Respond ONLY with a single valid JSON object. No markdown, no extra text, no code fences.

JSON schema:
{
  "title": "short English lesson title",
  "subtitle_ru": "short Russian subtitle",
  "preset": "__PRESET__",
  "emoji": "one fitting emoji",
  "slides": [
    {"headline": "short English headline", "body": "one or two concise English sentences", "emoji": "one fitting emoji"}
  ],
  "vocabulary": [
    {"word": "English word or phrase", "translation": "Russian translation", "example": "short English sentence (4-10 words) in English only", "transcription": "IPA transcription or pronunciation"}
  ],
  "quiz": [
    {"question": "English question", "options": ["English option", "..."], "answer_index": 0, "explanation_ru": "short Russian explanation"}
  ],
  "dialogue": {
    "scene_ru": "short Russian description of the scene",
    "lines": [{"character": "Character name", "line": "English line"}],
    "choices": [{"line": "English response for the student", "next": 1}]
  }
}

Preset rules:
- presentation: include the cover fields and 2 to 4 useful English slides; set vocabulary and quiz to [] and dialogue to null.
- cards: include the cover fields and 3 to 4 vocabulary cards; set slides and quiz to [] and dialogue to null.
- quiz: include the cover fields and exactly 3 quiz questions; set slides and vocabulary to [] and dialogue to null.
- dialogue: include the cover fields and one dialogue scene; set slides, vocabulary and quiz to [].
- mixed: include 2 to 4 slides, 3 to 4 vocabulary cards, exactly 3 quiz questions, and one dialogue scene.

Content rules:
- title, slide headlines and bodies, vocabulary words and examples, quiz questions and options, dialogue lines and choices are in ENGLISH.
- subtitle_ru, vocabulary translations, quiz explanation_ru and dialogue scene_ru are in RUSSIAN.
- ABSOLUTELY CRITICAL: every vocabulary "example" is an ENGLISH sentence. It is the sentence the student reads to learn the word. A Russian or Cyrillic "example" is a critical error. The Russian text belongs only in "translation".
- The answer_index is a zero-based integer that points to the correct item in options; every question must have at least 2 valid options.
- A dialogue has 3 to 6 lines, 2 to 3 choices for each of at most 2 student turns, and the choices must fit the student's level.
- Keep the content short, useful and suitable for the requested CEFR level. Do not repeat the same idea in several sections.
- Personalize examples and emphasis around the student's interests when they are provided. Character style affects tone and wording, never the JSON format.

__LEVEL_RULES__
__PRESET_RULES__
"""

DECK_FORMAT_RULE = (
    "CRITICAL FORMAT RULE — this overrides all other instructions: "
    "Your response MUST be ONLY a single valid JSON object matching the schema above. "
    "No markdown, no text outside JSON, no code fences, no bullet points and no emoji headers. "
    "If you break this rule the student will see an error."
)

PRESET_RULES = {
    "presentation": "Use the presentation preset exactly: only the cover and 2-4 slides are populated.",
    "cards": "Use the cards preset exactly: only the cover and 3-4 vocabulary cards are populated.",
    "quiz": "Use the quiz preset exactly: only the cover and 3 quiz questions are populated.",
    "dialogue": "Use the dialogue preset exactly: only the cover and one dialogue scene are populated.",
    "mixed": "Use the mixed preset exactly: populate slides, vocabulary, quiz and dialogue.",
}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def _looks_russian(text: str) -> bool:
    """True, если текст содержит кириллицу (пример на русском вместо английского)."""
    return bool(_CYRILLIC_RE.search(text))


def _cyrillic_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if _CYRILLIC_RE.match(ch)) / len(letters)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return int(candidate)
        except (TypeError, ValueError):
            return None
    return None


def _context_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        values = [_text(item) for item in value]
        return ", ".join(item for item in values if item)
    return _text(value)


def _object_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    try:
        return getattr(value, key)
    except (AttributeError, TypeError):
        return None


def _profile_text(profile: Any) -> str:
    if profile is None:
        return ""
    if isinstance(profile, str):
        return profile.strip()
    parts: list[str] = []
    name = ""
    for key in ("first_name", "name", "full_name", "username"):
        name = _context_value(_object_value(profile, key))
        if name:
            parts.append(f"Name: {name}")
            break
    fields = (
        ("goal", "Goal"),
        ("interests", "Interests"),
        ("weak_areas", "Weak areas"),
        ("preferred_format", "Preferred format"),
        ("notes", "Note"),
    )
    for key, label in fields:
        value = _context_value(_object_value(profile, key))
        if value:
            parts.append(f"{label}: {value}")
    if not parts:
        try:
            fallback = str(profile).strip()
        except Exception:
            fallback = ""
        if fallback and not fallback.startswith("<"):
            return fallback
        return ""
    return "Student profile: " + "; ".join(parts) + "."


def _character_text(character_prompt: Any) -> str:
    if isinstance(character_prompt, str):
        return character_prompt.strip()
    value = _object_value(character_prompt, "prompt_suffix")
    return _text(value)


def _plan_topic(plan_hint: Any) -> str:
    if plan_hint is None:
        return ""
    if isinstance(plan_hint, dict):
        topic = _text(plan_hint.get("topic"))
        return topic or ""
    if not isinstance(plan_hint, str):
        topic = _text(_object_value(plan_hint, "topic"))
        if topic:
            return topic
        return ""
    text = plan_hint.strip()
    if not text:
        return ""
    patterns = (
        re.compile(
            r"^\s*plan\s+lesson\s+\d+\s*/\s*\d+\s*:\s*(.*?)"
            r"(?=\s*(?:\.\s*)?focus\s*:|$)",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"^\s*(?:lesson\s+)?plan\s*(?:\d+\s*/\s*\d+)?\s*:\s*(.*?)"
            r"(?=\s*(?:\.\s*)?focus\s*:|$)",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"^\s*(?:next\s+)?topic\s*:\s*(.*?)"
            r"(?=\s*(?:\.\s*)?focus\s*:|$)",
            re.IGNORECASE | re.DOTALL,
        ),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip(" \t\r\n.-")
            if candidate:
                return candidate
    return text


def _normalized_level(level: Any) -> str | None:
    value = _text(level).upper()
    return value if value in LEVEL_DESCRIPTIONS else None


def _normalized_preset(value: Any, default: str = "mixed") -> str:
    candidate = _text(value).lower()
    return candidate if candidate in DECK_PRESETS else default


def _normalized_recent_topics(recent_topics: Any) -> list[str]:
    if not isinstance(recent_topics, (list, tuple)):
        return []
    return [text for text in (_text(item) for item in recent_topics) if text]


def build_deck_prompt(
    topic: str | None = None,
    level: str | None = None,
    profile: Any = None,
    recent_topics: list[str] | None = None,
    character_prompt: str | None = None,
    plan_hint: str | None = None,
    preset: str = "mixed",
) -> list[dict[str, str]]:
    """Собирает system/user-сообщения для одной генерации деки."""
    normalized_preset = _normalized_preset(preset)
    plan_topic = _plan_topic(plan_hint)
    effective_topic = plan_topic or _text(topic)
    level_key = _normalized_level(level)
    level_description = LEVEL_DESCRIPTIONS.get(level_key, LEVEL_DESCRIPTIONS[None])
    level_rules = LEVEL_RULES.get(level_key, "")
    system = DECK_SYSTEM_PROMPT.replace("__LEVEL_DESC__", level_description)
    system = system.replace("__PRESET__", normalized_preset)
    system = system.replace("__LEVEL_RULES__", level_rules)
    system = system.replace("__PRESET_RULES__", PRESET_RULES[normalized_preset])

    profile_text = _profile_text(profile)
    if profile_text:
        system += (
            f"\n\n{profile_text}\n"
            "Use the student's interests to make the topic and examples engaging, and use weak areas to choose useful language."
        )
    recent = _normalized_recent_topics(recent_topics)
    if recent:
        recent_text = ", ".join(f'"{item}"' for item in recent)
        system += (
            f"\n\nRECENT LESSON TOPICS (do not repeat them): {recent_text}. "
            "Choose a fresh angle."
        )
    character_text = _character_text(character_prompt)
    if character_text:
        system += (
            "\n\n[CHARACTER STYLE — act as this character while keeping JSON format: "
            f"{character_text}]"
        )
    if plan_hint:
        plan_text = _text(plan_hint) or str(plan_hint)
        system += (
            f"\n\nLESSON PLAN CONTEXT: {plan_text}. "
            "Follow the plan's topic and focus. The planned topic takes precedence over any other topic suggestion."
        )
    if plan_topic:
        system += f"\n\nPLANNED TOPIC (MANDATORY): use exactly this title/topic: {plan_topic}."
    system += f"\n\nSet \"preset\" to exactly \"{normalized_preset}\"."
    system += f"\n\n{_PRESET_FINAL_RULES[normalized_preset]}"

    if effective_topic:
        user_message = f"Create one complete {normalized_preset} deck about: {effective_topic}."
    else:
        user_message = f"Create one complete {normalized_preset} deck on an interesting everyday topic of your choice."
    if plan_hint:
        plan_text = _text(plan_hint) or str(plan_hint)
        user_message += f" Plan context: {plan_text}."

    return [
        {"role": "system", "content": system},
        {"role": "system", "content": DECK_FORMAT_RULE},
        {"role": "user", "content": user_message},
    ]


_PRESET_FINAL_RULES = {
    "presentation": "Do not add vocabulary cards, quiz questions or dialogue content in this presentation deck.",
    "cards": "Do not add slides, quiz questions or dialogue content in this vocabulary deck.",
    "quiz": "Do not add slides, vocabulary cards or dialogue content in this quiz deck.",
    "dialogue": "Do not add slides, vocabulary cards or quiz content in this dialogue deck.",
    "mixed": "All four content sections are required and must follow their count and language rules.",
}


@dataclass
class Slide:
    headline: str = ""
    body: str = ""
    emoji: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "Slide":
        if not isinstance(data, dict):
            return cls()
        return cls(
            headline=_text(data.get("headline")),
            body=_text(data.get("body")),
            emoji=_text(data.get("emoji")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "headline": self.headline,
            "body": self.body,
            "emoji": self.emoji,
        }


@dataclass
class VocabCard:
    word: str = ""
    translation: str = ""
    example: str = ""
    transcription: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "VocabCard":
        if not isinstance(data, dict):
            return cls()
        example = _text(data.get("example"))
        # LLM иногда кладёт русский перевод в example: показывать его нельзя —
        # слово остаётся, а пустой пример фронт просто скрывает.
        if _cyrillic_ratio(example) > 0.1:
            logger.warning("deck vocab: example на русском (%r) — очищен", example[:40])
            example = ""
        return cls(
            word=_text(data.get("word")),
            translation=_text(data.get("translation")),
            example=example,
            transcription=_text(data.get("transcription")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "word": self.word,
            "translation": self.translation,
            "example": self.example,
            "transcription": self.transcription,
        }


@dataclass
class QuizItem:
    question: str = ""
    options: list[str] = field(default_factory=list)
    answer_index: int = -1
    explanation_ru: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "QuizItem | None":
        if not isinstance(data, dict):
            return None
        options_raw = data.get("options")
        if not isinstance(options_raw, list):
            return None
        if not all(isinstance(item, str) and item.strip() for item in options_raw):
            return None
        options = [_text(item) for item in options_raw]
        if len(options) < 2:
            return None
        answer_index = _int(data.get("answer_index"))
        if answer_index is None or not 0 <= answer_index < len(options):
            return None
        return cls(
            question=_text(data.get("question")),
            options=options,
            answer_index=answer_index,
            explanation_ru=_text(data.get("explanation_ru")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "options": list(self.options),
            "answer_index": self.answer_index,
            "explanation_ru": self.explanation_ru,
        }


def _dialogue_line(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    raw_line = item.get("line", item.get("text"))
    line = _text(raw_line)
    if not line:
        return None
    character = _text(item.get("character", item.get("speaker")))
    return {"character": character, "line": line}


def _dialogue_choice(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    raw_line = item.get("line", item.get("text"))
    line = _text(raw_line)
    if not line:
        return None
    next_index = _int(item.get("next"))
    return {"line": line, "next": next_index if next_index is not None else -1}


def _parse_dialogue_choices(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if "line" in value or "text" in value:
            return [_choice for item in [value] if (_choice := _dialogue_choice(item)) is not None]
        grouped: dict[int, list[dict[str, Any]]] = {}
        for turn, turn_items in sorted(value.items(), key=lambda pair: str(pair[0])):
            turn_number = _int(turn)
            if turn_number is None or not isinstance(turn_items, list):
                continue
            grouped.setdefault(turn_number, []).extend(
                choice
                for item in turn_items
                if (choice := _dialogue_choice(item)) is not None
            )
        return _flatten_choice_groups(grouped)

    if not isinstance(value, list):
        return []

    if any(isinstance(item, (list, tuple)) for item in value):
        grouped = {}
        for turn, turn_items in enumerate(value[:MAX_DIALOGUE_TURNS]):
            if not isinstance(turn_items, (list, tuple)):
                continue
            grouped[turn] = [
                choice
                for item in turn_items
                if (choice := _dialogue_choice(item)) is not None
            ]
        return _flatten_choice_groups(grouped)

    parsed_items: list[tuple[dict[str, Any], int | None]] = []
    for item in value:
        choice = _dialogue_choice(item)
        if choice is None:
            continue
        raw_turn = item.get("turn") if isinstance(item, dict) else None
        parsed_items.append((choice, _int(raw_turn)))

    if not any(turn is not None for _, turn in parsed_items):
        return [choice for choice, _ in parsed_items[:MAX_DIALOGUE_CHOICES]]

    grouped = {}
    for choice, turn in parsed_items:
        grouped.setdefault(turn if turn is not None else 0, []).append(choice)
    return _flatten_choice_groups(grouped)


def _flatten_choice_groups(grouped: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for turn in sorted(grouped)[:MAX_DIALOGUE_TURNS]:
        result.extend(grouped[turn][:3])
    return result


@dataclass
class DialogueScene:
    scene_ru: str = ""
    lines: list[dict[str, str]] = field(default_factory=list)
    choices: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> "DialogueScene":
        if not isinstance(data, dict):
            return cls()
        lines: list[dict[str, str]] = []
        raw_lines = data.get("lines")
        if isinstance(raw_lines, list):
            for item in raw_lines:
                line = _dialogue_line(item)
                if line is not None:
                    lines.append(line)
                if len(lines) >= MAX_DIALOGUE_LINES:
                    break
        return cls(
            scene_ru=_text(data.get("scene_ru")),
            lines=lines,
            choices=_parse_dialogue_choices(data.get("choices")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_ru": self.scene_ru,
            "lines": [dict(item) for item in self.lines],
            "choices": [dict(item) for item in self.choices],
        }


def _parse_slides(value: Any) -> list[Slide]:
    if not isinstance(value, list):
        return []
    slides: list[Slide] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if not any(key in item for key in ("headline", "body", "emoji")):
            continue
        slides.append(Slide.from_dict(item))
        if len(slides) >= MAX_SLIDES:
            break
    return slides


def _parse_vocabulary(value: Any) -> list[VocabCard]:
    if not isinstance(value, list):
        return []
    vocabulary: list[VocabCard] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if not any(key in item for key in ("word", "translation", "example", "transcription")):
            continue
        vocabulary.append(VocabCard.from_dict(item))
        if len(vocabulary) >= MAX_VOCABULARY:
            break
    return vocabulary


def _parse_quiz(value: Any) -> list[QuizItem]:
    if not isinstance(value, list):
        return []
    quiz: list[QuizItem] = []
    for item in value:
        parsed = QuizItem.from_dict(item)
        if parsed is None:
            continue
        quiz.append(parsed)
        if len(quiz) >= MAX_QUIZ_ITEMS:
            break
    return quiz


def _decode_deck_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        logger.warning("deck_from_json: невалидный JSON (%s)", type(raw).__name__)
        return None
    text = raw.strip()
    if not text:
        logger.warning("deck_from_json: невалидный JSON (пустой ответ)")
        return None
    payload: Any = None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
        if fenced is None:
            logger.warning("deck_from_json: невалидный JSON (%s)", type(raw).__name__)
            return None
        try:
            payload = json.loads(fenced.group(1))
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("deck_from_json: невалидный JSON внутри code fence")
            return None
    if not isinstance(payload, dict):
        logger.warning("deck_from_json: ожидался объект, получен %s", type(payload).__name__)
        return None
    return payload


def deck_from_dict(
    data: Any,
    preset: str | None = None,
    topic: str | None = None,
    plan_hint: str | None = None,
) -> "Deck | None":
    """Собирает Deck из словаря, пропуская только некорректные элементы."""
    if not isinstance(data, dict):
        logger.warning("deck_from_dict: ожидался объект, получен %s", type(data).__name__)
        return None

    selected_preset = _normalized_preset(
        data.get("preset") if preset is None else preset,
    )
    plan_topic = _plan_topic(plan_hint)
    title = plan_topic or _text(topic) or _text(data.get("title")) or _text(data.get("topic")) or "English lesson"

    slides = _parse_slides(data.get("slides")) if selected_preset in {"presentation", "mixed"} else []
    vocabulary = _parse_vocabulary(data.get("vocabulary")) if selected_preset in {"cards", "mixed"} else []
    quiz = _parse_quiz(data.get("quiz")) if selected_preset in {"quiz", "mixed"} else []

    dialogue: DialogueScene | None = None
    if selected_preset in {"dialogue", "mixed"}:
        dialogue_raw = data.get("dialogue")
        if isinstance(dialogue_raw, dict):
            dialogue = DialogueScene.from_dict(dialogue_raw)

    return Deck(
        title=title,
        subtitle_ru=_text(data.get("subtitle_ru")),
        preset=selected_preset,
        emoji=_text(data.get("emoji")) or "📚",
        slides=slides,
        vocabulary=vocabulary,
        quiz=quiz,
        dialogue=dialogue,
    )


def deck_from_json(
    raw: str,
    preset: str | None = None,
    topic: str | None = None,
    plan_hint: str | None = None,
) -> "Deck | None":
    """Безопасно читает JSON деки; повреждённый ответ превращает в None."""
    payload = _decode_deck_payload(raw)
    if payload is None:
        return None
    return deck_from_dict(payload, preset=preset, topic=topic, plan_hint=plan_hint)


def deck_to_dict(deck: "Deck") -> dict[str, Any]:
    if not isinstance(deck, Deck):
        raise TypeError("deck_to_dict ожидает Deck")
    return {
        "title": deck.title,
        "subtitle_ru": deck.subtitle_ru,
        "preset": deck.preset,
        "emoji": deck.emoji,
        "slides": [slide.to_dict() for slide in deck.slides],
        "vocabulary": [card.to_dict() for card in deck.vocabulary],
        "quiz": [item.to_dict() for item in deck.quiz],
        "dialogue": deck.dialogue.to_dict() if deck.dialogue is not None else None,
    }


def deck_to_json(deck: "Deck") -> str:
    return json.dumps(deck_to_dict(deck), ensure_ascii=False)


@dataclass
class Deck:
    title: str = ""
    subtitle_ru: str = ""
    preset: str = "mixed"
    emoji: str = ""
    slides: list[Slide] = field(default_factory=list)
    vocabulary: list[VocabCard] = field(default_factory=list)
    quiz: list[QuizItem] = field(default_factory=list)
    dialogue: DialogueScene | None = None

    @property
    def topic(self) -> str:
        return self.title

    @classmethod
    def from_dict(
        cls,
        data: Any,
        preset: str | None = None,
        topic: str | None = None,
        plan_hint: str | None = None,
    ) -> "Deck | None":
        return deck_from_dict(data, preset=preset, topic=topic, plan_hint=plan_hint)

    @classmethod
    def from_json(
        cls,
        raw: str,
        preset: str | None = None,
        topic: str | None = None,
        plan_hint: str | None = None,
    ) -> "Deck | None":
        return deck_from_json(raw, preset=preset, topic=topic, plan_hint=plan_hint)

    def to_dict(self) -> dict[str, Any]:
        return deck_to_dict(self)

    def to_json(self) -> str:
        return deck_to_json(self)


def parse_deck_response(
    raw: str,
    preset: str | None = None,
    topic: str | None = None,
    plan_hint: str | None = None,
) -> Deck | None:
    return deck_from_json(raw, preset=preset, topic=topic, plan_hint=plan_hint)


class DeckService:
    """Генерирует одну целую деку через внедрённый LLM-клиент."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def generate(
        self,
        topic: str | None = None,
        level: str | None = None,
        profile: Any = None,
        recent_topics: list[str] | None = None,
        character_prompt: str | None = None,
        plan_hint: str | None = None,
        preset: str = "mixed",
    ) -> Deck | None:
        normalized_preset = _normalized_preset(preset)
        messages = build_deck_prompt(
            topic,
            level=level,
            profile=profile,
            recent_topics=recent_topics,
            character_prompt=character_prompt,
            plan_hint=plan_hint,
            preset=normalized_preset,
        )
        try:
            raw = await self._llm.chat(messages, temperature=0.7, json_mode=True)
        except Exception:
            logger.warning("Генерация деки не удалась", exc_info=True)
            return None
        deck = deck_from_json(
            raw,
            preset=normalized_preset,
            topic=topic,
            plan_hint=plan_hint,
        )
        if deck is None:
            logger.warning("Генерация деки вернула непригодный JSON")
        return deck


async def generate_deck(
    llm: LLMProvider,
    topic: str | None = None,
    level: str | None = None,
    profile: Any = None,
    recent_topics: list[str] | None = None,
    character_prompt: str | None = None,
    plan_hint: str | None = None,
    preset: str = "mixed",
) -> Deck | None:
    return await DeckService(llm).generate(
        topic,
        level=level,
        profile=profile,
        recent_topics=recent_topics,
        character_prompt=character_prompt,
        plan_hint=plan_hint,
        preset=preset,
    )


deck_content_to_json = deck_to_json
deck_content_from_json = deck_from_json
parse_deck = parse_deck_response
SYSTEM_PROMPT = DECK_SYSTEM_PROMPT
