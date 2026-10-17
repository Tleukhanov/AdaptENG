"""Аналитика обучения и воронки: считает метрики из уже существующих данных.

Ничего нового не изобретаем — все числа собираются из таблиц, которые уже
наполняются в обычном flow (реплики с is_correct, SRS-слова с интервалами,
уроки, события, диагностика). Нужен только слой агрегации.

Два уровня:
* :func:`learning_report` — честный прогресс конкретного ученика:
  точность по периодам (было/стало), удержание слов на интервалах, серия,
  рост уровня, прогноз уровня по факту.
* :func:`funnel_summary` / :func:`learning_cohort_summary` — продуктовые
  метрики: воронка (регистрация → онбординг → первый урок), удержание
  на 1/7/30 дней, активные ученики, распределение уровней.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------- вспомогательное ----------


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _day(value: Any) -> str | None:
    dt = _parse_dt(value)
    return dt.date().isoformat() if dt else None


def _bucket(dt: datetime, days: int) -> str:
    """Начало периода длиной ``days`` (7 = неделя, 30 = месяц)."""
    seconds = timedelta(days=days).total_seconds()
    epoch = dt.timestamp()
    shifted = dt - timedelta(seconds=epoch % seconds)
    return shifted.date().isoformat()


def _rate(correct: int, total: int) -> float:
    return round(correct / total * 100, 1) if total else 0.0


# ---------- данные ----------


@dataclass
class TurnSample:
    at: datetime
    correct: bool


@dataclass
class WordSample:
    added_at: datetime | None
    due_at: datetime | None
    interval_days: int
    ease: float
    reviews: int


@dataclass
class UserLearningData:
    user_id: int
    turns: list[TurnSample] = field(default_factory=list)
    words: list[WordSample] = field(default_factory=list)
    lessons: int = 0
    active_days: list[str] = field(default_factory=list)
    level: str | None = None
    diagnostic_level: str | None = None
    diagnostics: list[str] = field(default_factory=list)
    events: list[tuple[str, str | None]] = field(default_factory=list)
    weak_areas: list[dict[str, Any]] = field(default_factory=list)


async def collect_user_learning(repo, user_id: int) -> UserLearningData:
    """Собирает сырые данные одного ученика из репозитория."""
    data = UserLearningData(user_id=user_id)

    try:
        rows = await repo.get_user_turns(user_id, 500)
    except Exception:
        rows = []
    for row in rows or []:
        item = row if isinstance(row, dict) else getattr(row, "__dict__", {})
        at = _parse_dt(item.get("created_at"))
        if at is None:
            continue
        raw = item.get("is_correct")
        if raw is None:
            continue
        data.turns.append(TurnSample(at=at, correct=bool(raw)))

    try:
        words = await repo.get_srs_words(user_id, limit=500)
    except Exception:
        words = []
    for word in words or []:
        data.words.append(
            WordSample(
                added_at=_parse_dt(getattr(word, "created_at", None)),
                due_at=_parse_dt(getattr(word, "next_review", None)),
                interval_days=int(getattr(word, "interval_days", 0) or 0),
                ease=float(getattr(word, "ease_factor", 0) or 0),
                reviews=int(getattr(word, "reviews", 0) or 0),
            )
        )

    try:
        notes = await repo.get_lesson_notes(user_id, limit=200)
        data.lessons = len(notes or [])
        for note in notes or []:
            day = _day(getattr(note, "created_at", None))
            if day:
                data.active_days.append(day)
    except Exception:
        pass

    try:
        dates = await repo.get_practice_dates(user_id, limit=200)
        data.active_days.extend([d for d in (dates or []) if d])
    except Exception:
        pass

    user = await repo.get_user(user_id) if hasattr(repo, "get_user") else None
    if user is not None:
        data.level = getattr(user, "level", None)

    try:
        data.weak_areas = [dict(row) for row in await repo.get_weak_areas(user_id)]
    except Exception:
        data.weak_areas = []

    for event_type, since in (("user_registered", None), ("onboarding_completed", None), ("lesson_completed", None), ("diagnostic_completed", None), ("voice_answer", None), ("review_answer", None)):
        try:
            rows = await repo.get_events(user_id, event_type, since_date=since)
        except Exception:
            rows = []
        for row in rows or []:
            item = row if isinstance(row, dict) else getattr(row, "__dict__", {})
            data.events.append((event_type, _day(item.get("created_at"))))

    try:
        sessions = await repo.get_diagnostic_sessions(user_id)
        for session in sessions or []:
            level = getattr(session, "level", None) or (
                session.get("level") if isinstance(session, dict) else None
            )
            if level:
                data.diagnostic_level = str(level).upper()
                data.diagnostics.append(str(level).upper())
    except Exception:
        pass

    return data


# ---------- 1. отчёт по ученику ----------


def _accuracy_buckets(turns: list[TurnSample], bucket_days: int) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for turn in turns:
        key = _bucket(turn.at, bucket_days)
        entry = buckets.setdefault(key, {"period": key, "turns": 0, "correct": 0})
        entry["turns"] += 1
        entry["correct"] += 1 if turn.correct else 0
    result = []
    for key in sorted(buckets):
        entry = buckets[key]
        entry["accuracy"] = _rate(entry["correct"], entry["turns"])
        result.append(entry)
    return result


def _retention(words: list[WordSample], at_least: int) -> dict[str, Any]:
    total = len(words)
    kept = sum(1 for w in words if w.interval_days >= at_least)
    return {
        "interval_days": at_least,
        "words": kept,
        "total": total,
        "percent": round(kept / total * 100, 1) if total else 0.0,
    }


_LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1"]


def _growth(first: str | None, last: str | None) -> dict[str, Any]:
    if not first or not last or first not in _LEVEL_ORDER or last not in _LEVEL_ORDER:
        return {"from": first, "to": last, "steps": None}
    return {"from": first, "to": last, "steps": _LEVEL_ORDER.index(last) - _LEVEL_ORDER.index(first)}


def learning_report(data: UserLearningData, *, days: int = 30) -> dict[str, Any]:
    """Персональный отчёт: прогресс, а не «сколько раз зашёл»."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total = len(data.turns)
    correct = sum(1 for t in data.turns if t.correct)
    recent_7 = [t for t in data.turns if t.at >= week_ago]
    prev_7 = [t for t in data.turns if week_ago - timedelta(days=7) <= t.at < week_ago]
    recent_30 = [t for t in data.turns if t.at >= month_ago]
    prev_30 = [t for t in data.turns if month_ago - timedelta(days=7) <= t.at < month_ago]

    # прогноз уровня по объёму практики и средней точности
    predicted = None
    if total >= 10:
        score = _rate(correct, total)
        if score >= 90 and total >= 120:
            predicted = "C1"
        elif score >= 80 and total >= 70:
            predicted = "B2"
        elif score >= 65:
            predicted = "B1"
        elif score >= 45:
            predicted = "A2"
        else:
            predicted = "A1"

    return {
        "totals": {
            "turns": total,
            "correct": correct,
            "accuracy": _rate(correct, total),
            "lessons": data.lessons,
            "words": len(data.words),
            "streak_days": len(set(data.active_days)),
            "active_days": len(set(data.active_days)),
        },
        "trend": {
            "week": {
                "turns": len(recent_7),
                "accuracy": _rate(sum(1 for t in recent_7 if t.correct), len(recent_7)),
                "previous_accuracy": _rate(sum(1 for t in prev_7 if t.correct), len(prev_7)),
                "delta": round(
                    _rate(sum(1 for t in recent_7 if t.correct), len(recent_7))
                    - _rate(sum(1 for t in prev_7 if t.correct), len(prev_7)),
                    1,
                ),
            },
            "month": {
                "turns": len(recent_30),
                "accuracy": _rate(sum(1 for t in recent_30 if t.correct), len(recent_30)),
                "previous_accuracy": _rate(sum(1 for t in prev_30 if t.correct), len(prev_30)),
                "delta": round(
                    _rate(sum(1 for t in recent_30 if t.correct), len(recent_30))
                    - _rate(sum(1 for t in prev_30 if t.correct), len(prev_30)),
                    1,
                ),
            },
            "by_week": _accuracy_buckets(data.turns, 7),
            "by_month": _accuracy_buckets(data.turns, 30),
        },
        "retention": {
            "day1": _retention(data.words, 1),
            "day7": _retention(data.words, 7),
            "day30": _retention(data.words, 30),
            "mean_ease": round(sum(w.ease for w in data.words) / len(data.words), 2) if data.words else 0,
        },
        "level": {
            "current": data.level,
            "diagnostic": data.diagnostic_level,
            "diagnostic_history": data.diagnostics[-5:],
            "growth": _growth(data.diagnostic_level, data.level),
            "predicted": predicted,
        },
        "weak_areas": [
            {
                "area": row.get("area"),
                "correct": row.get("correct_count", 0),
                "incorrect": row.get("incorrect_count", 0),
                "accuracy": _rate(row.get("correct_count", 0), row.get("correct_count", 0) + row.get("incorrect_count", 0)),
            }
            for row in data.weak_areas[:5]
        ],
        "insight": _insight(recent_7, prev_7, data),
    }


def _insight(recent: list[TurnSample], prev: list[TurnSample], data: UserLearningData) -> str:
    """Одно человекочитаемое предупреждение/похвала."""
    if len(recent) < 3:
        if len(data.turns) < 10:
            return "Мало данных: напиши ещё несколько фраз в чате — покажем динамику точности."
        return "Начни неделю с 3–5 фраз в чате, чтобы увидеть, как растёт точность."
    r_acc = _rate(sum(1 for t in recent if t.correct), len(recent))
    if prev:
        p_acc = _rate(sum(1 for t in prev if t.correct), len(prev))
        if r_acc >= p_acc + 10:
            return f"Точность выросла: {p_acc}% → {r_acc}% за неделю. Метод работает."
        if p_acc - r_acc >= 10:
            return f"Точность просела: {p_acc}% → {r_acc}%. Повтори слова, помеченные «Повторю»."
    if r_acc >= 85:
        return "Отличная точность — можно поднять уровень сложности."
    return f"Стабильный темп: {r_acc}% верных реплик за неделю."


# ---------- 2. продуктовая воронка ----------


async def _distinct_users_with_event(repo, event_type: str, since: str) -> int:
    try:
        rows = await repo.get_event_user_ids(event_type, since)
    except Exception:
        return 0
    return len(rows or [])


async def funnel_summary(repo, *, days: int = 30) -> dict[str, Any]:
    """Воронка и удержание по всей базе."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).date().isoformat()

    total_users = await repo.count_users()

    stages = {
        "registered": await _distinct_users_with_event(repo, "user_registered", since),
        "onboarding": await _distinct_users_with_event(repo, "onboarding_completed", since),
        "first_lesson": await _distinct_users_with_event(repo, "lesson_completed", since),
    }

    active_today = await _distinct_users_with_event(repo, "any", datetime.now().date().isoformat())

    return {
        "days": days,
        "since": since,
        "total_users": total_users,
        "funnel": stages,
        "conversion": {
            "register_to_onboarding": _rate(stages["onboarding"], stages["registered"]),
            "onboarding_to_lesson": _rate(stages["first_lesson"], stages["onboarding"]),
            "register_to_lesson": _rate(stages["first_lesson"], stages["registered"]),
        },
        "retention": {
            "d1": await _retention_rate(repo, 1),
            "d7": await _retention_rate(repo, 7),
            "d30": await _retention_rate(repo, 30),
        },
        "active_today": active_today,
    }


async def _retention_rate(repo, days: int) -> dict[str, Any]:
    """Доля пользователей, активных сегодня, у которых был день рождения когорты N дней назад."""
    now = datetime.now(timezone.utc)
    target = (now - timedelta(days=days)).date().isoformat()
    future = (now - timedelta(days=days) + timedelta(days=1)).date().isoformat()
    try:
        cohort = await repo.count_users_registered_between(target, future)
        active = await repo.count_active_users_in_window(target, future)
    except Exception:
        return {"percent": 0.0, "cohort": 0}
    return {
        "percent": _rate(active, cohort),
        "cohort": cohort,
        "active": active,
        "note": "активны сегодня среди зарегистрированных N дней назад",
    }


async def learning_cohort_summary(repo, *, limit: int = 20) -> list[dict[str, Any]]:
    """Срез «есть ли у нас ученики с результатом» — по последним ученикам."""
    out: list[dict[str, Any]] = []
    for user in await repo.list_users_recent(limit=limit):
        try:
            data = await collect_user_learning(repo, user.id)
        except Exception:
            continue
        report = learning_report(data)
        out.append(
            {
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "level": user.level,
                "turns": report["totals"]["turns"],
                "accuracy": report["totals"]["accuracy"],
                "lessons": report["totals"]["lessons"],
                "words": report["totals"]["words"],
                "streak_days": report["totals"]["streak_days"],
                "accuracy_7d": report["trend"]["week"]["accuracy"],
                "trend_delta": report["trend"]["week"]["delta"],
                "retention_30": report["retention"]["day30"]["percent"],
            }
        )
    return out