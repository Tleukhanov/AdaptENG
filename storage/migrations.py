"""Версионированные миграции схемы (SQLite и PostgreSQL).

Зачем: до сих пор схема применялась через ``CREATE TABLE IF NOT EXISTS`` — это
не меняет существующие таблицы. Как только в ``users`` появились колонки
``email``/``password_hash`` и колонка ``tg_id`` перестала быть обязательной,
старая база (в проде — Heroku Postgres) осталась в старом состоянии, и код
падал с ``UndefinedColumn``/``AmbiguousColumnError``.

Здесь живут идемпотентные миграции: каждая смотрит на реальное состояние базы
и доводит её до нужного вида. Применённые версии хранятся в ``schema_migrations``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

logger = logging.getLogger(__name__)


class MigrationDB(Protocol):
    """Минимальный адаптер БД, нужный миграциям."""

    backend: str

    async def execute(self, statements: Sequence[str]) -> None:
        """Выполнить список SQL-стейтментов (каждый — отдельным запросом)."""

    async def fetch_applied_versions(self) -> list[int]:
        """Версии уже применённых миграций."""

    async def columns(self, table: str) -> list[tuple[str, bool]]:
        """Колонки таблицы: ``(имя, NOT NULL)``."""


@dataclass
class Migration:
    """Одна версия миграции."""

    version: int
    name: str
    run: Callable[[MigrationDB], Awaitable[None]]


# ---------- миграции ----------


async def _m001_users_email_password(db: MigrationDB) -> None:
    """users: email + password_hash, tg_id больше не обязателен."""
    columns = await db.columns("users")
    names = {name for name, _ in columns}
    notnull = {name: flag for name, flag in columns}

    if "email" not in names:
        await db.execute(["ALTER TABLE users ADD COLUMN email TEXT"])
    if "password_hash" not in names:
        await db.execute(["ALTER TABLE users ADD COLUMN password_hash TEXT"])

    if db.backend == "postgres":
        # В PG снимаем NOT NULL и расширяем тип до 64 бит (Telegram ID бывает > 2^31).
        if notnull.get("tg_id"):
            await db.execute(["ALTER TABLE users ALTER COLUMN tg_id DROP NOT NULL"])
        await db.execute(["ALTER TABLE users ALTER COLUMN tg_id TYPE BIGINT"])
    else:
        # SQLite не умеет DROP NOT NULL — пересобираем таблицу.
        if notnull.get("tg_id"):
            await db.execute(
                [
                    "PRAGMA foreign_keys=OFF",
                    """
                    CREATE TABLE users__migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tg_id INTEGER UNIQUE,
                        username TEXT,
                        first_name TEXT,
                        level TEXT,
                        unlimited INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        email TEXT,
                        password_hash TEXT
                    )
                    """,
                    """
                    INSERT INTO users__migrated
                        (id, tg_id, username, first_name, level, unlimited, created_at)
                    SELECT id, tg_id, username, first_name, level, unlimited, created_at FROM users
                    """,
                    "DROP TABLE users",
                    "ALTER TABLE users__migrated RENAME TO users",
                    # AUTOINCREMENT-счётчик сбрасывается при пересборке — восстанавливаем,
                    # иначе следующий INSERT снова получил бы id = 1.
                    "DELETE FROM sqlite_sequence WHERE name = 'users'",
                    """
                    INSERT INTO sqlite_sequence (name, seq)
                    SELECT 'users', COALESCE(MAX(id), 0) FROM users
                    """,
                    "PRAGMA foreign_keys=ON",
                ]
            )

    await db.execute(
        ["CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL"]
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="users_email_password", run=_m001_users_email_password),
)

MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


async def apply_migrations(db: MigrationDB) -> list[int]:
    """Применяет недостающие миграции. Возвращает список применённых версий."""
    await db.execute([MIGRATIONS_TABLE])

    applied = set(await db.fetch_applied_versions())
    done: list[int] = []
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version in applied:
            continue
        try:
            await migration.run(db)
        except Exception:
            logger.exception("Миграция %s (%s) не удалась", migration.version, migration.name)
            raise
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            [
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES "
                f"({migration.version}, '{migration.name}', '{now}')"
            ]
        )
        done.append(migration.version)
        logger.info("Применена миграция %s: %s", migration.version, migration.name)
    return done
