#!/usr/bin/env bash
# Прогон Postgres-тестов на изолированной схеме в Heroku Postgres.
# Использование: ./tools/pg_test.sh [pytest args...]
set -euo pipefail
cd "$(dirname "$0")/.."

HK_KEY="${HEROKU_API_KEY:-}"
if [ -z "$HK_KEY" ]; then
  echo "Нужен HEROKU_API_KEY (или задайте DB_URL напрямую)" >&2
  exit 1
fi

DB_URL=$(curl -sf -H "Authorization: Bearer $HK_KEY" -H "Accept: application/vnd.heroku+json; version=3" \
  https://api.heroku.com/apps/adapteng-api/config-vars \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["DATABASE_URL"])')

SCHEMA=adapteng_test
DATABASE_URL="$DB_URL" .venv/bin/python - "$SCHEMA" <<'PY'
import asyncio, os, sys
schema = sys.argv[1]
async def main():
    import asyncpg
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    await conn.close()
asyncio.run(main())
PY

TEST_DATABASE_URL="${DB_URL}?sslmode=require&search_path=${SCHEMA}" .venv/bin/python -m pytest "${@:-tests}" -q
