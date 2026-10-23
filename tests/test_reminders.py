"""Ежедневные email-напоминания «Продолжим?» (пункт 4 плана).

Проверяем правила отбора получателей, дедупликацию по ``events``, рендер
письма (ссылки + слова), настройки ``/api/me/notifications``, миграцию v5 и
то, что планировщик выключен по умолчанию.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core import reminders as reminders_module
from core.config import Settings
from core.email import DevEmailSender, EmailSender
from core.reminders import (
    in_reminder_window,
    render_reminder,
    select_recipients,
    send_daily_reminders,
    setup_reminder_scheduler,
)
from storage.migrations import apply_migrations
from storage.repo import LessonNote, SRSWord, UserRow
from storage.sqlite import SQLiteRepository, _SQLiteMigrationDB

NOW = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)


class RecordingSender(EmailSender):
    """Отправитель-шпион: запоминает письма и умеет падать на заданном адресе."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self._fail_for = fail_for or set()

    async def send_verification(self, email: str, link: str) -> bool:
        return True

    async def send_reminder(
        self, email: str, subject: str, text: str, html: str
    ) -> bool:
        if email in self._fail_for:
            raise RuntimeError("SMTP down")
        self.sent.append((email, subject, text))
        return True


@pytest.fixture()
async def repo(tmp_path):
    repository = SQLiteRepository(str(tmp_path / "reminders.db"))
    await repository.connect()
    try:
        yield repository
    finally:
        await repository.close()


async def _email_user(repo: SQLiteRepository, email: str = "student@example.com"):
    return await repo.create_email_user(email, "hash", first_name="Аня")


async def _due_word(repo: SQLiteRepository, user_id: int, word: str = "brew") -> None:
    await repo.add_srs_word(
        SRSWord(
            user_id=user_id,
            word=word,
            translation="заваривать",
            next_review=(NOW - timedelta(hours=1)).isoformat(),
            created_at=NOW.isoformat(),
        )
    )


def _settings(**overrides) -> Settings:
    return Settings(
        jwt_secret="test-secret-reminders",
        database_path=":memory:",
        session_cookie_secure=0,
        webapp_public_url="https://app.example",
        reminder_min_age_days=30,
        **overrides,
    )


# ---------- выбор получателей ----------


async def test_recipient_without_email_is_skipped(repo):
    user = await repo.get_or_create_user(777, username="tg_only")
    await _due_word(repo, user.id)

    recipients = await select_recipients(repo, NOW)
    assert all(item.user.id != user.id for item in recipients)


async def test_recipient_with_disabled_reminders_is_skipped(repo):
    user = await _email_user(repo)
    await _due_word(repo, user.id)
    await repo.set_reminders_enabled(user.id, False)

    recipients = await select_recipients(repo, NOW)
    assert all(item.user.id != user.id for item in recipients)


async def test_recipient_with_lesson_today_is_skipped(repo):
    user = await _email_user(repo)
    await repo.add_lesson_note(
        LessonNote(
            user_id=user.id,
            topic="Past Simple",
            created_at=NOW.isoformat(),
        )
    )

    recipients = await select_recipients(repo, NOW)
    assert all(item.user.id != user.id for item in recipients)


async def test_recipient_with_due_words_is_selected(repo):
    user = await _email_user(repo)
    await _due_word(repo, user.id)

    recipients = await select_recipients(repo, NOW)
    assert [item.user.id for item in recipients] == [user.id]
    assert recipients[0].due_words[0].word == "brew"


async def test_inactive_user_is_skipped(repo):
    user = await _email_user(repo)
    await _due_word(repo, user.id)
    # Нет ни сообщений, ни заметок: активность определяется датой регистрации.
    old = (NOW - timedelta(days=40)).isoformat()
    await repo._conn.execute(
        "UPDATE users SET created_at = ? WHERE id = ?", (old, user.id)
    )
    await repo._conn.commit()

    recipients = await select_recipients(repo, NOW, min_age_days=30)
    assert all(item.user.id != user.id for item in recipients)

    # С более щедрым окном тот же пользователь снова попадает в рассылку.
    recipients = await select_recipients(repo, NOW, min_age_days=60)
    assert [item.user.id for item in recipients] == [user.id]


async def test_streak_counts_yesterday_and_today(repo):
    user = await _email_user(repo)
    await _due_word(repo, user.id)
    for days_ago in (2, 1):
        day = (NOW - timedelta(days=days_ago)).isoformat()
        await repo._conn.execute(
            "INSERT INTO messages (user_id, role, content, created_at) "
            "VALUES (?, 'user', 'hi', ?)",
            (user.id, day),
        )
    await repo._conn.commit()

    recipients = await select_recipients(repo, NOW)
    assert recipients[0].streak == 2


# ---------- дедупликация ----------


async def test_second_run_same_day_sends_nothing(repo):
    first = await _email_user(repo, "one@example.com")
    second = await _email_user(repo, "two@example.com")
    await _due_word(repo, first.id)
    await _due_word(repo, second.id)

    sender = RecordingSender()
    settings = _settings()

    assert await send_daily_reminders(repo, sender, settings, NOW) == 2
    assert len(sender.sent) == 2

    # Второй тик в тот же день (и в следующие 24 ч) — писем нет.
    assert await send_daily_reminders(repo, sender, settings, NOW) == 0
    assert len(sender.sent) == 2

    # События записаны для обоих получателей.
    events = await repo.get_events(first.id, "reminder_sent")
    assert len(events) == 1


async def test_send_error_does_not_break_batch(repo):
    broken = await _email_user(repo, "broken@example.com")
    ok = await _email_user(repo, "ok@example.com")
    await _due_word(repo, broken.id)
    await _due_word(repo, ok.id)

    sender = RecordingSender(fail_for={"broken@example.com"})
    sent = await send_daily_reminders(repo, sender, _settings(), NOW)

    assert sent == 1
    assert [item[0] for item in sender.sent] == ["ok@example.com"]


async def test_dev_mode_logs_recipient_but_does_not_send(repo, caplog):
    user = await _email_user(repo)
    await _due_word(repo, user.id)

    with caplog.at_level(logging.INFO):
        sent = await send_daily_reminders(repo, DevEmailSender(), _settings(), NOW)

    assert sent == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Reminder email (dev mode" in message and user.email in message
        for message in messages
    )


# ---------- рендер письма ----------


def _user_stub() -> UserRow:
    return UserRow(id=1, first_name="Аня", email="anya@example.com")


def test_render_reminder_contains_links_and_words():
    user = _user_stub()
    words = [SRSWord(word="brew", translation="заваривать")]

    email = render_reminder(
        user,
        None,
        words,
        5,
        base_url="https://app.example/",
    )

    assert "Продолжим" in email.subject
    assert "https://app.example/lesson/next" in email.text
    assert "https://app.example/vocab" in email.text
    assert "https://app.example/lesson/next" in email.html
    assert "https://app.example/vocab" in email.html
    assert "brew" in email.text and "заваривать" in email.text
    assert "brew" in email.html
    assert "5" in email.text


def test_render_reminder_without_streak_or_words():
    email = render_reminder(_user_stub(), None, [], 0, base_url="https://app.example")
    assert "Продолжим" in email.text
    assert "Серия" not in email.text
    assert "Слова к повторению" not in email.text


# ---------- настройки /api/me/notifications ----------


def _client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        jwt_secret="test-secret-reminders-api",
        database_path=os.path.join(tmp_path, "reminders_api.db"),
        session_cookie_secure=0,
        **overrides,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str = "user@example.com") -> None:
    response = client.post(
        "/api/auth/register", json={"email": email, "password": "superpass1"}
    )
    assert response.status_code == 200, response.text


def test_notifications_roundtrip(tmp_path):
    with _client(tmp_path) as client:
        _register(client)

        response = client.get("/api/me/notifications")
        assert response.status_code == 200
        assert response.json() == {"email_reminders": True}

        response = client.put(
            "/api/me/notifications", json={"email_reminders": False}
        )
        assert response.status_code == 200
        assert response.json() == {"email_reminders": False}
        assert client.get("/api/me/notifications").json() == {
            "email_reminders": False
        }

        response = client.put(
            "/api/me/notifications", json={"email_reminders": True}
        )
        assert response.json() == {"email_reminders": True}


def test_notifications_require_auth(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/me/notifications").status_code == 401
        assert (
            client.put(
                "/api/me/notifications", json={"email_reminders": True}
            ).status_code
            == 401
        )


# ---------- миграция v5 ----------


async def test_migration_v5_adds_reminders_enabled_on_old_schema(tmp_path):
    db_path = str(tmp_path / "old.db")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            level TEXT,
            unlimited INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            email TEXT,
            password_hash TEXT,
            email_verified_at TEXT
        );
        INSERT INTO users (id, email, created_at)
        VALUES (1, 'old@example.com', '2025-01-01T00:00:00+00:00');
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_migrations VALUES (1, 'users_email_password', '2025-01-01T00:00:00+00:00');
        INSERT INTO schema_migrations VALUES (2, 'user_profiles_minutes_self_level', '2025-01-01T00:00:00+00:00');
        INSERT INTO schema_migrations VALUES (3, 'tutor_sessions', '2025-01-01T00:00:00+00:00');
        INSERT INTO schema_migrations VALUES (4, 'users_email_verified_at', '2025-01-01T00:00:00+00:00');
        """
    )
    await conn.commit()

    applied = await apply_migrations(_SQLiteMigrationDB(conn))
    assert applied == [5]

    cursor = await conn.execute("PRAGMA table_info(users)")
    columns = {row["name"] for row in await cursor.fetchall()}
    assert "reminders_enabled" in columns

    # Существующая строка получает дефолт 1 и не теряется.
    cursor = await conn.execute(
        "SELECT email, reminders_enabled FROM users WHERE id = 1"
    )
    row = await cursor.fetchone()
    assert row["email"] == "old@example.com"
    assert row["reminders_enabled"] == 1

    cursor = await conn.execute("SELECT name FROM schema_migrations WHERE version = 5")
    row = await cursor.fetchone()
    assert row is not None and row["name"] == "users_reminders_enabled"

    # Идемпотентность.
    assert await apply_migrations(_SQLiteMigrationDB(conn)) == []
    await conn.close()


async def test_repository_reads_and_sets_reminders_enabled(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "flag.db"))
    await repo.connect()
    try:
        user = await repo.create_email_user("flag@example.com", "hash")
        assert user.reminders_enabled is True
        assert await repo.get_reminders_enabled(user.id) is True

        await repo.set_reminders_enabled(user.id, False)
        assert await repo.get_reminders_enabled(user.id) is False
        assert (await repo.get_user(user.id)).reminders_enabled is False

        by_email = await repo.get_user_by_email("flag@example.com")
        assert by_email is not None and by_email.reminders_enabled is False
    finally:
        await repo.close()


# ---------- планировщик ----------


async def test_setup_reminder_scheduler_disabled_by_default(repo, monkeypatch):
    monkeypatch.setattr(reminders_module, "_scheduler", None)
    assert setup_reminder_scheduler(repo, DevEmailSender(), _settings()) is None


async def test_setup_reminder_scheduler_creates_single_job(repo, monkeypatch):
    monkeypatch.setattr(reminders_module, "_scheduler", None)
    settings = _settings(reminders_enabled=1, reminder_hour_utc=8)

    scheduler = setup_reminder_scheduler(repo, DevEmailSender(), settings)
    assert scheduler is not None
    jobs = scheduler.get_jobs()
    assert [job.id for job in jobs] == ["email_reminders"]

    # Второй вызов в том же процессе не создаёт дубль.
    assert setup_reminder_scheduler(repo, DevEmailSender(), settings) is None

    monkeypatch.setattr(reminders_module, "_scheduler", None)


def test_reminder_window_is_one_hour():
    assert in_reminder_window(datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc), 8)
    assert not in_reminder_window(
        datetime(2026, 5, 20, 9, 0, tzinfo=timezone.utc), 8
    )
    assert not in_reminder_window(
        datetime(2026, 5, 20, 7, 0, tzinfo=timezone.utc), 8
    )
