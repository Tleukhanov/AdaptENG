"""«Словарь»: личный список слов пользователя, повторение и проверка ИИ.

Модуль не знает ни про FastAPI, ни про Telegram: только репозиторий, LLM и
устойчивый разбор JSON-ответа (по образцу ``core.practice``). Список слов
отсортирован так, чтобы слова, готовые к повторению, шли первыми, а за ними —
остальные в порядке добавления.

Оценка ответа (перевод + собственное предложение) — ровно один LLM-вызов в
``json_mode``. Промпт мягкий: студент не должен бояться ошибаться, поэтому
feedback всегда на русском и начинается с того, что получилось.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from providers.base import LLMProvider
from storage.repo import SRSWord

from .json_utils import JsonParseError, extract_json

#: Сколько правильных повторений подряд делают слово «изученным».
KNOWN_CORRECT_COUNT = 3

#: Забираем весь словарь пользователя одним запросом (как ``SRSService.get_stats``).
MAX_LIST_WORDS = 10_000

#: Границы полей — те же, что в API-схемах.
MAX_WORD_LEN = 80
MAX_TRANSLATION_LEN = 200
MAX_EXAMPLE_LEN = 300

CHECK_SYSTEM_PROMPT = """You are a friendly English tutor for a Russian-speaking student.

The student repeats a word from their personal vocabulary and does two things:
1. Translates the English word into Russian.
2. Writes their own English sentence with that word.

Check both answers gently and fairly.

Rules:
- "translation_ok": true if the student's Russian translation is a correct equivalent. Accept synonyms, small typos and minor style differences.
- "sentence_ok": true if the sentence is grammatically correct English AND uses the target word with the correct meaning. Ignore tiny punctuation/capitalisation slips.
- "score": overall 0-100. Translation is worth up to 40 points, sentence correctness up to 40, natural word usage up to 20. Be encouraging: a good-faith attempt never gets 0.
- "feedback": 1-3 short sentences in RUSSIAN. Start with what is right, then name concrete mistakes and how to fix them. Never shame the student.
- "improved": a better, natural version of the student's sentence in English. Use an empty string if the sentence is already good.

Respond ONLY with a single valid JSON object. No markdown, no extra text, no code fences.

JSON schema:
{
  "translation_ok": true,
  "sentence_ok": true,
  "score": 85,
  "feedback": "короткая мягкая обратная связь на русском",
  "improved": "an improved English sentence or an empty string"
}
"""


@dataclass
class VocabCheckResult:
    """Результат проверки перевода и предложения."""

    translation_ok: bool = False
    sentence_ok: bool = False
    score: int = 0
    feedback: str = ""
    improved: str = ""


@dataclass
class VocabList:
    """Страница словаря: слова, общее число и число слов к повторению сейчас."""

    words: list[SRSWord] = field(default_factory=list)
    total: int = 0
    due: int = 0


class VocabError(Exception):
    """Базовая ошибка сервиса словаря."""


class VocabWordNotFound(VocabError):
    """Слово не найдено или принадлежит другому пользователю."""


class VocabLLMUnavailable(VocabError):
    """Проверка недоступна: LLM не настроен."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _as_bool(value: object, default: bool = False) -> bool:
    """Терпимо приводит значение LLM к bool (``true``/``"true"``/``1``/``"да"``)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "да"}
    return default


def _as_score(value: object, result: VocabCheckResult) -> int:
    """Балл 0..100; если LLM его не прислал — выводим из флагов."""
    try:
        score = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        score = 0
        if result.translation_ok:
            score += 40
        if result.sentence_ok:
            score += 40
            if not result.improved:
                score += 20
    return max(0, min(100, score))


def word_status(word: SRSWord) -> str:
    """``known`` для уверенно выученных слов, иначе ``learning``."""
    return "known" if word.correct_count >= KNOWN_CORRECT_COUNT else "learning"


def build_check_prompt(word: SRSWord, translation: str, sentence: str) -> list[dict[str, str]]:
    """Сообщения для LLM: слово, эталон и ответ студента."""
    task = (
        f"Target word: {word.word}\n"
        f"Reference translation: {word.translation or '(not set)'}\n"
        f"Reference example: {word.example or '(not set)'}\n\n"
        f"Student's translation: {translation or '(empty)'}\n"
        f"Student's sentence: {sentence or '(empty)'}"
    )
    return [
        {"role": "system", "content": CHECK_SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]


def parse_check_response(raw: str, sentence: str = "") -> VocabCheckResult:
    """Разбирает JSON LLM в VocabCheckResult. Все поля — с безопасными дефолтами.

    ``JsonParseError`` пробрасывается: битый ответ модели — это сбой провайдера,
    а не «плохой ответ студента».
    """
    payload = extract_json(raw)
    result = VocabCheckResult(
        translation_ok=_as_bool(payload.get("translation_ok")),
        sentence_ok=_as_bool(payload.get("sentence_ok")),
        feedback=str(payload.get("feedback") or "").strip(),
        improved=str(payload.get("improved") or "").strip(),
    )
    if result.improved and sentence and result.improved.strip() == sentence.strip():
        result.improved = ""
    result.score = _as_score(payload.get("score"), result)
    return result


class VocabService:
    """Личный словарь пользователя: список, добавление, удаление, проверка."""

    def __init__(self, repo, llm: LLMProvider | None = None) -> None:
        self._repo = repo
        self._llm = llm

    # ---------- список ----------

    async def list_words(self, user_id: int, limit: int = 50, offset: int = 0) -> VocabList:
        """Слова пользователя: сначала готовые к повторению, затем по дате добавления."""
        words = await self._repo.get_srs_words(user_id, limit=MAX_LIST_WORDS)
        now = _now()
        due_words = sorted(
            (w for w in words if w.next_review <= now),
            key=lambda w: (w.next_review, w.id),
        )
        rest = sorted(
            (w for w in words if w.next_review > now),
            key=lambda w: (w.created_at, w.id),
        )
        ordered = due_words + rest
        start = max(0, offset)
        return VocabList(
            words=ordered[start : start + max(0, limit)],
            total=len(ordered),
            due=len(due_words),
        )

    # ---------- добавление ----------

    async def add_word(
        self,
        user_id: int,
        word: str,
        translation: str = "",
        example: str = "",
        lesson_id: int = 0,
    ) -> tuple[SRSWord, bool]:
        """Добавляет слово идемпотентно по (user_id, word).

        Возвращает ``(слово, created)``: при повторе — уже существующая запись
        и ``created=False``. Слово всегда стартует как ``learning`` и сразу
        попадает в очередь повторения (``next_review = now``).
        """
        text = _text(word, MAX_WORD_LEN)
        if not text:
            raise VocabError("Слово не может быть пустым")

        existing = await self._repo.get_srs_word(user_id, text)
        if existing is not None:
            return existing, False

        now = _now()
        candidate = SRSWord(
            user_id=user_id,
            word=text,
            translation=_text(translation, MAX_TRANSLATION_LEN),
            example=_text(example, MAX_EXAMPLE_LEN),
            lesson_id=max(0, int(lesson_id or 0)),
            next_review=now,
            interval_days=1,
            ease_factor=2.5,
            correct_count=0,
            last_reviewed="",
            created_at=now,
        )
        new_id = await self._repo.add_srs_word(candidate)
        if new_id is None:
            # Гонка двух одновременных добавлений: побеждает первая запись.
            existing = await self._repo.get_srs_word(user_id, text)
            if existing is None:
                raise VocabError("Не удалось сохранить слово")
            return existing, False

        saved = await self._repo.get_srs_word_by_id(int(new_id))
        if saved is None:
            saved = await self._repo.get_srs_word(user_id, text)
        if saved is None:
            raise VocabError("Не удалось сохранить слово")
        return saved, True

    # ---------- удаление ----------

    async def get_owned_word(self, user_id: int, word_id: int) -> SRSWord:
        """Слово этого пользователя; чужое или несуществующее — VocabWordNotFound."""
        word = await self._repo.get_srs_word_by_id(word_id)
        if word is None or word.user_id != user_id:
            raise VocabWordNotFound("Слово не найдено")
        return word

    async def delete_word(self, user_id: int, word_id: int) -> None:
        """Удаляет слово пользователя; чужое — VocabWordNotFound."""
        await self.get_owned_word(user_id, word_id)
        await self._repo.delete_srs_word(word_id)

    # ---------- проверка перевода и предложения ----------

    async def check(
        self,
        user_id: int,
        word_id: int,
        translation: str,
        sentence: str,
    ) -> VocabCheckResult:
        """Один LLM-вызов: перевод + собственное предложение → мягкая оценка."""
        word = await self.get_owned_word(user_id, word_id)
        if self._llm is None:
            raise VocabLLMUnavailable("LLM не настроен")

        clean_translation = _text(translation, MAX_TRANSLATION_LEN)
        clean_sentence = _text(sentence, MAX_EXAMPLE_LEN)
        messages = build_check_prompt(word, clean_translation, clean_sentence)
        raw = await self._llm.chat(messages, json_mode=True)
        return parse_check_response(raw, sentence=clean_sentence)


#: Ошибки разбора ответа LLM — для роутера (502 вместо 500).
VocabParseError = JsonParseError
