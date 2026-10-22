"""Postgres-бэкенд хранилища: юниты адаптации SQL/DDL + интеграционный смоук.

Юнит-тесты не требуют PostgreSQL и asyncpg (проверяют чистые функции).
Интеграционный смоук выполняется только при наличии живой базы: задайте
TEST_DATABASE_URL (например, postgres://user:pass@localhost/db) — иначе тест
скипается, что честно отражено в выводе pytest.
"""

import json
import os

import pytest

from storage.postgres import _adopt
from storage.schema import POSTGRES_DDL, SQLITE_DDL, render_ddl
from storage.repo import SRSWord

PG_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


# ---------- _adopt: перевод ? -> $1..$n ----------


def test_adopt_single_placeholder():
    assert _adopt("SELECT * FROM users WHERE id = ?") == "SELECT * FROM users WHERE id = $1"


def test_adopt_multiple_placeholders_sequential():
    sql = "INSERT INTO t (a, b, c) VALUES (?, ?, ?)"
    assert _adopt(sql) == "INSERT INTO t (a, b, c) VALUES ($1, $2, $3)"


def test_adopt_no_placeholder_unchanged():
    assert _adopt("SELECT 1") == "SELECT 1"


def test_adopt_respects_existing_dollar_placeholders():
    sql = "UPDATE t SET a = $1 WHERE id = ?"
    assert _adopt(sql) == "UPDATE t SET a = $1 WHERE id = $2"


# ---------- единый DDL ----------


def test_sqlite_ddl_has_autoincrement_pk():
    assert "INTEGER PRIMARY KEY AUTOINCREMENT" in SQLITE_DDL
    assert "SERIAL PRIMARY KEY" not in SQLITE_DDL


def test_postgres_ddl_has_serial_pk():
    assert "SERIAL PRIMARY KEY" in POSTGRES_DDL
    assert "INTEGER PRIMARY KEY AUTOINCREMENT" not in POSTGRES_DDL


def test_render_ddl_unknown_backend_raises():
    with pytest.raises(ValueError):
        render_ddl("oracle")


def test_postgres_ddl_statements_are_well_formed():
    statements = [s for s in POSTGRES_DDL.split(";") if s.strip()]
    assert len(statements) >= 20
    for stmt in statements:
        head = stmt.strip().upper()
        assert head.startswith(("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX"))


def test_ddl_tables_match_between_backends():
    table_names = lambda ddl: {  # noqa: E731
        s.split("(")[0].replace("CREATE TABLE IF NOT EXISTS", "").strip()
        for s in ddl.split(";")
        if "CREATE TABLE" in s
    }
    assert table_names(POSTGRES_DDL) == table_names(SQLITE_DDL)


# ---------- интеграция (только с живой PostgreSQL) ----------


@pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL не задан")
class TestPostgresIntegration:
    """Смоук по основным сценариям Repository поверх реального PostgreSQL.

    Очистки не делаем: тесты пишут в отдельные ряды (уникальные tg_id),
    чтобы можно было гонять против dev-базы без её разрушения.
    """

    @pytest.fixture
    async def repo(self):
        from storage.postgres import PostgresRepository

        db = PostgresRepository(PG_URL)
        await db.connect()
        yield db
        await db.close()

    async def test_user_and_lesson_roundtrip(self, repo):
        user = await repo.get_or_create_user(770001, username="pg-smoke-1")
        assert user.id > 0
        fetched = await repo.get_user(user.id)
        assert fetched.tg_id == 770001 and fetched.username == "pg-smoke-1"

        session = await repo.start_lesson(user.id, "Past Simple", "{}")
        msg_id = await repo.add_user_message(
            user.id, "I goed there", lesson_id=session.id, is_correct=False
        )
        assert msg_id > 0
        await repo.add_assistant_message(user.id, "goed -> went")
        history = await repo.get_history(user.id, limit=5)
        assert any(m["role"] == "user" for m in history)
        stats = await repo.get_stats(user.id)
        assert stats.errors >= 1

    async def test_upsert_and_limits(self, repo):
        user = await repo.get_or_create_user(770002, username="pg-smoke-2")
        await repo.add_extra_actions(user.id, 10)
        await repo.add_extra_actions(user.id, 5)
        assert await repo.get_extra_actions(user.id) == 15
        await repo.decrement_extra_actions(user.id, 100)
        assert await repo.get_extra_actions(user.id) == 0

        await repo.increment_llm_usage(user.id, "2026-10-12", inc=2)
        assert await repo.get_llm_usage(user.id, "2026-10-12") == 2

    async def test_subscription_and_coupon(self, repo):
        user = await repo.get_or_create_user(770003, username="pg-smoke-3")
        sub = await repo.grant_subscription(user.id, 7)
        assert sub.id > 0
        assert (await repo.get_subscription(user.id)).is_active

        coupon = await repo.create_coupon(user.id, 20, "2099-01-01T00:00:00+00:00")
        active = await repo.get_active_coupon(user.id)
        assert active.id == coupon.id
        await repo.mark_coupon_used(coupon.id, user.id)
        assert await repo.get_active_coupon(user.id) is None

    async def test_weak_areas_and_leaderboard(self, repo):
        user = await repo.get_or_create_user(770004, username="pg-smoke-4")
        await repo.upsert_weak_area(user.id, "Present Perfect", incorrect_increment=3)
        await repo.upsert_weak_area(user.id, "Present Perfect", correct_increment=1)
        areas = await repo.get_weak_areas(user.id)
        assert any(a.area == "Present Perfect" and a.incorrect_count == 3 for a in areas)

        board = await repo.get_leaderboard()
        assert isinstance(board, list)

    async def test_srs_and_diagnostic(self, repo):
        user = await repo.get_or_create_user(770005, username="pg-smoke-5")
        inserted = await repo.add_srs_word(SRSWord(user_id=user.id, word="brew", translation="заваривать"))
        assert inserted is not None and inserted > 0
        dup = await repo.add_srs_word(SRSWord(user_id=user.id, word="brew", translation="заваривать"))
        assert dup is None
        assert (await repo.get_srs_word(user.id, "brew")).word == "brew"

        diag = await repo.start_diagnostic(user.id, "[]")
        await repo.append_diagnostic_answer(diag.id, "answer-a")
        await repo.append_diagnostic_answer(diag.id, "answer-b")
        loaded = await repo.get_active_diagnostic(user.id)
        answers = json.loads(loaded.answers_json)
        assert answers == ["answer-a", "answer-b"]

    async def test_tutor_sessions_roundtrip(self, repo):
        user = await repo.get_or_create_user(770006, username="pg-smoke-6")
        session = await repo.create_tutor_session(
            user_id=user.id,
            character="chill",
            mode="intro",
            state_json='{"turn_index": 1}',
        )
        assert session.id > 0
        loaded = await repo.get_tutor_session(session.id)
        assert loaded is not None
        assert loaded.user_id == user.id and loaded.guest_token is None
        assert loaded.status == "active"

        active = await repo.get_active_tutor_session(user_id=user.id)
        assert active is not None and active.id == session.id

        await repo.save_tutor_state(session.id, '{"turn_index": 2}', turn_index=2)
        saved = await repo.get_tutor_session(session.id)
        assert json.loads(saved.state_json)["turn_index"] == 2

        guest = await repo.create_tutor_session(guest_token="b" * 32)
        guest_active = await repo.get_active_tutor_session(guest_token="b" * 32)
        assert guest_active is not None and guest_active.id == guest.id

        await repo.finish_tutor_session(session.id)
        assert await repo.get_active_tutor_session(user_id=user.id) is None
        assert (await repo.get_tutor_session(session.id)).status == "finished"