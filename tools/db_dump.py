#!/usr/bin/env python3
"""Дамп базы AdaptENG в JSON (все таблицы) — резервная копия без pg_dump.

Использование:
    python tools/db_dump.py                       # возьмёт DATABASE_URL из .env
    python tools/db_dump.py --url postgres://...   # явный URL
    python tools/db_dump.py --out backup.json      # куда сохранить
    HEROKU_API_KEY=... python tools/db_dump.py    # URL из Heroku-конфига adapteng-api

Пароль в вывод не печатается. Файл дампа содержит персональные данные —
храни его как секрет.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mask(dsn: str) -> str:
    return re.sub(r"//([^:]+):[^@]*@", r"//\1:***@", dsn)


def url_from_env() -> str:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if dsn:
        return dsn
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    return ""


def url_from_heroku(api_key: str, app: str = "adapteng-api") -> str:
    import urllib.request

    request = urllib.request.Request(
        f"https://api.heroku.com/apps/{app}/config-vars",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.heroku+json; version=3",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read())
    dsn = data.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit(f"У приложения {app} нет DATABASE_URL")
    return dsn


async def dump(dsn: str) -> dict:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        tables = [
            row["table_name"]
            for row in await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
                "AND table_name <> 'schema_migrations' ORDER BY table_name"
            )
        ]
        payload: dict[str, list] = {}
        for table in tables:
            rows = await conn.fetch(f'SELECT * FROM "{table}"')
            payload[table] = [dict(row) for row in rows]
        return payload
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Дамп базы AdaptENG в JSON")
    parser.add_argument("--url", default="", help="DATABASE_URL (по умолчанию из .env или Heroku)")
    parser.add_argument("--out", default="", help="Файл для сохранения (по умолчанию backup-<дата>.json)")
    parser.add_argument("--heroku-key", default=os.environ.get("HEROKU_API_KEY", ""), help="ключ Heroku API")
    parser.add_argument("--app", default="adapteng-api", help="Heroku-приложение с базой")
    args = parser.parse_args()

    dsn = args.url or url_from_env()
    if not dsn and args.heroku_key:
        dsn = url_from_heroku(args.heroku_key, args.app)
    if not dsn:
        print("Не найден DATABASE_URL: передай --url или HEROKU_API_KEY", file=sys.stderr)
        return 2

    out = args.out or f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    print(f"Подключаюсь к {_mask(dsn)} …")
    payload = asyncio.run(dump(dsn))
    total = sum(len(rows) for rows in payload.values())
    Path(out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"Готово: {out} ({len(payload)} таблиц, {total} строк)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
