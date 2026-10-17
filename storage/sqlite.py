"""Реализация хранилища на aiosqlite.

Таблицы:
- users: профили пользователей Telegram (включая CEFR-уровень, Фаза 3)
- messages: история диалога + результаты проверки (is_correct, issues_json)
  Та же таблица даёт и историю для промпта, и статистику практики.
- lesson_sessions: состояние структурированных уроков
- diagnostic_sessions: состояние диагностики уровня (Фаза 3)
- user_profiles: память пользователя (Фаза 4): цели, интересы, слабые места
- lesson_notes: итоги уроков (Фаза 5): слова, грамматика, ошибки, рекомендация
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiosqlite

from .schema import SQLITE_DDL

from .repo import (
    DiagnosticSession,
    KaspiOrder,
    LeaderboardRow,
    LessonNote,
    LessonPlanRow,
    LessonSession,
    MiniLessonSession,
    Payment,
    Repository,
    SRSWord,
    Stats,
    Subscription,
    TopicProposal,
    UserProfile,
    UserRow,
    WeakArea,
    WheelCoupon,
)

_SCHEMA = SQLITE_DDL


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository(Repository):
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        parent = Path(self._db_path).parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        """Идемпотентные миграции для БД, созданных до появления новых колонок."""
        cursor = await self._conn.execute("PRAGMA table_info(users)")
        rows = await cursor.fetchall()
        columns = {row["name"] for row in rows}
        if "level" not in columns:
            await self._conn.execute("ALTER TABLE users ADD COLUMN level TEXT")
        if "unlimited" not in columns:
            await self._conn.execute("ALTER TABLE users ADD COLUMN unlimited INTEGER NOT NULL DEFAULT 0")

        cursor = await self._conn.execute("PRAGMA table_info(messages)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "lesson_id" not in columns:
            await self._conn.execute("ALTER TABLE messages ADD COLUMN lesson_id INTEGER")

        cursor = await self._conn.execute("PRAGMA table_info(lesson_sessions)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "mode" not in columns:
            await self._conn.execute(
                "ALTER TABLE lesson_sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'"
            )
        if "score_json" not in columns:
            await self._conn.execute("ALTER TABLE lesson_sessions ADD COLUMN score_json TEXT")
        if "deck_preset" not in columns:
            await self._conn.execute("ALTER TABLE lesson_sessions ADD COLUMN deck_preset TEXT")

        cursor = await self._conn.execute("PRAGMA table_info(user_profiles)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "character" not in columns:
            await self._conn.execute("ALTER TABLE user_profiles ADD COLUMN character TEXT NOT NULL DEFAULT ''")

        cursor = await self._conn.execute("PRAGMA table_info(user_balances)")
        bal_cols = {row["name"] for row in await cursor.fetchall()}
        if "dry_streak" not in bal_cols:
            await self._conn.execute(
                "ALTER TABLE user_balances ADD COLUMN dry_streak INTEGER NOT NULL DEFAULT 0"
            )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Хранилище не подключено: вызовите connect()")
        return self._conn

    async def get_or_create_user(
        self,
        tg_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> UserRow:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO users (tg_id, username, first_name, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET "
            "username = excluded.username, first_name = excluded.first_name",
            (tg_id, username, first_name, _now()),
        )
        await conn.commit()
        cursor = await conn.execute(
            "SELECT id, tg_id, username, first_name, level, unlimited FROM users WHERE tg_id = ?",
            (tg_id,),
        )
        row = await cursor.fetchone()
        return UserRow(
            id=row["id"],
            tg_id=row["tg_id"],
            username=row["username"],
            first_name=row["first_name"],
            level=row["level"],
            is_unlimited=bool(row["unlimited"]),
        )

    async def get_user(self, user_id: int) -> UserRow | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, tg_id, username, first_name, level, unlimited FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return UserRow(
            id=row["id"],
            tg_id=row["tg_id"],
            username=row["username"],
            first_name=row["first_name"],
            level=row["level"],
            is_unlimited=bool(row["unlimited"]),
        )

    async def set_level(self, user_id: int, level: str) -> None:
        conn = self._require_conn()
        await conn.execute("UPDATE users SET level = ? WHERE id = ?", (level, user_id))
        await conn.commit()

    async def get_level(self, user_id: int) -> str | None:
        conn = self._require_conn()
        cursor = await conn.execute("SELECT level FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return row["level"] if row else None

    # ---------- квота LLM ----------

    async def get_unlimited_status(self, user_id: int) -> bool:
        conn = self._require_conn()
        cursor = await conn.execute("SELECT unlimited FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return bool(row["unlimited"]) if row else False

    async def set_unlimited_status(self, user_id: int, value: bool) -> None:
        conn = self._require_conn()
        await conn.execute("UPDATE users SET unlimited = ? WHERE id = ?", (1 if value else 0, user_id))
        await conn.commit()

    async def get_llm_usage(self, user_id: int, day: str) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT count FROM llm_usage WHERE user_id = ? AND day = ?",
            (user_id, day),
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0

    async def increment_llm_usage(self, user_id: int, day: str, inc: int = 1) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO llm_usage (user_id, day, count) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, day) DO UPDATE SET count = count + excluded.count",
            (user_id, day, inc),
        )
        await conn.commit()

    # ---------- бонусные LLM-действия (колесо) ----------

    async def get_extra_actions(self, user_id: int) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT extra_actions FROM user_balances WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["extra_actions"] if row else 0

    async def _set_extra_actions(self, user_id: int, amount: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO user_balances (user_id, extra_actions) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET extra_actions = excluded.extra_actions",
            (user_id, max(0, amount)),
        )
        await conn.commit()

    async def add_extra_actions(self, user_id: int, amount: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO user_balances (user_id, extra_actions) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET extra_actions = extra_actions + excluded.extra_actions",
            (user_id, max(0, amount)),
        )
        await conn.commit()

    async def decrement_extra_actions(self, user_id: int, amount: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE user_balances SET extra_actions = MAX(0, extra_actions - ?) WHERE user_id = ?",
            (amount, user_id),
        )
        await conn.commit()

    # ---------- колесо удачи ----------

    async def get_last_spin_date(self, user_id: int) -> str | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT date FROM wheel_spins WHERE user_id = ? ORDER BY date DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["date"] if row else None

    async def save_spin(self, user_id: int, date: str) -> bool:
        conn = self._require_conn()
        cursor = await conn.execute(
            "INSERT INTO wheel_spins (user_id, date) VALUES (?, ?) "
            "ON CONFLICT(user_id, date) DO NOTHING",
            (user_id, date),
        )
        await conn.commit()
        return cursor.rowcount == 1

    async def get_dry_streak(self, user_id: int) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT dry_streak FROM user_balances WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["dry_streak"] if row else 0

    async def set_dry_streak(self, user_id: int, streak: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO user_balances (user_id, dry_streak) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET dry_streak = excluded.dry_streak",
            (user_id, max(0, streak)),
        )
        await conn.commit()

    async def create_coupon(self, user_id: int, discount_pct: int, expires_at: str) -> WheelCoupon:
        if not 0 <= discount_pct <= 100:
            raise ValueError(f"discount_pct должен быть в диапазоне 0..100, получено {discount_pct}")
        conn = self._require_conn()
        now = _now()
        cursor = await conn.execute(
            "INSERT INTO wheel_coupons (user_id, discount_pct, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (user_id, discount_pct, expires_at, now),
        )
        await conn.commit()
        return WheelCoupon(
            id=cursor.lastrowid,
            user_id=user_id,
            discount_pct=discount_pct,
            expires_at=expires_at,
            used=False,
            created_at=now,
        )

    async def get_active_coupon(self, user_id: int) -> WheelCoupon | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, discount_pct, expires_at, used, created_at "
            "FROM wheel_coupons WHERE user_id = ? AND used = 0 AND expires_at > ? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, _now()),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return WheelCoupon(
            id=row["id"],
            user_id=row["user_id"],
            discount_pct=row["discount_pct"],
            expires_at=row["expires_at"],
            used=bool(row["used"]),
            created_at=row["created_at"],
        )

    async def mark_coupon_used(self, coupon_id: int, user_id: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE wheel_coupons SET used = 1 WHERE id = ? AND user_id = ?",
            (coupon_id, user_id),
        )
        await conn.commit()

    # ---------- подписки ----------

    async def grant_subscription(self, user_id: int, plan_days: int) -> Subscription:
        now = datetime.now(timezone.utc)
        existing = await self.get_subscription(user_id)
        if existing is not None and existing.is_active:
            try:
                base = datetime.fromisoformat(existing.expires_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                base = now
        else:
            base = now
        expires_at = (base + timedelta(days=plan_days)).isoformat()
        granted_at = now.isoformat()
        conn = self._require_conn()
        cursor = await conn.execute(
            "INSERT INTO subscriptions (user_id, plan_days, granted_at, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, plan_days, granted_at, expires_at),
        )
        await conn.commit()
        return Subscription(
            id=cursor.lastrowid,
            user_id=user_id,
            plan_days=plan_days,
            granted_at=granted_at,
            expires_at=expires_at,
        )

    async def get_subscription(self, user_id: int) -> Subscription | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, plan_days, granted_at, expires_at "
            "FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Subscription(
            id=row["id"],
            user_id=row["user_id"],
            plan_days=row["plan_days"],
            granted_at=row["granted_at"],
            expires_at=row["expires_at"],
        )

    # ---------- платежи ----------

    async def create_payment(
        self,
        user_id: int,
        telegram_payment_id: str,
        amount: int,
        currency: str,
        plan_days: int,
        discount_pct: int,
    ) -> Payment:
        conn = self._require_conn()
        now = _now()
        await conn.execute(
            "INSERT OR IGNORE INTO payments "
            "(telegram_payment_id, user_id, amount, currency, plan_days, discount_pct, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (telegram_payment_id, user_id, amount, currency, plan_days, discount_pct, now),
        )
        await conn.commit()
        return await self.find_payment(telegram_payment_id)

    async def find_payment(self, telegram_payment_id: str) -> Payment | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, telegram_payment_id, user_id, amount, currency, plan_days, discount_pct, created_at "
            "FROM payments WHERE telegram_payment_id = ?",
            (telegram_payment_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Payment(
            id=row["id"],
            telegram_payment_id=row["telegram_payment_id"],
            user_id=row["user_id"],
            amount=row["amount"],
            currency=row["currency"],
            plan_days=row["plan_days"],
            discount_pct=row["discount_pct"],
            created_at=row["created_at"],
        )

    # ---------- Kaspi QR оплата ----------

    def _order_from_row(self, row) -> KaspiOrder:
        return KaspiOrder(
            id=row["id"],
            user_id=row["user_id"],
            plan_days=row["plan_days"],
            amount=row["amount"],
            discount_pct=row["discount_pct"],
            coupon_id=row["coupon_id"],
            order_code=row["order_code"],
            status=row["status"],
            photo_file_id=row["photo_file_id"],
            created_at=row["created_at"],
            confirmed_at=row["confirmed_at"],
        )

    _ORDER_COLUMNS = "id, user_id, plan_days, amount, discount_pct, coupon_id, order_code, status, photo_file_id, created_at, confirmed_at"

    async def create_order(
        self,
        user_id: int,
        plan_days: int,
        amount: int,
        discount_pct: int,
        coupon_id: int,
        order_code: str,
    ) -> KaspiOrder:
        conn = self._require_conn()
        cursor = await conn.execute(
            "INSERT INTO kaspi_orders (user_id, plan_days, amount, discount_pct, coupon_id, order_code, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, plan_days, amount, discount_pct, coupon_id, order_code, _now()),
        )
        await conn.commit()
        return KaspiOrder(
            id=cursor.lastrowid,
            user_id=user_id,
            plan_days=plan_days,
            amount=amount,
            discount_pct=discount_pct,
            coupon_id=coupon_id,
            order_code=order_code,
            status=KaspiOrder.STATUS_PENDING,
            created_at=_now(),
        )

    async def get_pending_order(self, user_id: int) -> KaspiOrder | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            f"SELECT {self._ORDER_COLUMNS} FROM kaspi_orders "
            "WHERE user_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (user_id, KaspiOrder.STATUS_PENDING),
        )
        row = await cursor.fetchone()
        return self._order_from_row(row) if row else None

    async def get_order(self, order_id: int) -> KaspiOrder | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            f"SELECT {self._ORDER_COLUMNS} FROM kaspi_orders WHERE id = ?",
            (order_id,),
        )
        row = await cursor.fetchone()
        return self._order_from_row(row) if row else None

    async def attach_photo(self, order_id: int, photo_file_id: str) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE kaspi_orders SET photo_file_id = ? WHERE id = ?",
            (photo_file_id, order_id),
        )
        await conn.commit()

    async def approve_order(self, order_id: int) -> KaspiOrder | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "UPDATE kaspi_orders SET status = ?, confirmed_at = ? "
            "WHERE id = ? AND status = ?",
            (KaspiOrder.STATUS_APPROVED, _now(), order_id, KaspiOrder.STATUS_PENDING),
        )
        await conn.commit()
        if cursor.rowcount == 0:
            return None
        return await self.get_order(order_id)

    async def cancel_order(self, order_id: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE kaspi_orders SET status = ? WHERE id = ? AND status = ?",
            (KaspiOrder.STATUS_CANCELLED, order_id, KaspiOrder.STATUS_PENDING),
        )
        await conn.commit()

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
        conn = self._require_conn()
        try:
            await conn.execute(
                "UPDATE kaspi_orders SET status = ? WHERE user_id = ? AND status = ?",
                (KaspiOrder.STATUS_CANCELLED, user_id, KaspiOrder.STATUS_PENDING),
            )
            cursor = await conn.execute(
                "INSERT INTO kaspi_orders "
                "(user_id, plan_days, amount, discount_pct, coupon_id, order_code, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, plan_days, amount, discount_pct, coupon_id, order_code, _now()),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        return KaspiOrder(
            id=cursor.lastrowid,
            user_id=user_id,
            plan_days=plan_days,
            amount=amount,
            discount_pct=discount_pct,
            coupon_id=coupon_id,
            order_code=order_code,
            status=KaspiOrder.STATUS_PENDING,
            created_at=_now(),
        )

    async def is_order_code_taken(self, order_code: str) -> bool:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT 1 FROM kaspi_orders WHERE order_code = ? AND status != ? LIMIT 1",
            (order_code, KaspiOrder.STATUS_CANCELLED),
        )
        return await cursor.fetchone() is not None

    # ---------- аналитика (события) ----------

    async def append_event(self, user_id: int, event_type: str, payload=None) -> None:
        conn = self._require_conn()
        payload_text = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
        await conn.execute(
            "INSERT INTO events (user_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (user_id, event_type, payload_text, _now()),
        )
        await conn.commit()

    async def count_events(self, event_type: str, since_date: str) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM events WHERE event_type = ? AND created_at >= ?",
            (event_type, since_date),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ---------- аналитика ----------

    async def get_events(self, user_id: int, event_type: str, since_date: str = "") -> list[dict]:
        conn = self._require_conn()
        if since_date:
            cursor = await conn.execute(
                "SELECT id, user_id, event_type, payload, created_at FROM events "
                "WHERE user_id = ? AND event_type = ? AND created_at >= ? ORDER BY id",
                (user_id, event_type, since_date),
            )
        else:
            cursor = await conn.execute(
                "SELECT id, user_id, event_type, payload, created_at FROM events "
                "WHERE user_id = ? AND event_type = ? ORDER BY id",
                (user_id, event_type),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def count_event_users(self, event_type: str, since_date: str, until_date: str = "") -> int:
        conn = self._require_conn()
        if until_date:
            cursor = await conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS cnt FROM events "
                "WHERE event_type = ? AND created_at >= ? AND created_at < ?",
                (event_type, since_date, until_date),
            )
        else:
            cursor = await conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS cnt FROM events WHERE event_type = ? AND created_at >= ?",
                (event_type, since_date),
            )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def count_active_users(self, since_date: str, until_date: str = "") -> int:
        """Активность = любое событие либо реплика за период."""
        conn = self._require_conn()
        until_clause = "AND created_at < ?" if until_date else ""
        params_e = (since_date, until_date) if until_date else (since_date,)
        cursor = await conn.execute(
            f"SELECT COUNT(DISTINCT user_id) AS cnt FROM events WHERE created_at >= ? {until_clause}",
            params_e,
        )
        from_events = (await cursor.fetchone())["cnt"] if True else 0
        params_m = (since_date, until_date) if until_date else (since_date,)
        cursor = await conn.execute(
            f"SELECT COUNT(DISTINCT user_id) AS cnt FROM messages "
            f"WHERE role = 'user' AND created_at >= ? {until_clause}",
            params_m,
        )
        from_messages = (await cursor.fetchone())["cnt"] if True else 0
        return max(from_events, from_messages)

    async def count_users(self) -> int:
        conn = self._require_conn()
        cursor = await conn.execute("SELECT COUNT(*) AS cnt FROM users")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def count_users_created_between(self, start_date: str, end_date: str) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE created_at >= ? AND created_at < ?",
            (start_date, end_date),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def list_users_recent(self, limit: int = 20) -> list[UserRow]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, tg_id, username, first_name, level, unlimited FROM users "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        rows = await cursor.fetchall()
        return [
            UserRow(
                id=row["id"],
                tg_id=row["tg_id"],
                username=row["username"],
                first_name=row["first_name"],
                level=row["level"],
                is_unlimited=bool(row["unlimited"]),
            )
            for row in rows
        ]

    async def get_diagnostic_sessions(self, user_id: int) -> list[DiagnosticSession]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, questions_json, answers_json, status, created_at, updated_at "
            "FROM diagnostic_sessions WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [
            DiagnosticSession(
                id=row["id"],
                user_id=row["user_id"],
                questions_json=row["questions_json"],
                answers_json=row["answers_json"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    # ---------- админ-статистика ----------

    async def count_spins_today(self, date: str) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM wheel_spins WHERE date = ?",
            (date,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def count_pending_orders(self) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM kaspi_orders WHERE status = ?",
            (KaspiOrder.STATUS_PENDING,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def sum_revenue(self) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM kaspi_orders WHERE status = ?",
            (KaspiOrder.STATUS_APPROVED,),
        )
        row = await cursor.fetchone()
        return row["total"] if row else 0

    async def count_active_subscriptions(self) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM subscriptions WHERE expires_at > ?",
            (_now(),),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def get_profile(self, user_id: int) -> UserProfile | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT user_id, goal, interests, weak_areas, preferred_format, notes, character, updated_at "
            "FROM user_profiles WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return UserProfile(
            user_id=row["user_id"],
            goal=row["goal"],
            interests=row["interests"],
            weak_areas=row["weak_areas"],
            preferred_format=row["preferred_format"],
            notes=row["notes"],
            character=row["character"],
            updated_at=row["updated_at"],
        )

    async def save_profile(self, profile: UserProfile) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO user_profiles "
            "(user_id, goal, interests, weak_areas, preferred_format, notes, character, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "goal = excluded.goal, interests = excluded.interests, weak_areas = excluded.weak_areas, "
            "preferred_format = excluded.preferred_format, notes = excluded.notes, "
            "character = excluded.character, "
            "updated_at = excluded.updated_at",
            (
                profile.user_id,
                profile.goal,
                profile.interests,
                profile.weak_areas,
                profile.preferred_format,
                profile.notes,
                profile.character,
                profile.updated_at,
            ),
        )
        await conn.commit()

    async def add_user_message(
        self,
        user_id: int,
        content: str,
        *,
        is_correct: bool | None = None,
        issues_json: str = "",
        corrected_text: str = "",
        lesson_id: int | None = None,
    ) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "INSERT INTO messages (user_id, role, content, is_correct, issues_json, corrected_text, lesson_id, created_at) "
            "VALUES (?, 'user', ?, ?, ?, ?, ?, ?)",
            (user_id, content, is_correct, issues_json, corrected_text, lesson_id, _now()),
        )
        await conn.commit()
        return cursor.lastrowid

    async def add_assistant_message(self, user_id: int, content: str) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (user_id, content, _now()),
        )
        await conn.commit()

    async def get_history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def get_user_turns(self, user_id: int, limit: int = 500) -> list[dict]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, content, is_correct, created_at FROM messages "
            "WHERE user_id = ? AND role = 'user' ORDER BY id ASC LIMIT ?",
            (user_id, int(limit)),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "content": row["content"],
                "is_correct": row["is_correct"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def get_lesson_messages(self, lesson_id: int) -> list[dict]:
        """Ответы пользователя во время конкретного урока — для итоговой заметки."""
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT content, is_correct, issues_json, corrected_text FROM messages "
            "WHERE lesson_id = ? AND role = 'user' ORDER BY id ASC",
            (lesson_id,),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            raw = row["is_correct"]
            if raw is None:
                is_correct = None
            elif raw:
                is_correct = True
            else:
                is_correct = False
            result.append({
                "content": row["content"],
                "is_correct": is_correct,
                "issues_json": row["issues_json"] or "",
                "corrected_text": row["corrected_text"] or "",
            })
        return result

    async def get_stats(self, user_id: int) -> Stats:
        conn = self._require_conn()

        cursor = await conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct, "
            "COALESCE(SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END), 0) AS errors "
            "FROM messages WHERE user_id = ? AND role = 'user' AND is_correct IS NOT NULL",
            (user_id,),
        )
        totals = await cursor.fetchone()

        cursor = await conn.execute(
            "SELECT issues_json FROM messages "
            "WHERE user_id = ? AND role = 'user' AND issues_json IS NOT NULL AND issues_json != '' "
            "ORDER BY id DESC LIMIT 200",
            (user_id,),
        )
        rows = await cursor.fetchall()

        categories: dict[str, int] = {}
        for row in rows:
            try:
                issues = json.loads(row["issues_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(issues, list):
                continue
            for issue in issues:
                if isinstance(issue, dict) and issue.get("category"):
                    cat = str(issue["category"])
                    categories[cat] = categories.get(cat, 0) + 1

        top = sorted(categories.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return Stats(
            total_turns=totals["total"] if totals else 0,
            correct=totals["correct"] if totals else 0,
            errors=totals["errors"] if totals else 0,
            top_categories=top,
        )

    async def get_last_correction(self, user_id: int) -> dict | None:
        """Последний разбор фразы пользователя для кнопки «Показать ошибку»."""
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT is_correct, corrected_text, issues_json FROM messages "
            "WHERE user_id = ? AND role = 'user' AND is_correct = 0 "
            "AND corrected_text IS NOT NULL AND corrected_text != '' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "is_correct": bool(row["is_correct"]),
            "corrected_text": row["corrected_text"],
            "issues_json": row["issues_json"] or "",
        }

    async def get_user_message(self, user_id: int, message_id: int) -> dict | None:
        """Разбор конкретной фразы по её id — кнопка «Показать ошибку» привязана к сообщению."""
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT is_correct, corrected_text, issues_json FROM messages "
            "WHERE id = ? AND user_id = ? AND role = 'user'",
            (message_id, user_id),
        )
        row = await cursor.fetchone()
        if row is None or row["is_correct"] != 0:
            return None
        return {
            "is_correct": bool(row["is_correct"]),
            "corrected_text": row["corrected_text"] or "",
            "issues_json": row["issues_json"] or "",
        }

    # ---------- уроки ----------

    @staticmethod
    def _row_to_lesson(row) -> LessonSession:
        return LessonSession(
            id=row["id"],
            user_id=row["user_id"],
            topic=row["topic"],
            step=row["step"],
            task_index=row["task_index"],
            content_json=row["content_json"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_mini_lesson(row) -> MiniLessonSession:
        return MiniLessonSession(
            id=row["id"],
            user_id=row["user_id"],
            topic=row["topic"],
            content_json=row["content_json"],
            preset=row["deck_preset"],
            score_json=row["score_json"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def start_mini_lesson(
        self, user_id: int, topic: str, deck_json: str, preset: str
    ) -> MiniLessonSession:
        conn = self._require_conn()
        now = _now()
        try:
            await conn.execute(
                "UPDATE lesson_sessions SET status = 'aborted', updated_at = ? "
                "WHERE user_id = ? AND mode = 'miniapp' AND status = 'active'",
                (now, user_id),
            )
            cursor = await conn.execute(
                "INSERT INTO lesson_sessions "
                "(user_id, topic, content_json, mode, deck_preset, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'miniapp', ?, 'active', ?, ?)",
                (user_id, topic, deck_json, preset, now, now),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        return MiniLessonSession(
            id=cursor.lastrowid,
            user_id=user_id,
            topic=topic,
            content_json=deck_json,
            preset=preset,
            score_json=None,
            status="active",
            created_at=now,
            updated_at=now,
        )

    async def get_active_mini_lesson(self, user_id: int) -> MiniLessonSession | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, topic, content_json, deck_preset, score_json, status, created_at, updated_at "
            "FROM lesson_sessions WHERE user_id = ? AND mode = 'miniapp' AND status = 'active' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_mini_lesson(row) if row else None

    async def save_mini_answers(self, session_id: int, score_json: str) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE lesson_sessions SET score_json = ?, updated_at = ? WHERE id = ? AND mode = 'miniapp'",
            (score_json, _now(), session_id),
        )
        await conn.commit()

    async def finish_mini_lesson(self, session_id: int, score_json: str | None = None) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE lesson_sessions SET status = 'finished', updated_at = ?, "
            "score_json = COALESCE(?, score_json) WHERE id = ? AND mode = 'miniapp'",
            (_now(), score_json, session_id),
        )
        await conn.commit()

    async def save_audio_answer(
        self,
        session_id: int,
        word: str,
        audio_file: str,
        transcript: str,
        rating: int | None,
    ) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO audio_answers (session_id, word, audio_file, transcript, rating) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, word, audio_file, transcript, rating),
        )
        await conn.commit()

    async def start_lesson(self, user_id: int, topic: str, content_json: str) -> LessonSession:
        conn = self._require_conn()
        now = _now()
        # Атомарно закрываем старые активные уроки, чтобы не копились «зависшие» сессии.
        await conn.execute(
            "UPDATE lesson_sessions SET status = 'aborted', updated_at = ? WHERE user_id = ? AND status = 'active'",
            (now, user_id),
        )
        cursor = await conn.execute(
            "INSERT INTO lesson_sessions (user_id, topic, content_json, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, ?)",
            (user_id, topic, content_json, now, now),
        )
        await conn.commit()
        session_id = cursor.lastrowid
        return LessonSession(
            id=session_id,
            user_id=user_id,
            topic=topic,
            step=0,
            task_index=0,
            content_json=content_json,
            status="active",
            created_at=now,
            updated_at=now,
        )

    async def get_active_lesson(self, user_id: int) -> LessonSession | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT * FROM lesson_sessions WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_lesson(row) if row else None

    async def update_lesson(self, session_id: int, *, step: int | None = None, task_index: int | None = None) -> None:
        conn = self._require_conn()
        updates: list[str] = []
        params: list[object] = []
        if step is not None:
            updates.append("step = ?")
            params.append(step)
        if task_index is not None:
            updates.append("task_index = ?")
            params.append(task_index)
        if not updates:
            return
        updates.append("updated_at = ?")
        params.append(_now())
        params.append(session_id)
        await conn.execute(f"UPDATE lesson_sessions SET {', '.join(updates)} WHERE id = ?", params)
        await conn.commit()

    async def finish_lesson(self, session_id: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE lesson_sessions SET status = 'finished', updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await conn.commit()

    async def finish_active_lessons(self, user_id: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE lesson_sessions SET status = 'finished', updated_at = ? WHERE user_id = ? AND status = 'active'",
            (_now(), user_id),
        )
        await conn.commit()

    async def abort_active_lessons(self, user_id: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE lesson_sessions SET status = 'aborted', updated_at = ? WHERE user_id = ? AND status = 'active'",
            (_now(), user_id),
        )
        await conn.commit()

    async def add_lesson_note(self, note: LessonNote) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "INSERT INTO lesson_notes "
            "(user_id, lesson_id, topic, vocabulary, grammar, speaking, mistakes, recommendation, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                note.user_id,
                note.lesson_id,
                note.topic,
                note.vocabulary,
                note.grammar,
                note.speaking,
                note.mistakes,
                note.recommendation,
                note.created_at or _now(),
            ),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_lesson_notes(self, user_id: int, limit: int = 10) -> list[LessonNote]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, lesson_id, topic, vocabulary, grammar, speaking, mistakes, recommendation, created_at "
            "FROM lesson_notes WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            LessonNote(
                id=row["id"],
                user_id=row["user_id"],
                lesson_id=row["lesson_id"],
                topic=row["topic"],
                vocabulary=row["vocabulary"],
                grammar=row["grammar"],
                speaking=row["speaking"],
                mistakes=row["mistakes"],
                recommendation=row["recommendation"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # ---------- план уроков / счётчик завершённых уроков ----------

    async def get_lesson_plan(self, user_id: int) -> LessonPlanRow | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT user_id, plan_json, horizon, based_on_lessons, generated_at "
            "FROM user_lesson_plans WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return LessonPlanRow(
            user_id=row["user_id"],
            plan_json=row["plan_json"],
            horizon=row["horizon"],
            based_on_lessons=row["based_on_lessons"],
            generated_at=row["generated_at"],
        )

    async def save_lesson_plan(self, plan: LessonPlanRow) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO user_lesson_plans "
            "(user_id, plan_json, horizon, based_on_lessons, generated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "plan_json = excluded.plan_json, horizon = excluded.horizon, "
            "based_on_lessons = excluded.based_on_lessons, "
            "generated_at = excluded.generated_at",
            (
                plan.user_id,
                plan.plan_json,
                plan.horizon,
                plan.based_on_lessons,
                plan.generated_at,
            ),
        )
        await conn.commit()

    async def count_finished_lessons(self, user_id: int) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM lesson_sessions "
            "WHERE user_id = ? AND status = 'finished'",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ---------- диагностика уровня (Фаза 3) ----------

    @staticmethod
    def _row_to_diagnostic(row) -> DiagnosticSession:
        return DiagnosticSession(
            id=row["id"],
            user_id=row["user_id"],
            questions_json=row["questions_json"],
            answers_json=row["answers_json"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def start_diagnostic(self, user_id: int, questions_json: str) -> DiagnosticSession:
        conn = self._require_conn()
        now = _now()
        # Атомарно закрываем старые активные диагностики, чтобы не копились «зависшие» сессии.
        await conn.execute(
            "UPDATE diagnostic_sessions SET status = 'aborted', updated_at = ? "
            "WHERE user_id = ? AND status = 'active'",
            (now, user_id),
        )
        cursor = await conn.execute(
            "INSERT INTO diagnostic_sessions (user_id, questions_json, status, created_at, updated_at) "
            "VALUES (?, ?, 'active', ?, ?)",
            (user_id, questions_json, now, now),
        )
        await conn.commit()
        return DiagnosticSession(
            id=cursor.lastrowid,
            user_id=user_id,
            questions_json=questions_json,
            answers_json="[]",
            status="active",
            created_at=now,
            updated_at=now,
        )

    async def get_active_diagnostic(self, user_id: int) -> DiagnosticSession | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT * FROM diagnostic_sessions WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_diagnostic(row) if row else None

    async def append_diagnostic_answer(self, session_id: int, answer: str) -> None:
        # Атомарное добавление ответа одним стейтментом: JSON1 доступен в SQLite, но
        # json_array_append отсутствует — используем json_insert с путём '$[#]'.
        conn = self._require_conn()
        await conn.execute(
            "UPDATE diagnostic_sessions SET "
            "answers_json = CASE "
            "  WHEN json_valid(answers_json) AND json_type(answers_json) = 'array' "
            "  THEN json_insert(answers_json, '$[#]', ?) "
            "  ELSE json_array(?) END, "
            "updated_at = ? WHERE id = ?",
            (answer, answer, _now(), session_id),
        )
        await conn.commit()

    async def finish_diagnostic(self, session_id: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE diagnostic_sessions SET status = 'finished', updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await conn.commit()

    async def abort_active_diagnostics(self, user_id: int) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE diagnostic_sessions SET status = 'aborted', updated_at = ? "
            "WHERE user_id = ? AND status = 'active'",
            (_now(), user_id),
        )
        await conn.commit()

    # ---------- предложения тем (Фаза 2) ----------

    async def save_topic_proposals(self, user_id: int, proposals: list[TopicProposal]) -> None:
        # Единый неявный transaction (стиль sqlite.py): первый DML открывает BEGIN, commit в конце,
        # rollback в except — без хрупкого явного BEGIN.
        conn = self._require_conn()
        try:
            await conn.execute("DELETE FROM topic_proposals WHERE user_id = ?", (user_id,))
            for p in proposals:
                await conn.execute(
                    "INSERT INTO topic_proposals (user_id, topic, description, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, p.topic, p.description, p.created_at or _now()),
                )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def get_topic_proposal(self, proposal_id: int) -> TopicProposal | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, topic, description, created_at FROM topic_proposals WHERE id = ?",
            (proposal_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return TopicProposal(
            id=row["id"],
            user_id=row["user_id"],
            topic=row["topic"],
            description=row["description"],
            created_at=row["created_at"],
        )

    async def get_topic_proposals(self, user_id: int) -> list[TopicProposal]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, topic, description, created_at FROM topic_proposals WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
        return [
            TopicProposal(
                id=row["id"],
                user_id=row["user_id"],
                topic=row["topic"],
                description=row["description"],
                created_at=row["created_at"],
            )
            for row in await cursor.fetchall()
        ]

    async def delete_topic_proposals(self, user_id: int) -> None:
        conn = self._require_conn()
        await conn.execute("DELETE FROM topic_proposals WHERE user_id = ?", (user_id,))
        await conn.commit()

    async def get_practice_dates(self, user_id: int, limit: int = 50) -> list[str]:
        """Возвращает уникальные даты (YYYY-MM-DD) последних практик пользователя."""
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT DISTINCT substr(created_at, 1, 10) AS day "
            "FROM messages WHERE user_id = ? AND role = 'user' "
            "ORDER BY day DESC LIMIT ?",
            (user_id, limit),
        )
        return [row["day"] for row in await cursor.fetchall()]

    async def get_last_activity(self, user_id: int) -> str | None:
        """Последняя активность (ISO) по сообщениям пользователя и заметкам уроков."""
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT created_at FROM messages WHERE user_id = ? AND role = 'user' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        best = row["created_at"] if row else None
        cursor = await conn.execute(
            "SELECT created_at FROM lesson_notes WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        note = row["created_at"] if row else None
        if best is None:
            return note
        if note is None:
            return best
        return best if best >= note else note

    # ---------- weak areas (Фаза 13) ----------

    async def get_weak_areas(self, user_id: int) -> list[WeakArea]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, user_id, area, incorrect_count, correct_count, last_seen, created_at "
            "FROM user_weak_areas WHERE user_id = ? "
            "ORDER BY (incorrect_count * 2.0 + "
            "CASE WHEN last_seen != '' THEN "
            "  MAX(0, 14 - CAST((julianday('now') - julianday(last_seen)) AS INTEGER)) / 14.0 "
            "ELSE 0 END) DESC",
            (user_id,),
        )
        return [
            WeakArea(
                id=row["id"],
                user_id=row["user_id"],
                area=row["area"],
                incorrect_count=row["incorrect_count"],
                correct_count=row["correct_count"],
                last_seen=row["last_seen"],
                created_at=row["created_at"],
            )
            for row in await cursor.fetchall()
        ]

    async def upsert_weak_area(
        self,
        user_id: int,
        area: str,
        incorrect_increment: int = 0,
        correct_increment: int = 0,
        last_seen: str = "",
    ) -> None:
        conn = self._require_conn()
        now = last_seen or ""
        await conn.execute(
            """
            INSERT INTO user_weak_areas (user_id, area, incorrect_count, correct_count, last_seen, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, area) DO UPDATE SET
                incorrect_count = incorrect_count + excluded.incorrect_count,
                correct_count = correct_count + excluded.correct_count,
                last_seen = CASE WHEN excluded.last_seen != '' THEN excluded.last_seen ELSE user_weak_areas.last_seen END
            """,
            (user_id, area, incorrect_increment, correct_increment, now, now),
        )
        await conn.commit()

    async def delete_weak_area(self, user_id: int, area: str) -> None:
        conn = self._require_conn()
        await conn.execute(
            "DELETE FROM user_weak_areas WHERE user_id = ? AND area = ?",
            (user_id, area),
        )
        await conn.commit()

    # ---------- SRS vocabulary (Фаза 13) ----------

    async def add_srs_word(self, word: SRSWord) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "INSERT OR IGNORE INTO user_vocabulary "
            "(user_id, word, translation, example, lesson_id, next_review, interval_days, ease_factor, correct_count, last_reviewed, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (word.user_id, word.word, word.translation, word.example,
             word.lesson_id, word.next_review, word.interval_days,
             word.ease_factor, word.correct_count, word.last_reviewed, word.created_at),
        )
        await conn.commit()
        if cursor.rowcount == 1:
            return cursor.lastrowid
        return None

    async def get_srs_word(self, user_id: int, word: str) -> SRSWord | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT * FROM user_vocabulary WHERE user_id = ? AND word = ?",
            (user_id, word),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_srs_word(row)

    async def get_srs_word_by_id(self, word_id: int) -> SRSWord | None:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT * FROM user_vocabulary WHERE id = ?", (word_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_srs_word(row)

    async def get_srs_words(self, user_id: int, limit: int = 100) -> list[SRSWord]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT * FROM user_vocabulary WHERE user_id = ? ORDER BY next_review ASC LIMIT ?",
            (user_id, limit),
        )
        return [self._row_to_srs_word(row) for row in await cursor.fetchall()]

    async def update_srs_word(self, word: SRSWord) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE user_vocabulary SET "
            "next_review=?, interval_days=?, ease_factor=?, correct_count=?, last_reviewed=? "
            "WHERE id=?",
            (word.next_review, word.interval_days, word.ease_factor,
             word.correct_count, word.last_reviewed, word.id),
        )
        await conn.commit()

    def _row_to_srs_word(self, row) -> SRSWord:
        return SRSWord(
            id=row["id"], user_id=row["user_id"], word=row["word"],
            translation=row["translation"], example=row["example"],
            lesson_id=row["lesson_id"], next_review=row["next_review"],
            interval_days=row["interval_days"], ease_factor=row["ease_factor"],
            correct_count=row["correct_count"], last_reviewed=row["last_reviewed"],
            created_at=row["created_at"],
        )

    async def get_all_users(self) -> list[UserRow]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT id, tg_id, username, first_name, level, unlimited FROM users"
        )
        rows = await cursor.fetchall()
        return [
            UserRow(
                id=row["id"],
                tg_id=row["tg_id"],
                username=row["username"],
                first_name=row["first_name"],
                level=row["level"],
                is_unlimited=bool(row["unlimited"]),
            )
            for row in rows
        ]

    # ---------- лидерборд ----------

    async def get_leaderboard(self, limit: int = 20) -> list[LeaderboardRow]:
        conn = self._require_conn()
        cursor = await conn.execute(
            """
            SELECT
                u.id AS user_id,
                u.username,
                u.first_name,
                u.level,
                COALESCE(ln.cnt, 0) AS total_lessons,
                COALESCE(m.correct, 0) AS correct,
                COALESCE(m.errors, 0) AS errors,
                (COALESCE(ln.cnt, 0) * 10
                 + COALESCE(m.correct, 0) * 5
                 - COALESCE(m.errors, 0) * 2) AS xp
            FROM users u
            LEFT JOIN (
                SELECT user_id, COUNT(*) AS cnt
                FROM lesson_notes
                GROUP BY user_id
            ) ln ON ln.user_id = u.id
            LEFT JOIN (
                SELECT user_id,
                    SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
                    SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS errors
                FROM messages
                WHERE role = 'user' AND is_correct IS NOT NULL
                GROUP BY user_id
            ) m ON m.user_id = u.id
            WHERE xp > 0
            ORDER BY xp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            streak = await self._calc_streak(row["user_id"])
            result.append(LeaderboardRow(
                user_id=row["user_id"],
                username=row["username"],
                first_name=row["first_name"],
                level=row["level"],
                xp=row["xp"],
                total_lessons=row["total_lessons"],
                streak_days=streak,
            ))
        return result

    async def get_shown_achievements(self, user_id: int) -> list[str]:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT achievement_id FROM user_achievements WHERE user_id = ?",
            (user_id,),
        )
        return [row["achievement_id"] for row in await cursor.fetchall()]

    async def save_shown_achievements(self, user_id: int, achievement_ids: list[str]) -> None:
        # Единый неявный transaction (стиль sqlite.py): rollback по except.
        conn = self._require_conn()
        try:
            await conn.execute("DELETE FROM user_achievements WHERE user_id = ?", (user_id,))
            for aid in achievement_ids:
                await conn.execute(
                    "INSERT OR IGNORE INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
                    (user_id, aid),
                )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def _calc_streak(self, user_id: int) -> int:
        """Считает стрик (дни подряд) для пользователя."""
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT DISTINCT substr(created_at, 1, 10) AS day "
            "FROM messages WHERE user_id = ? AND role = 'user' "
            "UNION "
            "SELECT DISTINCT substr(created_at, 1, 10) AS day "
            "FROM lesson_notes WHERE user_id = ? "
            "ORDER BY day DESC LIMIT 60",
            (user_id, user_id),
        )
        dates = [row["day"] for row in await cursor.fetchall()]
        if not dates:
            return 0

        from datetime import datetime, timedelta
        today = datetime.now(timezone.utc).date()
        streak = 0
        expected = today

        for date_str in dates:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if d == expected:
                streak += 1
                expected -= timedelta(days=1)
            else:
                break

        return streak
