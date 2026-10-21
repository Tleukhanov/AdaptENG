"""Статические проверки SQL в Postgres-реализации хранилища.

Главный мотив: SQLite и PostgreSQL по-разному трактуют ``ON CONFLICT ... DO UPDATE SET``.
В SQLite ``SET count = count + excluded.count`` корректно, а в PostgreSQL ``count``
неоднозначен (``AmbiguousColumnError``) — нужно ``count = llm_usage.count + excluded.count``.
Такие баги не ловились тестами на SQLite, но роняли прод на Heroku (Postgres).
"""

import re
from pathlib import Path

import pytest

POSTGRES_SRC = Path(__file__).resolve().parent.parent / "storage" / "postgres.py"
SQLITE_SRC = Path(__file__).resolve().parent.parent / "storage" / "sqlite.py"

# ``SET col = col ...`` — самоссылка без квалификатора таблицы.
SELF_REF = re.compile(r"DO UPDATE SET\s+(\w+)\s*=\s*(?!\w+\.)(\w+)\b", re.IGNORECASE)


def _postgres_upsert_statements() -> list[tuple[int, str]]:
    text = POSTGRES_SRC.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    for match in re.finditer(r"ON CONFLICT[^\"]*?DO UPDATE SET[^\"]*", text, re.IGNORECASE | re.DOTALL):
        line = text[: match.start()].count("\n") + 1
        out.append((line, match.group(0)))
    return out


def test_postgres_has_upsert_statements():
    """Страховка: если разбор перестанет находить ON CONFLICT — тест не должен молчать."""
    statements = _postgres_upsert_statements()
    assert len(statements) >= 5, "не нашли ON CONFLICT ... DO UPDATE SET в storage/postgres.py"


def test_postgres_upsert_has_no_ambiguous_self_reference():
    """В Postgres колонка в RHS должна быть квалифицирована (таблица.колонка)."""
    problems: list[str] = []
    for line, statement in _postgres_upsert_statements():
        for target, ref in SELF_REF.findall(statement):
            if target.lower() != ref.lower():
                continue
            problems.append(f"{POSTGRES_SRC.name}:{line}: SET {target} = {ref} — неоднозначно для PostgreSQL")
    assert not problems, "\n".join(problems)


def test_sqlite_upsert_keeps_working_syntax():
    """SQLite допускает самоссылку без квалификатора — не ломаем его синтаксис."""
    text = SQLITE_SRC.read_text(encoding="utf-8")
    assert "DO UPDATE SET count = count + excluded.count" in text or "COALESCE" in text


@pytest.mark.parametrize(
    "fragment",
    [
        "count = llm_usage.count + excluded.count",
        "extra_actions = user_balances.extra_actions + excluded.extra_actions",
        "incorrect_count = user_weak_areas.incorrect_count + excluded.incorrect_count",
    ],
)
def test_known_ambiguous_statements_are_qualified(fragment: str):
    """Конкретные места, которые чинили — должны остаться починенными."""
    assert fragment in POSTGRES_SRC.read_text(encoding="utf-8")
