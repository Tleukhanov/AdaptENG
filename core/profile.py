"""Память пользователя (Фаза 4): LLM ведёт профиль из диалога.

Профиль хранит цель обучения, интересы, слабые места, предпочитаемый формат
и поведенческие заметки. LLM обновляет его по ходу обычной практики, а бот
встраивает сниппет профиля в промпты практики и генерации уроков.
Логика не зависит от Telegram — только LLM и модель данных.
"""

from __future__ import annotations

from datetime import datetime, timezone

from providers.base import LLMProvider
from storage.repo import UserProfile

from .json_utils import extract_json, JsonParseError

ProfileParseError = JsonParseError

EXTRACT_SYSTEM_PROMPT = """You maintain a personal memory profile for a student of an English tutor.

You are given (a) the previously known profile and (b) the recent dialogue (student messages and tutor replies with corrections).

Update the profile ONLY from what is clearly stated or clearly demonstrated in the dialogue. Do not guess or invent.

Fields:
- goal: the student's learning goal, a short phrase in Russian (e.g. "свободное общение", "работа в IT", "путешествия"). Empty string if unknown.
- interests: comma-separated topics the student is interested in (keep the names in their original language, e.g. "chess, artificial intelligence, travel").
- weak_areas: comma-separated recurring grammar/vocabulary problems seen in the tutor's corrections (short phrases, e.g. "Present Perfect, артикли"). Empty string if none observed.
- preferred_format: "voice" if the student clearly prefers voice practice, "text" if text, "" if unknown.
- notes: one short sentence in Russian about the student's behavior or preferences (e.g. "любит короткие объяснения"). Empty string if nothing notable.

Keep every field you already know and still believe; update a field only when the dialogue gives new information. Return ALL fields.

Respond ONLY with a single valid JSON object. No markdown, no extra text, no code fences.

JSON schema:
{"goal": "...", "interests": "...", "weak_areas": "...", "preferred_format": "voice|text|", "notes": "..."}
"""

PROFILE_FIELDS = ("goal", "interests", "weak_areas", "preferred_format", "notes")

# Как часто обновлять профиль (секунды), чтобы не жечь лишние вызовы LLM.
PROFILE_UPDATE_INTERVAL_SEC = 60 * 60


def to_profile_snippet(profile: UserProfile | None) -> str:
    """Короткая строка о пользователе для вставки в системный промпт."""
    if profile is None:
        return ""
    parts = []
    if profile.goal:
        parts.append(f"Goal: {profile.goal}")
    if profile.interests:
        parts.append(f"Interests: {profile.interests}")
    if profile.weak_areas:
        parts.append(f"Weak areas: {profile.weak_areas}")
    if profile.preferred_format:
        parts.append(f"Prefers {'voice' if profile.preferred_format == 'voice' else 'text'} practice")
    if profile.notes:
        parts.append(f"Note: {profile.notes}")
    if not parts:
        return ""
    return "Student profile: " + "; ".join(parts) + "."


def build_extract_prompt(
    previous: UserProfile | None,
    dialogue: list[dict[str, str]],
) -> list[dict[str, str]]:
    previous_text = to_profile_snippet(previous) or "(none)"
    lines = "\n".join(
        f"{item.get('role', '?')}: {item.get('content', '')}"
        for item in dialogue
        if item.get("content")
    )
    user_message = f"Previous profile:\n{previous_text}\n\nRecent dialogue:\n{lines}"
    return [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def parse_profile_update(raw: str) -> dict[str, str]:
    """Разбирает JSON-ответ LLM в обновление полей профиля."""
    payload = extract_json(raw)
    update: dict[str, str] = {}
    for field in PROFILE_FIELDS:
        value = str(payload.get(field, "")).strip()
        if field == "preferred_format" and value not in {"voice", "text"}:
            value = ""
        update[field] = value
    return update


def profile_update_due(
    profile: UserProfile | None,
    *,
    now: datetime | None = None,
    interval_sec: float = PROFILE_UPDATE_INTERVAL_SEC,
) -> bool:
    """Нужно ли обновлять профиль: нет профиля или он давно не трогали."""
    if profile is None:
        return True
    if not profile.updated_at:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        updated = datetime.fromisoformat(profile.updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (now - updated).total_seconds() >= interval_sec


async def merge_weak_areas(profile: UserProfile, *parts: str, repo=None) -> str:
    """Дополняет profile.weak_areas новыми формулировками, не дублируя.

    Используется после урока: найденные грамматика и ошибки попадают в память
    пользователя (Фаза 5 -> Фаза 4).
    Также записывает в таблицу user_weak_areas (Фаза 13).
    """
    additions = [part.strip() for part in parts if part and part.strip()]
    if not additions:
        return profile.weak_areas
    combined = profile.weak_areas
    if combined:
        combined += ", "
    combined += ", ".join(additions)
    unique: list[str] = []
    for item in combined.split(","):
        item = item.strip()
        if item and item not in unique:
            unique.append(item)

    if repo is not None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for item in additions:
            if item.strip():
                await repo.upsert_weak_area(
                    profile.user_id, item.strip(),
                    incorrect_increment=1, last_seen=now,
                )

    return ", ".join(unique)


class ProfileService:
    """Извлекает и сливает профиль пользователя через LLM."""

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    async def update(
        self,
        user_id: int,
        previous: UserProfile | None,
        dialogue: list[dict[str, str]],
    ) -> UserProfile:
        """Обновляет профиль по диалогу: известные поля сохраняются, новое дополняется."""
        messages = build_extract_prompt(previous, dialogue)
        raw = await self._llm.chat(messages, temperature=0.0)
        update = parse_profile_update(raw)

        merged = UserProfile(
            user_id=user_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        if previous is not None:
            # Поля гостевого онбординга LLM не обновляет — сохраняем как есть.
            merged.minutes_per_day = previous.minutes_per_day
            merged.self_level = previous.self_level
        for field in PROFILE_FIELDS:
            new_value = update[field]
            if not new_value and previous is not None:
                new_value = getattr(previous, field)
            setattr(merged, field, new_value)
        return merged
