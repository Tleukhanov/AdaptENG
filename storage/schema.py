"""Один источник схемы БД для обоих бэкендов (SQLite и PostgreSQL).

Таблицы объявлены один раз в ``DDL_TEMPLATE``. Единственное различие между
бэкендами — объявление автогенерируемого первичного ключа ``{AutoPK}``:

- SQLite: ``INTEGER PRIMARY KEY AUTOINCREMENT``
- Postgres: ``SERIAL PRIMARY KEY``

Булевы колонки намеренно остаются ``INTEGER NOT NULL DEFAULT 0/1`` в обоих
бэкендах: это сохраняет SQL (``is_correct = 1``, ``used = 0``) дословно
одинаковым и не требует переписывания сравнений под PG-тип ``boolean``.
"""

from __future__ import annotations

DDL_TEMPLATE = """
CREATE TABLE IF NOT EXISTS users (
    id {AutoPK},
    tg_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    level TEXT,
    unlimited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    is_correct INTEGER,
    issues_json TEXT,
    corrected_text TEXT,
    lesson_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);

CREATE TABLE IF NOT EXISTS lesson_sessions (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    topic TEXT NOT NULL,
    step INTEGER NOT NULL DEFAULT 0,
    task_index INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'chat',
    score_json TEXT,
    deck_preset TEXT,
    content_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lesson_user ON lesson_sessions(user_id, status);

CREATE TABLE IF NOT EXISTS audio_answers (
    id {AutoPK},
    session_id INTEGER NOT NULL REFERENCES lesson_sessions(id),
    word TEXT,
    audio_file TEXT,
    transcript TEXT,
    rating INTEGER
);

CREATE TABLE IF NOT EXISTS diagnostic_sessions (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_user ON diagnostic_sessions(user_id, status);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    goal TEXT NOT NULL DEFAULT '',
    interests TEXT NOT NULL DEFAULT '',
    weak_areas TEXT NOT NULL DEFAULT '',
    preferred_format TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    character TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lesson_notes (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    lesson_id INTEGER NOT NULL REFERENCES lesson_sessions(id),
    topic TEXT NOT NULL DEFAULT '',
    vocabulary TEXT NOT NULL DEFAULT '',
    grammar TEXT NOT NULL DEFAULT '',
    speaking TEXT NOT NULL DEFAULT '',
    mistakes TEXT NOT NULL DEFAULT '',
    recommendation TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lesson_notes_user ON lesson_notes(user_id, id);

CREATE TABLE IF NOT EXISTS user_lesson_plans (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    plan_json TEXT NOT NULL DEFAULT '',
    horizon INTEGER NOT NULL DEFAULT 12,
    based_on_lessons INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS topic_proposals (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    topic TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_topic_proposals_user ON topic_proposals(user_id, id);

CREATE TABLE IF NOT EXISTS llm_usage (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS user_balances (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    extra_actions INTEGER NOT NULL DEFAULT 0,
    dry_streak INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wheel_spins (
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS wheel_coupons (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    discount_pct INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wheel_coupons_user ON wheel_coupons(user_id, id);

CREATE TABLE IF NOT EXISTS subscriptions (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan_days INTEGER NOT NULL,
    granted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id, id);

CREATE TABLE IF NOT EXISTS payments (
    id {AutoPK},
    telegram_payment_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'RUB',
    plan_days INTEGER NOT NULL,
    discount_pct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kaspi_orders (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan_days INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    discount_pct INTEGER NOT NULL DEFAULT 0,
    coupon_id INTEGER NOT NULL DEFAULT 0,
    order_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    photo_file_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_kaspi_orders_user ON kaspi_orders(user_id, id);

CREATE INDEX IF NOT EXISTS idx_kaspi_orders_pending ON kaspi_orders(user_id, status) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS events (
    id {AutoPK},
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_user_type ON events(user_id, event_type);

CREATE TABLE IF NOT EXISTS user_weak_areas (
    id {AutoPK},
    user_id INTEGER NOT NULL,
    area TEXT NOT NULL,
    incorrect_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    last_seen TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    UNIQUE(user_id, area)
);

CREATE TABLE IF NOT EXISTS user_vocabulary (
    id {AutoPK},
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    translation TEXT NOT NULL DEFAULT '',
    example TEXT NOT NULL DEFAULT '',
    lesson_id INTEGER NOT NULL DEFAULT 0,
    next_review TEXT NOT NULL DEFAULT '',
    interval_days INTEGER NOT NULL DEFAULT 1,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    correct_count INTEGER NOT NULL DEFAULT 0,
    last_reviewed TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    UNIQUE(user_id, word)
);

CREATE TABLE IF NOT EXISTS user_achievements (
    user_id INTEGER NOT NULL REFERENCES users(id),
    achievement_id TEXT NOT NULL,
    PRIMARY KEY (user_id, achievement_id)
);
"""

_AUTO_PK = {
    "sqlite": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "postgres": "SERIAL PRIMARY KEY",
}


def render_ddl(backend: str) -> str:
    """DDL для бэкенда; backend: 'sqlite' | 'postgres'."""
    if backend not in _AUTO_PK:
        raise ValueError(f"Неизвестный бэкенд схемы: {backend!r}")
    return DDL_TEMPLATE.format(AutoPK=_AUTO_PK[backend])


SQLITE_DDL = render_ddl("sqlite")
POSTGRES_DDL = render_ddl("postgres")