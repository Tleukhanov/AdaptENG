#!/usr/bin/env python3
"""Восстановление базы AdaptENG из JSON-дампа (см. tools/db_dump.py).

Использование:
    python tools/db_restore.py backup.json --url postgres://...
    python tools/db_restore.py backup.json --heroku-key $HEROKU_API_KEY --truncate

По умолчанию данные ДОБАВЛЯЮТСЯ (INSERT ... ON CONFLICT DO NOTHING для PK).
С --truncate таблицы сначала очищаются — тогда это полная перезагрузка.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_dump import url_from_env, url_from_heroku  # noqa: E402


async def ensure_schema(conn) -> None:
    """Создаёт таблицы (как это делает приложение при старте) + применяет миграции."""
    from storage.migrations import apply_migrations
    from storage.schema import POSTGRES_DDL

    for statement in [s.strip() for s in POSTGRES_DDL.split(";") if s.strip()]:
        await conn.execute(statement)

    class _DB:
        backend = "postgres"

        async def execute(self, statements):
            for sql in statements:
                await conn.execute(sql)

        async def fetch_applied_versions(self):
            rows = await conn.fetch("SELECT version FROM schema_migrations")
            return [int(row["version"]) for row in rows]

        async def columns(self, table):
            rows = await conn.fetch(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = $1",
                table,
            )
            return [(r["column_name"], r["is_nullable"] == "NO") for r in rows]

    await apply_migrations(_DB())


def _encode(value):
    if isinstance(value, bool):
        return int(value)
    return value


#: Порядок заливки — по внешним ключам (сначала родители).
TABLE_ORDER = [
    "users",
    "messages",
    "lesson_sessions",
    "lesson_notes",
    "audio_answers",
    "user_vocabulary",
    "user_weak_areas",
    "user_profiles",
    "user_balances",
    "user_lesson_plans",
    "user_achievements",
    "diagnostic_sessions",
    "events",
    "llm_usage",
    "topic_proposals",
    "wheel_spins",
    "wheel_coupons",
    "kaspi_orders",
    "payments",
    "subscriptions",
]


def _ordered_tables(payload: dict) -> list[str]:
    known = [t for t in TABLE_ORDER if t in payload]
    rest = [t for t in payload if t not in TABLE_ORDER]
    return known + rest


async def restore(dsn: str, payload: dict, truncate: bool) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    inserted = 0
    try:
        await ensure_schema(conn)
        async with conn.transaction():
            for table in _ordered_tables(payload):
                rows = payload.get(table) or []
                if not rows:
                    continue
                columns = list(rows[0].keys())
                placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
                collist = ", ".join(f'"{c}"' for c in columns)
                if truncate:
                    await conn.execute(f'DELETE FROM "{table}"')
                # Конфликты по первичному ключу игнорируем, чтобы дамп можно было
                # накапливать и применять повторно.
                sql = (
                    f'INSERT INTO "{table}" ({collist}) VALUES ({placeholders}) '
                    "ON CONFLICT DO NOTHING"
                )
                for row in rows:
                    await conn.execute(sql, *[_encode(row.get(c)) for c in columns])
                    inserted += 1
        print(f"Восстановлено строк: {inserted}")
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Восстановление базы AdaptENG из JSON")
    parser.add_argument("dump_file", help="файл дампа")
    parser.add_argument("--url", default="", help="DATABASE_URL")
    parser.add_argument("--heroku-key", default=os.environ.get("HEROKU_API_KEY", ""))
    parser.add_argument("--app", default="adapteng-api")
    parser.add_argument("--truncate", action="store_true", help="очистить таблицы перед заливкой")
    args = parser.parse_args()

    dsn = args.url or url_from_env()
    if not dsn and args.heroku_key:
        dsn = url_from_heroku(args.heroku_key, args.app)
    if not dsn:
        print("Не найден DATABASE_URL: передай --url или HEROKU_API_KEY", file=sys.stderr)
        return 2

    payload = json.loads(Path(args.dump_file).read_text(encoding="utf-8"))
    asyncio.run(restore(dsn, payload, args.truncate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
