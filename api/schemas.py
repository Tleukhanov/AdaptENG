"""Pydantic-схемы REST API AdaptENG."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class TelegramUserAuth(BaseModel):
    """Объект пользователя, приходящий с Telegram Login Widget."""

    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    photo_url: str = ""
    auth_date: int = 0
    hash: str = ""


class AuthResponse(BaseModel):
    token: str
    user: "UserPublic"


class RegisterRequest(BaseModel):
    """Регистрация web-аккаунта (email + пароль) — без Telegram."""

    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=80)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Некорректный email")
        if " " in email:
            raise ValueError("Некорректный email")
        return email


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserPublic(BaseModel):
    id: int
    tg_id: int | None = None
    username: str = ""
    first_name: str = ""
    email: str = ""
    level: str | None = None
    character: str = ""
    interests: list[str] = Field(default_factory=list)
    quota_left: int | None = None
    quota_total: int | None = None
    llm_daily_limit: int = 0
    is_unlimited: bool = False
    total_turns: int = 0
    correct: int = 0
    errors: int = 0


class MeResponse(BaseModel):
    user: UserPublic
    character: dict[str, object] | None = None


class CharacterPublic(BaseModel):
    id: str
    emoji: str
    voice: str
    avatar: str
    palette: list[str]
    name: str
    description: str
    tagline: str = ""
    backstory: str = ""


class SetCharacterRequest(BaseModel):
    character_id: str


class CharacterSetResponse(BaseModel):
    character: dict[str, object]


class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


class IssueOut(BaseModel):
    category: str = ""
    problem: str = ""
    suggestion: str = ""
    correction: str = ""


class ChatResponse(BaseModel):
    reply: str
    tone: str = ""
    corrected_text: str = ""
    is_correct: bool
    next_question: str = ""
    issues: list[IssueOut] = Field(default_factory=list)
    character: dict[str, object]


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    character_id: str = "default"

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


class DeckNewRequest(BaseModel):
    """Новый урок Mini App: тема и/или пресет деки (оба опциональны)."""

    topic: str | None = None
    preset: str | None = None


class DeckAnswerRequest(BaseModel):
    """Ответ квиза: индекс вопроса и выбранный вариант."""

    quiz_index: int
    chosen: int


class QuizAnswerItem(BaseModel):
    """Один ответ квиза для финального score_json."""

    quiz_index: int | None = None
    chosen: int | None = None
    correct: bool = False


class DeckFinishRequest(BaseModel):
    """Финал урока: балл, ответы квиза, карточки «повторю» и id сессии."""

    score: int = 0
    preset: str | None = None
    quiz_answers: list[QuizAnswerItem] = Field(default_factory=list)
    flashcards: dict[str, bool] = Field(default_factory=dict)
    session_id: int | None = None


class VoiceAnswerRequest(BaseModel):
    """Голосовая реплика: аудио в base64 и ожидаемая фраза/слово."""

    audio_base64: str
    expected_line: str = ""
    word: str = ""


class ProgressResponse(BaseModel):
    """Прогресс пользователя + тема следующего урока и число слов к повтору."""

    level: str = "—"
    total_lessons: int = 0
    total_turns: int = 0
    correct: int = 0
    errors: int = 0
    accuracy: float = 0.0
    weak_areas: list[str] = Field(default_factory=list)
    strong_areas: list[str] = Field(default_factory=list)
    streak_days: int = 0
    xp: int = 0
    character: str = "default"
    interests: str = ""
    next_topic: str = ""
    due_words: int = 0


class ReviewDueWord(BaseModel):
    """Слово SRS, готовое к повторению."""

    id: int
    word: str
    translation: str = ""
    example: str = ""


class ReviewAnswerRequest(BaseModel):
    """Тело на запись слова: id и качество ответа (0-5)."""

    word_id: int
    quality: int


class VocabWordOut(BaseModel):
    """Слово личного словаря в ответе API."""

    id: int
    word: str
    translation: str = ""
    example: str = ""
    status: str = "learning"  # learning | known
    next_review: str = ""


class VocabListResponse(BaseModel):
    """Страница словаря пользователя: слова, всего и сколько ждёт повторения."""

    words: list[VocabWordOut] = Field(default_factory=list)
    total: int = 0
    due: int = 0


class VocabAddRequest(BaseModel):
    """Новое слово словаря (можно привязать к уроку)."""

    word: str = Field(..., max_length=80)
    translation: str = Field(default="", max_length=200)
    example: str = Field(default="", max_length=300)
    lesson_id: int = 0

    @field_validator("word")
    @classmethod
    def _strip_word(cls, value: str) -> str:
        word = value.strip()
        if not word:
            raise ValueError("word must not be empty")
        return word

    @field_validator("translation", "example")
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return value.strip()


class VocabCheckRequest(BaseModel):
    """Ответ студента: перевод слова и собственное предложение."""

    word_id: int
    translation: str = Field(default="", max_length=200)
    sentence: str = Field(default="", max_length=300)

    @field_validator("translation", "sentence")
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return value.strip()


class VocabCheckResponse(BaseModel):
    """Оценка ИИ: перевод, предложение, балл, обратная связь и лучший вариант."""

    translation_ok: bool = False
    sentence_ok: bool = False
    score: int = 0
    feedback: str = ""
    improved: str = ""


class AchievementItem(BaseModel):
    """Одно достижение с признаком полученности."""

    id: str
    name: str
    emoji: str
    description: str
    condition: str
    earned: bool = False


class LevelInfo(BaseModel):
    """Текущий уровень и прогресс до следующего."""

    name: str
    emoji: str
    xp: int = 0
    next_level: str | None = None
    xp_needed: int | None = None


class AchievementsResponse(BaseModel):
    """Достижения пользователя + уровень."""

    level: LevelInfo
    achievements: list[AchievementItem] = Field(default_factory=list)


class LeaderboardEntry(BaseModel):
    """Строка лидерборда."""

    user_id: int
    username: str | None = None
    first_name: str | None = None
    level: str | None = None
    xp: int = 0
    total_lessons: int = 0
    streak_days: int = 0


class ProfileUpdateRequest(BaseModel):
    """Память студента: цель, интересы, формат, заметки и уровень."""

    goal: str | None = Field(default=None, max_length=300)
    interests: list[str] | None = Field(default=None)
    weak_areas: list[str] | None = Field(default=None)
    preferred_format: str | None = Field(default=None, max_length=16)
    notes: str | None = Field(default=None, max_length=1000)
    level: str | None = Field(default=None, max_length=4)

    @field_validator("preferred_format")
    @classmethod
    def _check_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip().lower()
        if candidate and candidate not in {"voice", "text"}:
            raise ValueError("preferred_format должен быть voice, text или пустым")
        return candidate

    @field_validator("interests", "weak_areas")
    @classmethod
    def _check_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item and item.strip()][:12]


class ProfileResponse(BaseModel):
    """Профиль-память пользователя для веба."""

    goal: str = ""
    interests: list[str] = Field(default_factory=list)
    weak_areas: list[str] = Field(default_factory=list)
    preferred_format: str = ""
    notes: str = ""
    level: str | None = None
    character: str = ""
    # из гостевого онбординга: сколько минут в день и самооценка уровня
    minutes_per_day: int = 0
    self_level: str = ""
    has_profile: bool = False


# ---------- гостевой онбординг (до регистрации) ----------

GUEST_GOALS: tuple[str, ...] = ("exam", "communication", "work", "general")
GUEST_MINUTES: tuple[int, ...] = (10, 20, 30, 60)
GUEST_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1")

#: Человекочитаемая цель для ``user_profiles.goal`` при переносе в аккаунт.
GUEST_GOAL_LABELS: dict[str, str] = {
    "exam": "Для экзамена (IELTS/TOEFL)",
    "communication": "Для общения за границей",
    "work": "Для работы и карьеры",
    "general": "Для общего развития",
}


def normalize_guest_profile(payload: dict | None) -> dict | None:
    """Проверяет значения гостевого профиля. Некорректные → ``None``."""
    if not payload:
        return None
    goal = payload.get("goal")
    minutes = payload.get("minutes")
    level = payload.get("level")
    if goal not in GUEST_GOALS or level not in GUEST_LEVELS:
        return None
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes not in GUEST_MINUTES:
        return None
    return {"goal": goal, "minutes": minutes, "level": level}


class GuestProfileIn(BaseModel):
    """Ответы гостевого онбординга: цель, минуты в день, уровень."""

    goal: str
    minutes: int
    level: str

    @field_validator("goal")
    @classmethod
    def _check_goal(cls, value: str) -> str:
        goal = value.strip().lower()
        if goal not in GUEST_GOALS:
            raise ValueError("goal: допустимо exam | communication | work | general")
        return goal

    @field_validator("minutes")
    @classmethod
    def _check_minutes(cls, value: int) -> int:
        if value not in GUEST_MINUTES:
            raise ValueError("minutes: допустимо 10 | 20 | 30 | 60")
        return value

    @field_validator("level")
    @classmethod
    def _check_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in GUEST_LEVELS:
            raise ValueError("level: допустимо A1 | A2 | B1 | B2 | C1")
        return level


class GuestProfileOut(BaseModel):
    """Гостевой профиль без служебного ``iat``."""

    goal: str
    minutes: int
    level: str


class GuestProfileResponse(BaseModel):
    profile: GuestProfileOut | None = None


class DiagnosticTaskOut(BaseModel):
    """Задание диагностики уровня."""

    text: str
    level_hint: str = ""


class DiagnosticStartResponse(BaseModel):
    """Лестница из заданий для определения уровня."""

    tasks: list[DiagnosticTaskOut] = Field(default_factory=list)


class DiagnosticFinishRequest(BaseModel):
    """Ответы студента + задания (клиент возвращает их из /start)."""

    answers: list[str] = Field(default_factory=list)
    tasks: list[DiagnosticTaskOut] = Field(default_factory=list)


class DiagnosticFinishResponse(BaseModel):
    """Итог диагностики: уровень CEFR с обоснованием."""

    level: str
    confidence: float = 0.0
    explanation_ru: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendation: str = ""


class HealthResponse(BaseModel):
    ok: bool = True
    # Есть ли серверное распознавание речи (иначе фронт сразу идёт в браузер).
    stt_available: bool = False


# ---------- «Урок 0»: знакомство с наставником ----------


class TutorSessionRequest(BaseModel):
    """Старт урока 0. Пока поддерживается только режим ``intro``."""

    mode: str = "intro"

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode != "intro":
            raise ValueError("mode: допустимо только intro")
        return mode


class TutorIssueOut(BaseModel):
    """Мягкая правка: что не так и как сказать лучше."""

    problem: str = ""
    suggestion: str = ""


class TutorCorrectionOut(BaseModel):
    """Исправленный вариант ответа студента (не больше одной ошибки за ход)."""

    corrected_text: str = ""
    issues: list[TutorIssueOut] = Field(default_factory=list)


class TutorTurnOut(BaseModel):
    """Один ход наставника (``reply`` читается вслух через TTS)."""

    reply: str
    kind: str = "ask"
    question: str | None = None
    correction: TutorCorrectionOut | None = None
    # интересы, которые наставник услышал в ответе (для чипов «Запомнил»)
    interests: list[str] = Field(default_factory=list)
    # текущая оценка уровня по ответам ученика (A1..C1 или "")
    level_signal: str = ""
    should_finish: bool = False


class TutorSessionResponse(BaseModel):
    """Сессия урока 0 + первый ход наставника."""

    session_id: int
    turn: TutorTurnOut
    turn_index: int
    max_turns: int


class TutorTurnRequest(BaseModel):
    """Ответ студента: 1..600 символов после trim."""

    session_id: int
    text: str = Field(min_length=1, max_length=600)

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


class TutorTurnResponse(BaseModel):
    """Ход наставника по ответу студента."""

    turn: TutorTurnOut
    turn_index: int
    max_turns: int
    should_finish: bool = False


class TutorFinishRequest(BaseModel):
    """Завершение урока 0."""

    session_id: int


class TutorSummaryOut(BaseModel):
    """Итог урока 0: уровень CEFR и мягкая обратная связь."""

    level: str = "B1"
    confidence: float = 0.0
    matches_self_level: bool = False
    interests: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendation: str = ""
    praise: str = ""


class TutorFinishResponse(BaseModel):
    """Итог урока 0. Для гостя прогресс не пишется (``registered=false``)."""

    summary: TutorSummaryOut
    turns: int = 0
    xp: int = 0
    streak_days: int = 0
    registered: bool = False


class ApiError(BaseModel):
    ok: bool = False
    error: str