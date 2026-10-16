"""Фабрика репозитория: бэкенд выбирается по настройкам.

- ``database_url`` заполнен (PostgreSQL, на Heroku) -> PostgresRepository.
- иначе локальный SQLite без внешней БД (разработка/тесты).

Обязательные сведения: бот работает только с интерфейсом :class:`Repository`
(storage.repo), поэтому смена бэкенда не меняет ни один сервис.
"""

from __future__ import annotations

from .repo import Repository


def create_repository(
    *,
    database_url: str = "",
    database_path: str = "data/english_bot.db",
    pool_min: int = 1,
    pool_max: int = 10,
) -> Repository:
    """Выбирает и возвращает репозиторий по настройкам окружения."""
    if database_url.strip():
        # asyncpg импортируется лениво в PostgresRepository.connect(), поэтому
        # локальный запуск и тесты без Postgres не требуют установки библиотеки.
        from .postgres import PostgresRepository

        return PostgresRepository(
            database_url.strip(), pool_min=pool_min, pool_max=pool_max
        )
    from .sqlite import SQLiteRepository

    return SQLiteRepository(database_path)