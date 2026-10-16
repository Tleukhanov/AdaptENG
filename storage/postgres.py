"""Реализация хранилища на asyncpg (PostgreSQL).

Тот же интерфейс ``Repository`` (repo.py), что и SQLite-реализация, поэтому бот
не знает, на каком бэкенде работает. Диалектные отличия SQLite -> Postgres:

- ``?`` -> ``$1..$n`` (см. ``_adopt()``)
- ``INTEGER PRIMARY KEY AUTOINCREMENT`` -> ``SERIAL PRIMARY KEY`` (в schema.py)
- ``INSERT OR IGNORE`` -> ``INSERT ... ON CONFLICT DO NOTHING``
- ``cursor.lastrowid``/``cursor.rowcount`` -> ``INSERT ... RETURNING id``
- ``MAX(0, ...)`` (скалярный) -> ``GREATEST(0, ...)``
- ``WHERE <alias> > 0`` в get_leaderboard -> сабквери (PG не видит алиас в WHERE)
- ``julianday`` / JSON1 (``json_valid``, ``json_insert``) -> epoch/jsonb

asyncpg импортируется лениво (только при connect), чтобы локальный запуск
и тесты без Postgres не требовали установки библиотеки.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta

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
from .schema import POSTGRES_DDL

logger = logging.getLogger(__name__)

_POOL_MIN = 1
_POOL_MAX = 5

# Схема DDL содержит только по одному оператору на ";": плейсхолдеры не используются.
_POSTGRES_STATEMENTS = [s.strip() for s in POSTGRES_DDL.split(";") if s.strip()]


def _adopt(sql: str) -> str:
    """Переводит ``?``-плейсхолдеры SQLite в ``$1..$n`` PostgreSQL.

    Вызовы в этом файле пишутся в SQLite-стиле (``?``), чтобы копировать SQL из
    sqlite.py без ручной нумерации; результат кэшируется, т.к. запросы повторяются.
    Счётчик нумерации стартует от максимального существующего ``$N`` в запросе,
    поэтому смешанный SQL (часть параметров уже ``$N``) не даёт коллизий.
    """
    converted = _adopt.cache.get(sql)
    if converted is not None:
        return converted
    counter = max((int(num) for num in re.findall(r"\$(\d+)", sql)), default=0)

    def _repl(_match: re.Match) -> str:
        nonlocal counter
        counter += 1
        return f"${counter}"

    converted = re.sub(r"\?", _repl, sql)
    _adopt.cache[sql] = converted
    return converted


_adopt.cache: dict[str, str] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresRepository(Repository):
    def __init__(self, dsn: str, pool_min: int = 1, pool_max: int = 5):
        self._dsn = dsn
        self._pool_min = max(1, int(pool_min))
        self._pool_max = max(self._pool_min, int(pool_max))
        self._pool = None
        self._asyncpg = None

    # ---------- подключение ----------

    async def connect(self) -> None:
        self._asyncpg = __import__("asyncpg")
        self._pool = await self._asyncpg.create_pool(
            dsn=self._dsn, min_size=self._pool_min, max_size=self._pool_max
        )
        async with self._pool.acquire() as conn:
            for statement in _POSTGRES_STATEMENTS:
                await conn.execute(statement)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _acquire(self):
        if self._pool is None:
            raise RuntimeError("Хранилище не подключено: вызовите connect()")
        return self._pool.acquire()

    # ---------- пользователи ----------

    async def get_or_create_user(
        self,
        tg_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> UserRow:
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO users (tg_id, username, first_name, created_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(tg_id) DO UPDATE SET "
                    "username = excluded.username, first_name = excluded.first_name"
                ),
                tg_id,
                username,
                first_name,
                _now(),
            )
            row = await conn.fetchrow(
                _adopt(
                    "SELECT id, tg_id, username, first_name, level, unlimited "
                    "FROM users WHERE tg_id = ?"
                ),
                tg_id,
            )
        return self._user_from_row(row)

    @staticmethod
    def _user_from_row(row) -> UserRow:
        return UserRow(
            id=row["id"],
            tg_id=row["tg_id"],
            username=row["username"],
            first_name=row["first_name"],
            level=row["level"],
            is_unlimited=bool(row["unlimited"]),
        )

    async def get_user(self, user_id: int) -> UserRow | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT id, tg_id, username, first_name, level, unlimited "
                    "FROM users WHERE id = ?"
                ),
                user_id,
            )
        return self._user_from_row(row) if row else None

    async def set_level(self, user_id: int, level: str) -> None:
        async with self._acquire() as conn:
            await conn.execute("UPDATE users SET level = $1 WHERE id = $2", level, user_id)

    async def get_level(self, user_id: int) -> str | None:
        async with self._acquire() as conn:
            return await conn.fetchval("SELECT level FROM users WHERE id = $1", user_id)

    # ---------- квота LLM ----------

    async def get_unlimited_status(self, user_id: int) -> bool:
        async with self._acquire() as conn:
            value = await conn.fetchval("SELECT unlimited FROM users WHERE id = $1", user_id)
        return bool(value) if value is not None else False

    async def set_unlimited_status(self, user_id: int, value: bool) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE users SET unlimited = $1 WHERE id = $2", 1 if value else 0, user_id
            )

    async def get_llm_usage(self, user_id: int, day: str) -> int:
        async with self._acquire() as conn:
            value = await conn.fetchval(
                "SELECT count FROM llm_usage WHERE user_id = $1 AND day = $2", user_id, day
            )
        return value if value is not None else 0

    async def increment_llm_usage(self, user_id: int, day: str, inc: int = 1) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO llm_usage (user_id, day, count) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id, day) DO UPDATE SET count = count + excluded.count"
                ),
                user_id,
                day,
                inc,
            )

    # ---------- бонусные LLM-действия (колесо) ----------

    async def get_extra_actions(self, user_id: int) -> int:
        async with self._acquire() as conn:
            value = await conn.fetchval(
                "SELECT extra_actions FROM user_balances WHERE user_id = $1", user_id
            )
        return value if value is not None else 0

    async def _set_extra_actions(self, user_id: int, amount: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO user_balances (user_id, extra_actions) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET extra_actions = excluded.extra_actions"
                ),
                user_id,
                max(0, amount),
            )

    async def add_extra_actions(self, user_id: int, amount: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO user_balances (user_id, extra_actions) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "extra_actions = extra_actions + excluded.extra_actions"
                ),
                user_id,
                max(0, amount),
            )

    async def decrement_extra_actions(self, user_id: int, amount: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE user_balances SET extra_actions = GREATEST(0, extra_actions - $1) "
                "WHERE user_id = $2",
                amount,
                user_id,
            )

    # ---------- колесо удачи ----------

    async def get_last_spin_date(self, user_id: int) -> str | None:
        async with self._acquire() as conn:
            return await conn.fetchval(
                "SELECT date FROM wheel_spins WHERE user_id = $1 ORDER BY date DESC LIMIT 1",
                user_id,
            )

    async def save_spin(self, user_id: int, date: str) -> bool:
        async with self._acquire() as conn:
            inserted = await conn.fetchval(
                "INSERT INTO wheel_spins (user_id, date) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING RETURNING 1",
                user_id,
                date,
            )
        return inserted is not None

    async def get_dry_streak(self, user_id: int) -> int:
        async with self._acquire() as conn:
            value = await conn.fetchval(
                "SELECT dry_streak FROM user_balances WHERE user_id = $1", user_id
            )
        return value if value is not None else 0

    async def set_dry_streak(self, user_id: int, streak: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO user_balances (user_id, dry_streak) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET dry_streak = excluded.dry_streak"
                ),
                user_id,
                max(0, streak),
            )

    async def create_coupon(self, user_id: int, discount_pct: int, expires_at: str) -> WheelCoupon:
        if not 0 <= discount_pct <= 100:
            raise ValueError(f"discount_pct должен быть в диапазоне 0..100, получено {discount_pct}")
        now = _now()
        async with self._acquire() as conn:
            coupon_id = await conn.fetchval(
                "INSERT INTO wheel_coupons (user_id, discount_pct, expires_at, created_at) "
                "VALUES ($1, $2, $3, $4) RETURNING id",
                user_id,
                discount_pct,
                expires_at,
                now,
            )
        return WheelCoupon(
            id=coupon_id,
            user_id=user_id,
            discount_pct=discount_pct,
            expires_at=expires_at,
            used=False,
            created_at=now,
        )

    async def get_active_coupon(self, user_id: int) -> WheelCoupon | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT id, user_id, discount_pct, expires_at, used, created_at "
                    "FROM wheel_coupons WHERE user_id = ? AND used = 0 AND expires_at > ? "
                    "ORDER BY id DESC LIMIT 1"
                ),
                user_id,
                _now(),
            )
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
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE wheel_coupons SET used = 1 WHERE id = $1 AND user_id = $2",
                coupon_id,
                user_id,
            )

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
        async with self._acquire() as conn:
            sub_id = await conn.fetchval(
                "INSERT INTO subscriptions (user_id, plan_days, granted_at, expires_at) "
                "VALUES ($1, $2, $3, $4) RETURNING id",
                user_id,
                plan_days,
                granted_at,
                expires_at,
            )
        return Subscription(
            id=sub_id,
            user_id=user_id,
            plan_days=plan_days,
            granted_at=granted_at,
            expires_at=expires_at,
        )

    async def get_subscription(self, user_id: int) -> Subscription | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT id, user_id, plan_days, granted_at, expires_at "
                    "FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1"
                ),
                user_id,
            )
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
        async with self._acquire() as conn:
            await conn.execute(
                "INSERT INTO payments "
                "(telegram_payment_id, user_id, amount, currency, plan_days, discount_pct, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING",
                telegram_payment_id,
                user_id,
                amount,
                currency,
                plan_days,
                discount_pct,
                _now(),
            )
        return await self.find_payment(telegram_payment_id)

    async def find_payment(self, telegram_payment_id: str) -> Payment | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT id, telegram_payment_id, user_id, amount, currency, plan_days, discount_pct, created_at "
                    "FROM payments WHERE telegram_payment_id = ?"
                ),
                telegram_payment_id,
            )
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

    @staticmethod
    def _order_from_row(row) -> KaspiOrder:
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
        now = _now()
        async with self._acquire() as conn:
            order_id = await conn.fetchval(
                _adopt(
                    "INSERT INTO kaspi_orders "
                    "(user_id, plan_days, amount, discount_pct, coupon_id, order_code, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id"
                ),
                user_id,
                plan_days,
                amount,
                discount_pct,
                coupon_id,
                order_code,
                now,
            )
        return KaspiOrder(
            id=order_id,
            user_id=user_id,
            plan_days=plan_days,
            amount=amount,
            discount_pct=discount_pct,
            coupon_id=coupon_id,
            order_code=order_code,
            status=KaspiOrder.STATUS_PENDING,
            created_at=now,
        )

    async def get_pending_order(self, user_id: int) -> KaspiOrder | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {self._ORDER_COLUMNS} FROM kaspi_orders "
                "WHERE user_id = $1 AND status = $2 ORDER BY id DESC LIMIT 1",
                user_id,
                KaspiOrder.STATUS_PENDING,
            )
        return self._order_from_row(row) if row else None

    async def get_order(self, order_id: int) -> KaspiOrder | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {self._ORDER_COLUMNS} FROM kaspi_orders WHERE id = $1", order_id
            )
        return self._order_from_row(row) if row else None

    async def attach_photo(self, order_id: int, photo_file_id: str) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE kaspi_orders SET photo_file_id = $1 WHERE id = $2", photo_file_id, order_id
            )

    async def approve_order(self, order_id: int) -> KaspiOrder | None:
        async with self._acquire() as conn:
            updated = await conn.fetchval(
                "UPDATE kaspi_orders SET status = $1, confirmed_at = $2 "
                "WHERE id = $3 AND status = $4 RETURNING id",
                KaspiOrder.STATUS_APPROVED,
                _now(),
                order_id,
                KaspiOrder.STATUS_PENDING,
            )
        if updated is None:
            return None
        return await self.get_order(order_id)

    async def cancel_order(self, order_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE kaspi_orders SET status = $1 WHERE id = $2 AND status = $3",
                KaspiOrder.STATUS_CANCELLED,
                order_id,
                KaspiOrder.STATUS_PENDING,
            )

    async def replace_pending_order(
        self,
        user_id: int,
        plan_days: int,
        amount: int,
        discount_pct: int,
        coupon_id: int,
        order_code: str,
    ) -> KaspiOrder:
        now = _now()
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE kaspi_orders SET status = $1 WHERE user_id = $2 AND status = $3",
                    KaspiOrder.STATUS_CANCELLED,
                    user_id,
                    KaspiOrder.STATUS_PENDING,
                )
                order_id = await conn.fetchval(
                    _adopt(
                        "INSERT INTO kaspi_orders "
                        "(user_id, plan_days, amount, discount_pct, coupon_id, order_code, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id"
                    ),
                    user_id,
                    plan_days,
                    amount,
                    discount_pct,
                    coupon_id,
                    order_code,
                    now,
                )
        return KaspiOrder(
            id=order_id,
            user_id=user_id,
            plan_days=plan_days,
            amount=amount,
            discount_pct=discount_pct,
            coupon_id=coupon_id,
            order_code=order_code,
            status=KaspiOrder.STATUS_PENDING,
            created_at=now,
        )

    async def is_order_code_taken(self, order_code: str) -> bool:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT 1 FROM kaspi_orders WHERE order_code = ? AND status != ? LIMIT 1"
                ),
                order_code,
                KaspiOrder.STATUS_CANCELLED,
            )
        return row is not None

    # ---------- аналитика (события) ----------

    async def append_event(self, user_id: int, event_type: str, payload=None) -> None:
        payload_text = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
        async with self._acquire() as conn:
            await conn.execute(
                "INSERT INTO events (user_id, event_type, payload, created_at) "
                "VALUES ($1, $2, $3, $4)",
                user_id,
                event_type,
                payload_text,
                _now(),
            )

    async def count_events(self, event_type: str, since_date: str) -> int:
        async with self._acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) AS cnt FROM events WHERE event_type = $1 AND created_at >= $2",
                event_type,
                since_date,
            )

    # ---------- админ-статистика ----------

    async def count_spins_today(self, date: str) -> int:
        async with self._acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) AS cnt FROM wheel_spins WHERE date = $1", date
            )

    async def count_pending_orders(self) -> int:
        async with self._acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) AS cnt FROM kaspi_orders WHERE status = $1",
                KaspiOrder.STATUS_PENDING,
            )

    async def sum_revenue(self) -> int:
        async with self._acquire() as conn:
            result = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM kaspi_orders WHERE status = $1",
                KaspiOrder.STATUS_APPROVED,
            )
        return result if result is not None else 0

    async def count_active_subscriptions(self) -> int:
        async with self._acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) AS cnt FROM subscriptions WHERE expires_at > $1", _now()
            )

    # ---------- профиль пользователя ----------

    async def get_profile(self, user_id: int) -> UserProfile | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT user_id, goal, interests, weak_areas, preferred_format, notes, character, updated_at "
                    "FROM user_profiles WHERE user_id = ?"
                ),
                user_id,
            )
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
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO user_profiles "
                    "(user_id, goal, interests, weak_areas, preferred_format, notes, character, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "goal = excluded.goal, interests = excluded.interests, weak_areas = excluded.weak_areas, "
                    "preferred_format = excluded.preferred_format, notes = excluded.notes, "
                    "character = excluded.character, updated_at = excluded.updated_at"
                ),
                profile.user_id,
                profile.goal,
                profile.interests,
                profile.weak_areas,
                profile.preferred_format,
                profile.notes,
                profile.character,
                profile.updated_at,
            )

    # ---------- сообщения и история ----------

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
        async with self._acquire() as conn:
            return await conn.fetchval(
                _adopt(
                    "INSERT INTO messages "
                    "(user_id, role, content, is_correct, issues_json, corrected_text, lesson_id, created_at) "
                    "VALUES (?, 'user', ?, ?, ?, ?, ?, ?) RETURNING id"
                ),
                user_id,
                content,
                is_correct,
                issues_json,
                corrected_text,
                lesson_id,
                _now(),
            )

    async def add_assistant_message(self, user_id: int, content: str) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "INSERT INTO messages (user_id, role, content, created_at) VALUES ($1, 'assistant', $2, $3)",
                user_id,
                content,
                _now(),
            )

    async def get_history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM messages WHERE user_id = $1 ORDER BY id DESC LIMIT $2",
                user_id,
                limit,
            )
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def get_lesson_messages(self, lesson_id: int) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                _adopt(
                    "SELECT content, is_correct, issues_json, corrected_text FROM messages "
                    "WHERE lesson_id = ? AND role = 'user' ORDER BY id ASC"
                ),
                lesson_id,
            )
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
        async with self._acquire() as conn:
            totals = await conn.fetchrow(
                _adopt(
                    "SELECT COUNT(*) AS total, "
                    "COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct, "
                    "COALESCE(SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END), 0) AS errors "
                    "FROM messages WHERE user_id = ? AND role = 'user' AND is_correct IS NOT NULL"
                ),
                user_id,
            )
            rows = await conn.fetch(
                _adopt(
                    "SELECT issues_json FROM messages "
                    "WHERE user_id = ? AND role = 'user' "
                    "AND issues_json IS NOT NULL AND issues_json != '' "
                    "ORDER BY id DESC LIMIT 200"
                ),
                user_id,
            )

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
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT is_correct, corrected_text, issues_json FROM messages "
                    "WHERE user_id = ? AND role = 'user' AND is_correct = 0 "
                    "AND corrected_text IS NOT NULL AND corrected_text != '' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                user_id,
            )
        if row is None:
            return None
        return {
            "is_correct": bool(row["is_correct"]),
            "corrected_text": row["corrected_text"],
            "issues_json": row["issues_json"] or "",
        }

    async def get_user_message(self, user_id: int, message_id: int) -> dict | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT is_correct, corrected_text, issues_json FROM messages "
                    "WHERE id = ? AND user_id = ? AND role = 'user'"
                ),
                message_id,
                user_id,
            )
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
        now = _now()
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE lesson_sessions SET status = 'aborted', updated_at = $1 "
                    "WHERE user_id = $2 AND mode = 'miniapp' AND status = 'active'",
                    now,
                    user_id,
                )
                session_id = await conn.fetchval(
                    _adopt(
                        "INSERT INTO lesson_sessions "
                        "(user_id, topic, content_json, mode, deck_preset, status, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'miniapp', ?, 'active', ?, ?) RETURNING id"
                    ),
                    user_id,
                    topic,
                    deck_json,
                    preset,
                    now,
                    now,
                )
        return MiniLessonSession(
            id=session_id,
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
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT id, user_id, topic, content_json, deck_preset, score_json, status, created_at, updated_at "
                    "FROM lesson_sessions WHERE user_id = ? AND mode = 'miniapp' AND status = 'active' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                user_id,
            )
        return self._row_to_mini_lesson(row) if row else None

    async def save_mini_answers(self, session_id: int, score_json: str) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE lesson_sessions SET score_json = $1, updated_at = $2 "
                "WHERE id = $3 AND mode = 'miniapp'",
                score_json,
                _now(),
                session_id,
            )

    async def finish_mini_lesson(self, session_id: int, score_json: str | None = None) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE lesson_sessions SET status = 'finished', updated_at = $1, "
                "score_json = COALESCE($2, score_json) WHERE id = $3 AND mode = 'miniapp'",
                _now(),
                score_json,
                session_id,
            )

    async def save_audio_answer(
        self,
        session_id: int,
        word: str,
        audio_file: str,
        transcript: str,
        rating: int | None,
    ) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "INSERT INTO audio_answers (session_id, word, audio_file, transcript, rating) "
                "VALUES ($1, $2, $3, $4, $5)",
                session_id,
                word,
                audio_file,
                transcript,
                rating,
            )

    async def start_lesson(self, user_id: int, topic: str, content_json: str) -> LessonSession:
        now = _now()
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE lesson_sessions SET status = 'aborted', updated_at = $1 "
                    "WHERE user_id = $2 AND status = 'active'",
                    now,
                    user_id,
                )
                session_id = await conn.fetchval(
                    _adopt(
                        "INSERT INTO lesson_sessions (user_id, topic, content_json, status, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'active', ?, ?) RETURNING id"
                    ),
                    user_id,
                    topic,
                    content_json,
                    now,
                    now,
                )
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
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT * FROM lesson_sessions WHERE user_id = ? AND status = 'active' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                user_id,
            )
        return self._row_to_lesson(row) if row else None

    async def update_lesson(self, session_id: int, *, step: int | None = None, task_index: int | None = None) -> None:
        updates: list[str] = []
        params: list[int | str] = []
        if step is not None:
            updates.append(f"step = ${len(params) + 1}")
            params.append(step)
        if task_index is not None:
            updates.append(f"task_index = ${len(params) + 1}")
            params.append(task_index)
        if not updates:
            return
        updates.append(f"updated_at = ${len(params) + 1}")
        params.append(_now())
        params.append(session_id)
        async with self._acquire() as conn:
            await conn.execute(
                f"UPDATE lesson_sessions SET {', '.join(updates)} WHERE id = ${len(params)}",
                *params,
            )

    async def finish_lesson(self, session_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE lesson_sessions SET status = 'finished', updated_at = $1 WHERE id = $2",
                _now(),
                session_id,
            )

    async def finish_active_lessons(self, user_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE lesson_sessions SET status = 'finished', updated_at = $1 "
                "WHERE user_id = $2 AND status = 'active'",
                _now(),
                user_id,
            )

    async def abort_active_lessons(self, user_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE lesson_sessions SET status = 'aborted', updated_at = $1 "
                "WHERE user_id = $2 AND status = 'active'",
                _now(),
                user_id,
            )

    async def add_lesson_note(self, note: LessonNote) -> int:
        async with self._acquire() as conn:
            return await conn.fetchval(
                _adopt(
                    "INSERT INTO lesson_notes "
                    "(user_id, lesson_id, topic, vocabulary, grammar, speaking, mistakes, recommendation, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id"
                ),
                note.user_id,
                note.lesson_id,
                note.topic,
                note.vocabulary,
                note.grammar,
                note.speaking,
                note.mistakes,
                note.recommendation,
                note.created_at or _now(),
            )

    async def get_lesson_notes(self, user_id: int, limit: int = 10) -> list[LessonNote]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                _adopt(
                    "SELECT id, user_id, lesson_id, topic, vocabulary, grammar, speaking, mistakes, recommendation, created_at "
                    "FROM lesson_notes WHERE user_id = ? ORDER BY id DESC LIMIT ?"
                ),
                user_id,
                limit,
            )
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
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT user_id, plan_json, horizon, based_on_lessons, generated_at "
                    "FROM user_lesson_plans WHERE user_id = ?"
                ),
                user_id,
            )
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
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO user_lesson_plans "
                    "(user_id, plan_json, horizon, based_on_lessons, generated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "plan_json = excluded.plan_json, horizon = excluded.horizon, "
                    "based_on_lessons = excluded.based_on_lessons, "
                    "generated_at = excluded.generated_at"
                ),
                plan.user_id,
                plan.plan_json,
                plan.horizon,
                plan.based_on_lessons,
                plan.generated_at,
            )

    async def count_finished_lessons(self, user_id: int) -> int:
        async with self._acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) AS cnt FROM lesson_sessions "
                "WHERE user_id = $1 AND status = 'finished'",
                user_id,
            )

    # ---------- диагностика уровня ----------

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
        now = _now()
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE diagnostic_sessions SET status = 'aborted', updated_at = $1 "
                    "WHERE user_id = $2 AND status = 'active'",
                    now,
                    user_id,
                )
                session_id = await conn.fetchval(
                    _adopt(
                        "INSERT INTO diagnostic_sessions (user_id, questions_json, status, created_at, updated_at) "
                        "VALUES (?, ?, 'active', ?, ?) RETURNING id"
                    ),
                    user_id,
                    questions_json,
                    now,
                    now,
                )
        return DiagnosticSession(
            id=session_id,
            user_id=user_id,
            questions_json=questions_json,
            answers_json="[]",
            status="active",
            created_at=now,
            updated_at=now,
        )

    async def get_active_diagnostic(self, user_id: int) -> DiagnosticSession | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT * FROM diagnostic_sessions WHERE user_id = ? AND status = 'active' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                user_id,
            )
        return self._row_to_diagnostic(row) if row else None

    async def append_diagnostic_answer(self, session_id: int, answer: str) -> None:
        # Postgres-аналог JSON1-фичи SQLite: jsonb-оператор || дёшево, сохраняет
        # сериализацию в TEXT (answers_json читается как строка в get_active_diagnostic).
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE diagnostic_sessions SET "
                "answers_json = CASE "
                "  WHEN jsonb_typeof(answers_json::jsonb) = 'array' "
                "  THEN (answers_json::jsonb || jsonb_build_array($1::text))::text "
                "  ELSE jsonb_build_array($1::text)::text END, "
                "updated_at = $2 WHERE id = $3",
                answer,
                _now(),
                session_id,
            )

    async def finish_diagnostic(self, session_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE diagnostic_sessions SET status = 'finished', updated_at = $1 WHERE id = $2",
                _now(),
                session_id,
            )

    async def abort_active_diagnostics(self, user_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE diagnostic_sessions SET status = 'aborted', updated_at = $1 "
                "WHERE user_id = $2 AND status = 'active'",
                _now(),
                user_id,
            )

    # ---------- предложения тем ----------

    async def save_topic_proposals(self, user_id: int, proposals: list[TopicProposal]) -> None:
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM topic_proposals WHERE user_id = $1", user_id)
                for p in proposals:
                    await conn.execute(
                        _adopt(
                            "INSERT INTO topic_proposals (user_id, topic, description, created_at) "
                            "VALUES (?, ?, ?, ?)"
                        ),
                        user_id,
                        p.topic,
                        p.description,
                        p.created_at or _now(),
                    )

    async def get_topic_proposal(self, proposal_id: int) -> TopicProposal | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                _adopt(
                    "SELECT id, user_id, topic, description, created_at FROM topic_proposals WHERE id = ?"
                ),
                proposal_id,
            )
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
        async with self._acquire() as conn:
            rows = await conn.fetch(
                _adopt(
                    "SELECT id, user_id, topic, description, created_at FROM topic_proposals "
                    "WHERE user_id = ? ORDER BY id"
                ),
                user_id,
            )
        return [
            TopicProposal(
                id=row["id"],
                user_id=row["user_id"],
                topic=row["topic"],
                description=row["description"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def delete_topic_proposals(self, user_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute("DELETE FROM topic_proposals WHERE user_id = $1", user_id)

    # ---------- активность ----------

    async def get_practice_dates(self, user_id: int, limit: int = 50) -> list[str]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                _adopt(
                    "SELECT DISTINCT substr(created_at, 1, 10) AS day "
                    "FROM messages WHERE user_id = ? AND role = 'user' "
                    "ORDER BY day DESC LIMIT ?"
                ),
                user_id,
                limit,
            )
        return [row["day"] for row in rows]

    async def get_last_activity(self, user_id: int) -> str | None:
        async with self._acquire() as conn:
            best = await conn.fetchval(
                "SELECT created_at FROM messages WHERE user_id = $1 AND role = 'user' "
                "ORDER BY id DESC LIMIT 1",
                user_id,
            )
            note = await conn.fetchval(
                "SELECT created_at FROM lesson_notes WHERE user_id = $1 ORDER BY id DESC LIMIT 1",
                user_id,
            )
        if best is None:
            return note
        if note is None:
            return best
        return best if best >= note else note

    # ---------- слабые области ----------

    async def get_weak_areas(self, user_id: int) -> list[WeakArea]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                _adopt(
                    "SELECT id, user_id, area, incorrect_count, correct_count, last_seen, created_at "
                    "FROM user_weak_areas WHERE user_id = ? "
                    "ORDER BY (incorrect_count * 2.0 + "
                    "CASE WHEN last_seen IS NOT NULL AND last_seen != '' THEN "
                    "  GREATEST(0, 14 - CAST(("
                    "    extract(epoch FROM now()::timestamptz) - "
                    "    extract(epoch FROM last_seen::timestamptz)"
                    "  ) / 86400 AS INTEGER)) / 14.0 "
                    "ELSE 0 END) DESC"
                ),
                user_id,
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
            for row in rows
        ]

    async def upsert_weak_area(
        self,
        user_id: int,
        area: str,
        incorrect_increment: int = 0,
        correct_increment: int = 0,
        last_seen: str = "",
    ) -> None:
        now = last_seen or ""
        async with self._acquire() as conn:
            await conn.execute(
                _adopt(
                    "INSERT INTO user_weak_areas "
                    "(user_id, area, incorrect_count, correct_count, last_seen, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(user_id, area) DO UPDATE SET "
                    "incorrect_count = incorrect_count + excluded.incorrect_count, "
                    "correct_count = correct_count + excluded.correct_count, "
                    "last_seen = CASE WHEN excluded.last_seen != '' "
                    "  THEN excluded.last_seen ELSE user_weak_areas.last_seen END"
                ),
                user_id,
                area,
                incorrect_increment,
                correct_increment,
                now,
                now,
            )

    async def delete_weak_area(self, user_id: int, area: str) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "DELETE FROM user_weak_areas WHERE user_id = $1 AND area = $2", user_id, area
            )

    # ---------- SRS vocabulary ----------

    async def add_srs_word(self, word: SRSWord) -> int:
        async with self._acquire() as conn:
            new_id = await conn.fetchval(
                _adopt(
                    "INSERT INTO user_vocabulary "
                    "(user_id, word, translation, example, lesson_id, next_review, interval_days, ease_factor, correct_count, last_reviewed, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING RETURNING id"
                ),
                word.user_id,
                word.word,
                word.translation,
                word.example,
                word.lesson_id,
                word.next_review,
                word.interval_days,
                word.ease_factor,
                word.correct_count,
                word.last_reviewed,
                word.created_at,
            )
        return new_id

    async def get_srs_word(self, user_id: int, word: str) -> SRSWord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_vocabulary WHERE user_id = $1 AND word = $2", user_id, word
            )
        if not row:
            return None
        return self._row_to_srs_word(row)

    async def get_srs_word_by_id(self, word_id: int) -> SRSWord | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_vocabulary WHERE id = $1", word_id
            )
        if not row:
            return None
        return self._row_to_srs_word(row)

    async def get_srs_words(self, user_id: int, limit: int = 100) -> list[SRSWord]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM user_vocabulary WHERE user_id = $1 ORDER BY next_review ASC LIMIT $2",
                user_id,
                limit,
            )
        return [self._row_to_srs_word(row) for row in rows]

    async def update_srs_word(self, word: SRSWord) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "UPDATE user_vocabulary SET "
                "next_review=$1, interval_days=$2, ease_factor=$3, correct_count=$4, last_reviewed=$5 "
                "WHERE id=$6",
                word.next_review,
                word.interval_days,
                word.ease_factor,
                word.correct_count,
                word.last_reviewed,
                word.id,
            )

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
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, tg_id, username, first_name, level, unlimited FROM users"
            )
        return [self._user_from_row(row) for row in rows]

    # ---------- лидерборд ----------

    async def get_leaderboard(self, limit: int = 20) -> list[LeaderboardRow]:
        # Postgres не позволяет ссылаться в WHERE на алиас из SELECT — оборачиваем в сабквери.
        base_select = _adopt(
            "SELECT u.id AS user_id, u.username, u.first_name, u.level, "
            "COALESCE(ln.cnt, 0) AS total_lessons, "
            "COALESCE(m.correct, 0) AS correct, "
            "COALESCE(m.errors, 0) AS errors, "
            "(COALESCE(ln.cnt, 0) * 10 + COALESCE(m.correct, 0) * 5 - COALESCE(m.errors, 0) * 2) AS xp "
            "FROM users u "
            "LEFT JOIN (SELECT user_id, COUNT(*) AS cnt FROM lesson_notes GROUP BY user_id) ln "
            "  ON ln.user_id = u.id "
            "LEFT JOIN (SELECT user_id, "
            "  SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct, "
            "  SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS errors "
            "  FROM messages WHERE role = 'user' AND is_correct IS NOT NULL GROUP BY user_id) m "
            "  ON m.user_id = u.id"
        )
        async with self._acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM ({base_select}) scorer WHERE xp > 0 ORDER BY xp DESC LIMIT $1",
                limit,
            )
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

    # ---------- достижения ----------

    async def get_shown_achievements(self, user_id: int) -> list[str]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT achievement_id FROM user_achievements WHERE user_id = $1", user_id
            )
        return [row["achievement_id"] for row in rows]

    async def save_shown_achievements(self, user_id: int, achievement_ids: list[str]) -> None:
        async with self._acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM user_achievements WHERE user_id = $1", user_id
                )
                for aid in achievement_ids:
                    await conn.execute(
                        "INSERT INTO user_achievements (user_id, achievement_id) "
                        "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        user_id,
                        aid,
                    )

    async def _calc_streak(self, user_id: int) -> int:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                _adopt(
                    "SELECT DISTINCT substr(created_at, 1, 10) AS day "
                    "FROM messages WHERE user_id = ? AND role = 'user' "
                    "UNION "
                    "SELECT DISTINCT substr(created_at, 1, 10) AS day "
                    "FROM lesson_notes WHERE user_id = ? "
                    "ORDER BY day DESC LIMIT 60"
                ),
                user_id,
                user_id,
            )
        dates = [row["day"] for row in rows]
        if not dates:
            return 0

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