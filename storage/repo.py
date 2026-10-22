"""Абстракция хранилища — чтобы позже можно было пересесть на Postgres без правки бота."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class UserRow:
    id: int
    tg_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    level: str | None = None  # CEFR: A1 | A2 | B1 | B2 | C1 | None
    is_unlimited: bool = False  # промокодом снят дневной лимит LLM
    email: str | None = None  # web-вход (без Telegram)


@dataclass
class AuthAccount:
    """Учётные данные web-входа (email + пароль)."""

    user_id: int
    email: str
    password_hash: str
    created_at: str = ""


@dataclass
class UserProfile:
    """Память пользователя (Фаза 4): то, что LLM выводит из диалога.

    Поля хранятся как текст (списки — через запятую), чтобы было просто
    встраивать их в промпты.
    """

    user_id: int
    goal: str = ""  # цель обучения, коротко (на русском)
    interests: str = ""  # интересы, через запятую
    weak_areas: str = ""  # повторяющиеся ошибки, через запятую (напр. "Present Perfect, артикли")
    preferred_format: str = ""  # voice | text | ""
    notes: str = ""  # особенности поведения (на русском)
    character: str = ""  # ID выбранного персонажа (напр. "chill", "toxic") или "" (по умолчанию)
    minutes_per_day: int = 0  # желаемая длительность занятий, минут в день (0 = не задано)
    self_level: str = ""  # самооценка уровня CEFR из гостевого онбординга
    updated_at: str = ""


@dataclass
class Stats:
    total_turns: int = 0  # всего реплик пользователя
    correct: int = 0  # корректных
    errors: int = 0  # с ошибками
    top_categories: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class LessonSession:
    id: int
    user_id: int
    topic: str
    step: int  # индекс шага в core.lessons.LESSON_STEPS
    task_index: int  # индекс текущего задания внутри шага "tasks"
    content_json: str
    status: str  # active | finished | aborted
    created_at: str
    updated_at: str


@dataclass
class MiniLessonSession:
    id: int
    user_id: int
    topic: str
    content_json: str
    preset: str | None
    score_json: str | None
    status: str
    created_at: str
    updated_at: str


@dataclass
class DiagnosticSession:
    id: int
    user_id: int
    questions_json: str  # список DiagnosticTask в JSON
    answers_json: str  # список ответов пользователя в JSON
    status: str  # active | finished | aborted
    created_at: str
    updated_at: str


@dataclass
class TutorSession:
    """Сессия «Урока 0»: короткий разговор-знакомство с наставником.

    Принадлежит либо пользователю (``user_id``), либо гостю (``guest_token``
    из подписанной cookie). Состояние диалога живёт в ``state_json``.
    """

    id: int
    user_id: int | None = None
    guest_token: str | None = None
    character: str = "default"
    mode: str = "intro"
    state_json: str = "{}"
    status: str = "active"  # active | finished | aborted
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LessonNote:
    """Структурированный итог урока (Фаза 5), сгенерированный LLM."""

    id: int = 0
    user_id: int = 0
    lesson_id: int = 0
    topic: str = ""
    vocabulary: str = ""  # +N новых слов, какие использовал
    grammar: str = ""  # тема и как усвоена
    speaking: str = ""  # оценка говорения
    mistakes: str = ""  # повторяющиеся ошибки
    recommendation: str = ""  # что повторить дальше
    created_at: str = ""


@dataclass
class LessonPlanRow:
    """«План уроков» пользователя на N дней: JSON-план и опора на число пройденных уроков."""

    user_id: int
    plan_json: str
    horizon: int = 12
    based_on_lessons: int = 0
    generated_at: str = ""


@dataclass
class TopicProposal:
    """Предложение темы для урока (Фаза 2). Временная запись до выбора пользователя."""

    id: int = 0
    user_id: int = 0
    topic: str = ""
    description: str = ""
    created_at: str = ""


@dataclass
class WeakArea:
    """Слабая область пользователя (Фаза 13)."""

    id: int = 0
    user_id: int = 0
    area: str = ""
    incorrect_count: int = 0
    correct_count: int = 0
    last_seen: str = ""
    created_at: str = ""

    @property
    def priority_score(self) -> float:
        """Чем выше, тем важнее."""
        from datetime import datetime, timezone
        age_days = 999.0
        if self.last_seen:
            try:
                dt = datetime.fromisoformat(self.last_seen.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
            except (ValueError, TypeError):
                pass
        recency_bonus = max(0, 14 - age_days) / 14.0
        error_weight = self.incorrect_count / max(1, self.incorrect_count + self.correct_count)
        return error_weight * 2.0 + recency_bonus


@dataclass
class SRSWord:
    """Слово в системе spaced repetition (Фаза 13)."""

    id: int = 0
    user_id: int = 0
    word: str = ""
    translation: str = ""
    example: str = ""
    lesson_id: int = 0
    next_review: str = ""
    interval_days: int = 1
    ease_factor: float = 2.5
    correct_count: int = 0
    last_reviewed: str = ""
    created_at: str = ""


@dataclass
class LeaderboardRow:
    """Строка лидерборда."""

    user_id: int = 0
    username: str | None = None
    first_name: str | None = None
    level: str | None = None
    xp: int = 0
    total_lessons: int = 0
    streak_days: int = 0


@dataclass
class Subscription:
    """Подписка: полный доступ к LLM на срок (plan_days)."""

    id: int = 0
    user_id: int = 0
    plan_days: int = 0  # 1 | 7 | 30
    granted_at: str = ""
    expires_at: str = ""

    @property
    def is_active(self) -> bool:
        from datetime import datetime, timezone
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False
        return datetime.now(timezone.utc) < expires


@dataclass
class WheelCoupon:
    """Скидка-купон с колеса: N% на подписку, действует до expires_at."""

    id: int = 0
    user_id: int = 0
    discount_pct: int = 0
    expires_at: str = ""
    used: bool = False
    created_at: str = ""

    @property
    def is_expired(self) -> bool:
        from datetime import datetime, timezone
        if not self.expires_at:
            return True
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return True
        return datetime.now(timezone.utc) >= expires


@dataclass
class Payment:
    """Запись платежа (Telegram Payments)."""

    id: int = 0
    telegram_payment_id: str = ""
    user_id: int = 0
    amount: int = 0  # в минимальных единицах валюты (копейки за RUB)
    currency: str = "RUB"
    plan_days: int = 0
    discount_pct: int = 0
    created_at: str = ""


@dataclass
class KaspiOrder:
    """Заказ на подписку по Kaspi QR: оплата вручную, подтверждение админом."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_CANCELLED = "cancelled"

    id: int = 0
    user_id: int = 0
    plan_days: int = 0
    amount: int = 0  # целые тенге для Kaspi-перевода
    discount_pct: int = 0
    coupon_id: int = 0
    order_code: str = ""  # комментарий к переводу, напр. BOT-ABC123
    status: str = STATUS_PENDING
    photo_file_id: str = ""  # чек/скриншот перевода
    created_at: str = ""
    confirmed_at: str = ""


class Repository(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def get_or_create_user(self, tg_id: int, username: str | None = None, first_name: str | None = None) -> UserRow: ...

    @abstractmethod
    async def get_user(self, user_id: int) -> UserRow | None: ...

    # ---------- web-вход (email + пароль) ----------

    @abstractmethod
    async def get_user_by_email(self, email: str) -> UserRow | None: ...

    @abstractmethod
    async def get_user_by_tg_id(self, tg_id: int) -> UserRow | None: ...

    @abstractmethod
    async def create_email_user(
        self,
        email: str,
        password_hash: str,
        username: str | None = None,
        first_name: str | None = None,
    ) -> UserRow: ...

    @abstractmethod
    async def get_auth_account(self, user_id: int) -> AuthAccount | None: ...

    @abstractmethod
    async def set_password_hash(self, user_id: int, password_hash: str) -> None: ...

    @abstractmethod
    async def link_telegram(self, user_id: int, tg_id: int) -> None: ...

    @abstractmethod
    async def set_level(self, user_id: int, level: str) -> None: ...

    @abstractmethod
    async def get_level(self, user_id: int) -> str | None: ...

    # ---------- квота LLM ----------

    @abstractmethod
    async def get_unlimited_status(self, user_id: int) -> bool: ...

    @abstractmethod
    async def set_unlimited_status(self, user_id: int, value: bool) -> None: ...

    @abstractmethod
    async def get_llm_usage(self, user_id: int, day: str) -> int: ...

    @abstractmethod
    async def increment_llm_usage(self, user_id: int, day: str, inc: int = 1) -> None: ...

    # ---------- бонусные LLM-действия (колесо) ----------

    @abstractmethod
    async def get_extra_actions(self, user_id: int) -> int: ...

    @abstractmethod
    async def add_extra_actions(self, user_id: int, amount: int) -> None: ...

    @abstractmethod
    async def decrement_extra_actions(self, user_id: int, amount: int) -> None: ...

    # ---------- колесо удачи ----------

    @abstractmethod
    async def get_last_spin_date(self, user_id: int) -> str | None: ...

    @abstractmethod
    async def save_spin(self, user_id: int, date: str) -> bool: ...

    @abstractmethod
    async def get_dry_streak(self, user_id: int) -> int: ...

    @abstractmethod
    async def set_dry_streak(self, user_id: int, streak: int) -> None: ...

    @abstractmethod
    async def create_coupon(self, user_id: int, discount_pct: int, expires_at: str) -> WheelCoupon: ...

    @abstractmethod
    async def get_active_coupon(self, user_id: int) -> WheelCoupon | None: ...

    @abstractmethod
    async def mark_coupon_used(self, coupon_id: int, user_id: int) -> None: ...

    # ---------- подписки ----------

    @abstractmethod
    async def grant_subscription(self, user_id: int, plan_days: int) -> Subscription: ...

    @abstractmethod
    async def get_subscription(self, user_id: int) -> Subscription | None: ...

    # ---------- платежи ----------

    @abstractmethod
    async def create_payment(
        self,
        user_id: int,
        telegram_payment_id: str,
        amount: int,
        currency: str,
        plan_days: int,
        discount_pct: int,
    ) -> Payment: ...

    @abstractmethod
    async def find_payment(self, telegram_payment_id: str) -> Payment | None: ...

    # ---------- Kaspi QR оплата ----------

    @abstractmethod
    async def create_order(
        self,
        user_id: int,
        plan_days: int,
        amount: int,
        discount_pct: int,
        coupon_id: int,
        order_code: str,
    ) -> KaspiOrder: ...

    @abstractmethod
    async def get_pending_order(self, user_id: int) -> KaspiOrder | None: ...

    @abstractmethod
    async def get_order(self, order_id: int) -> KaspiOrder | None: ...

    @abstractmethod
    async def attach_photo(self, order_id: int, photo_file_id: str) -> None: ...

    @abstractmethod
    async def approve_order(self, order_id: int) -> KaspiOrder | None: ...

    @abstractmethod
    async def cancel_order(self, order_id: int) -> None: ...

    @abstractmethod
    async def replace_pending_order(
        self,
        user_id: int,
        plan_days: int,
        amount: int,
        discount_pct: int,
        coupon_id: int,
        order_code: str,
    ) -> KaspiOrder:
        """Отменяет все старые pending и создаёт новый заказ в одной транзакции."""
        ...

    @abstractmethod
    async def is_order_code_taken(self, order_code: str) -> bool:
        """Занят ли код среди не-отменённых заказов."""
        ...

    # ---------- аналитика (события) ----------

    @abstractmethod
    async def append_event(self, user_id: int, event_type: str, payload=None) -> None: ...

    @abstractmethod
    async def count_events(self, event_type: str, since_date: str) -> int: ...

    # ---------- аналитика: события, когорты, диагностика ----------

    @abstractmethod
    async def get_events(
        self, user_id: int, event_type: str, since_date: str = ""
    ) -> list[dict]: ...

    @abstractmethod
    async def count_event_users(
        self, event_type: str, since_date: str, until_date: str = ""
    ) -> int:
        """Сколько разных пользователей породили событие за период."""

    @abstractmethod
    async def count_active_users(self, since_date: str, until_date: str = "") -> int:
        """Сколько разных пользователей были активны за период."""

    @abstractmethod
    async def count_users(self) -> int: ...

    @abstractmethod
    async def count_users_created_between(self, start_date: str, end_date: str) -> int: ...

    @abstractmethod
    async def list_users_recent(self, limit: int = 20) -> list[UserRow]: ...

    @abstractmethod
    async def get_diagnostic_sessions(self, user_id: int) -> list[DiagnosticSession]: ...

    # ---------- админ-статистика ----------

    @abstractmethod
    async def count_spins_today(self, date: str) -> int: ...

    @abstractmethod
    async def count_pending_orders(self) -> int: ...

    @abstractmethod
    async def sum_revenue(self) -> int: ...

    @abstractmethod
    async def count_active_subscriptions(self) -> int: ...

    @abstractmethod
    async def get_profile(self, user_id: int) -> UserProfile | None: ...

    @abstractmethod
    async def save_profile(self, profile: UserProfile) -> None: ...

    @abstractmethod
    async def add_user_message(
        self,
        user_id: int,
        content: str,
        *,
        is_correct: bool | None = None,
        issues_json: str = "",
        corrected_text: str = "",
        lesson_id: int | None = None,
    ) -> int: ...

    @abstractmethod
    async def add_assistant_message(self, user_id: int, content: str) -> None: ...

    @abstractmethod
    async def get_history(self, user_id: int, limit: int) -> list[dict[str, str]]: ...

    @abstractmethod
    async def get_user_turns(self, user_id: int, limit: int = 500) -> list[dict]:
        """Реплики ученика с оценкой и временем — сырьё для метрик прогресса."""

    @abstractmethod
    async def get_lesson_messages(self, lesson_id: int) -> list[dict]: ...

    @abstractmethod
    async def get_stats(self, user_id: int) -> Stats: ...

    @abstractmethod
    async def get_last_correction(self, user_id: int) -> dict | None: ...

    @abstractmethod
    async def get_user_message(self, user_id: int, message_id: int) -> dict | None: ...

    @abstractmethod
    async def start_lesson(self, user_id: int, topic: str, content_json: str) -> LessonSession: ...

    @abstractmethod
    async def get_active_lesson(self, user_id: int) -> LessonSession | None: ...

    @abstractmethod
    async def update_lesson(self, session_id: int, *, step: int | None = None, task_index: int | None = None) -> None: ...

    @abstractmethod
    async def finish_lesson(self, session_id: int) -> None: ...

    @abstractmethod
    async def finish_active_lessons(self, user_id: int) -> None: ...

    @abstractmethod
    async def abort_active_lessons(self, user_id: int) -> None: ...

    @abstractmethod
    async def start_mini_lesson(self, user_id: int, topic: str, deck_json: str, preset: str) -> MiniLessonSession: ...

    @abstractmethod
    async def get_active_mini_lesson(self, user_id: int) -> MiniLessonSession | None: ...

    @abstractmethod
    async def save_mini_answers(self, session_id: int, score_json: str) -> None: ...

    @abstractmethod
    async def finish_mini_lesson(self, session_id: int, score_json: str | None = None) -> None: ...

    @abstractmethod
    async def save_audio_answer(
        self,
        session_id: int,
        word: str,
        audio_file: str,
        transcript: str,
        rating: int | None,
    ) -> None: ...

    @abstractmethod
    async def add_lesson_note(self, note: LessonNote) -> int: ...

    @abstractmethod
    async def get_lesson_notes(self, user_id: int, limit: int = 10) -> list[LessonNote]: ...

    @abstractmethod
    async def get_lesson_plan(self, user_id: int) -> LessonPlanRow | None: ...

    @abstractmethod
    async def save_lesson_plan(self, plan: LessonPlanRow) -> None: ...

    @abstractmethod
    async def count_finished_lessons(self, user_id: int) -> int: ...

    @abstractmethod
    async def get_all_users(self) -> list[UserRow]: ...

    # ---------- диагностика уровня (Фаза 3) ----------

    @abstractmethod
    async def start_diagnostic(self, user_id: int, questions_json: str) -> DiagnosticSession: ...

    @abstractmethod
    async def get_active_diagnostic(self, user_id: int) -> DiagnosticSession | None: ...

    @abstractmethod
    async def append_diagnostic_answer(self, session_id: int, answer: str) -> None: ...

    @abstractmethod
    async def finish_diagnostic(self, session_id: int) -> None: ...

    @abstractmethod
    async def abort_active_diagnostics(self, user_id: int) -> None: ...

    # ---------- «Урок 0»: знакомство с наставником ----------

    @abstractmethod
    async def create_tutor_session(
        self,
        *,
        user_id: int | None = None,
        guest_token: str | None = None,
        character: str = "default",
        mode: str = "intro",
        state_json: str = "{}",
    ) -> TutorSession: ...

    @abstractmethod
    async def get_tutor_session(self, session_id: int) -> TutorSession | None: ...

    @abstractmethod
    async def get_active_tutor_session(
        self,
        *,
        user_id: int | None = None,
        guest_token: str | None = None,
    ) -> TutorSession | None:
        """Активная сессия пользователя или гостя (ровно один из ключей)."""

    @abstractmethod
    async def save_tutor_state(
        self,
        session_id: int,
        state_json: str,
        turn_index: int | None = None,
    ) -> None:
        """Сохраняет состояние диалога.

        ``turn_index`` — опциональный ход для будущих бэкендов: сейчас номер
        хода живёт внутри ``state_json``, поэтому параметр не пишется отдельно.
        """

    @abstractmethod
    async def finish_tutor_session(self, session_id: int) -> None: ...

    # ---------- предложения тем (Фаза 2) ----------

    @abstractmethod
    async def save_topic_proposals(self, user_id: int, proposals: list[TopicProposal]) -> None: ...

    @abstractmethod
    async def get_topic_proposal(self, proposal_id: int) -> TopicProposal | None: ...

    @abstractmethod
    async def get_topic_proposals(self, user_id: int) -> list[TopicProposal]: ...

    @abstractmethod
    async def delete_topic_proposals(self, user_id: int) -> None: ...

    @abstractmethod
    async def get_practice_dates(self, user_id: int, limit: int = 50) -> list[str]: ...

    @abstractmethod
    async def get_last_activity(self, user_id: int) -> str | None: ...

    # ---------- слабые области (Фаза 13) ----------

    @abstractmethod
    async def get_weak_areas(self, user_id: int) -> list[WeakArea]: ...

    @abstractmethod
    async def upsert_weak_area(
        self,
        user_id: int,
        area: str,
        incorrect_increment: int = 0,
        correct_increment: int = 0,
        last_seen: str = "",
    ) -> None: ...

    @abstractmethod
    async def delete_weak_area(self, user_id: int, area: str) -> None: ...

    # ---------- SRS vocabulary (Фаза 13) ----------

    @abstractmethod
    async def add_srs_word(self, word: SRSWord) -> int: ...

    @abstractmethod
    async def get_srs_word(self, user_id: int, word: str) -> SRSWord | None: ...

    @abstractmethod
    async def get_srs_word_by_id(self, word_id: int) -> SRSWord | None: ...

    @abstractmethod
    async def get_srs_words(self, user_id: int, limit: int = 100) -> list[SRSWord]: ...

    @abstractmethod
    async def update_srs_word(self, word: SRSWord) -> None: ...

    @abstractmethod
    async def delete_srs_word(self, word_id: int) -> None:
        """Удаляет слово из личного словаря (владение проверяет вызывающий)."""

    # ---------- лидерборд ----------

    @abstractmethod
    async def get_leaderboard(self, limit: int = 20) -> list[LeaderboardRow]: ...

    # ---------- достижения ----------

    @abstractmethod
    async def get_shown_achievements(self, user_id: int) -> list[str]: ...

    @abstractmethod
    async def save_shown_achievements(self, user_id: int, achievement_ids: list[str]) -> None: ...
