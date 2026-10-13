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


class UserPublic(BaseModel):
    id: int
    tg_id: int
    username: str = ""
    first_name: str = ""
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


class HealthResponse(BaseModel):
    ok: bool = True


class ApiError(BaseModel):
    ok: bool = False
    error: str