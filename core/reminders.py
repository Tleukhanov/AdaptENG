"""Ежедневные email-напоминания «Продолжим?».

Telegram-бот в проде выключен, поэтому единственный канал возврата ученика —
email (и интерфейс веба). Модуль намеренно не зависит от Telegram:

* ``select_recipients`` — кому вообще стоит писать сегодня;
* ``render_reminder`` — тема/текст/HTML письма;
* ``send_daily_reminders`` — один проход рассылки с дедупликацией;
* ``setup_reminder_scheduler`` — APScheduler-джоб, который раз в час проверяет
  «наш час» и запускает рассылку.

Правила получателя:
* есть email и включённые напоминания (``users.reminders_enabled``);
* не был урока сегодня ИЛИ есть слова к повторению (``next_review <= now``);
* последняя активность не старше ``REMINDER_MIN_AGE_DAYS`` — «уснувшим»
  пользователям письма не помогают, а база получателей остаётся живой.

Дедупликация: не чаще одного письма в 24 часа. Факт попытки пишется событием
``reminder_sent`` в ``events`` — планировщик может рестартовать, а событие
переживает рестарт (в отличие от счётчика в памяти процесса).
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from storage.repo import Repository, SRSWord, UserProfile, UserRow

from .config import Settings
from .email import ACCENT, MUTED, TEXT, EmailSender
from .srs import SRSService

logger = logging.getLogger(__name__)

#: Ширина окна вокруг ``REMINDER_HOUR_UTC`` (в часах). Джоб ходит раз в час,
#: поэтому 1 = «ровно этот час»; окно оставлено на случай дрейфа планировщика.
REMINDER_WINDOW_HOURS = 1

#: Не больше стольких слов показываем в письме (остальное — по ссылке).
DUE_WORDS_IN_EMAIL = 5

#: Сколько часов должно пройти между двумя письмами одному пользователю.
REMINDER_INTERVAL_HOURS = 24


@dataclass
class Recipient:
    """Кандидат на напоминание: всё, что нужно для письма, собрано заранее."""

    user: UserRow
    profile: UserProfile | None = None
    due_words: list[SRSWord] = field(default_factory=list)
    streak: int = 0


@dataclass
class ReminderEmail:
    """Готовое письмо: тема + plain-text + HTML."""

    subject: str
    text: str
    html: str


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _as_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def compute_streak(days: list[str], now: datetime | None = None) -> int:
    """Серия дней подряд, если последний день — сегодня или вчера.

    В отличие от ``ProgressService._get_streak`` (стрик обнуляется, если
    сегодня ещё не занимался), письмо должно показать живую серию: человек
    ещё не открыл урок, но вчерашняя серия — его мотивация.
    """
    today = _as_utc(now).date()
    parsed = sorted({day for day in (_as_date(value) for value in days) if day}, reverse=True)
    if not parsed:
        return 0
    if parsed[0] not in (today, today - timedelta(days=1)):
        return 0
    streak = 1
    cursor = parsed[0]
    for day in parsed[1:]:
        if cursor - day == timedelta(days=1):
            streak += 1
            cursor = day
        else:
            break
    return streak


def _user_days(notes: list, practice_dates: list[str]) -> list[str]:
    """Даты активности пользователя: уроки (заметки) и реплики практики."""
    days = list(practice_dates)
    for note in notes:
        created = getattr(note, "created_at", "")
        if created:
            days.append(created[:10])
    return days


async def select_recipients(
    repo: Repository,
    now: datetime | None = None,
    *,
    min_age_days: int = 30,
    due_limit: int = DUE_WORDS_IN_EMAIL,
) -> list[Recipient]:
    """Кому отправить напоминание сегодня.

    ``min_age_days`` — не писать тем, кто не проявлял активности дольше N дней
    (свежий аккаунт без активности считается активным).
    """
    current = _as_utc(now)
    today = current.date().isoformat()
    srs = SRSService(repo)
    recipients: list[Recipient] = []

    for user in await repo.get_all_users():
        if not (user.email or "").strip():
            continue
        if not user.reminders_enabled:
            continue

        last_activity = _parse_iso(await repo.get_last_activity(user.id))
        registered = _parse_iso(user.created_at)
        reference = last_activity or registered
        if reference is not None:
            if current - reference > timedelta(days=min_age_days):
                continue

        notes = await repo.get_lesson_notes(user.id, limit=10)
        lesson_today = await repo.has_lesson_on(user.id, today)
        due_words = await srs.get_due_words(user.id, limit=due_limit)
        # Урок сегодня — повод не писать; но забытые слова всё равно повод.
        if lesson_today and not due_words:
            continue

        practice_dates = await repo.get_practice_dates(user.id, limit=60)
        streak = compute_streak(_user_days(notes, practice_dates), current)
        profile = await repo.get_profile(user.id)

        recipients.append(
            Recipient(
                user=user,
                profile=profile,
                due_words=due_words,
                streak=streak,
            )
        )
    return recipients


def _safe(value: str) -> str:
    return html.escape(value or "", quote=True)


def render_reminder(
    user: UserRow,
    profile: UserProfile | None,
    due_words: list[SRSWord],
    streak: int,
    *,
    base_url: str = "",
) -> ReminderEmail:
    """Собирает письмо: «Продолжим?», стрик, слова и кнопки в веб-продукт."""
    base = (base_url or "").strip().rstrip("/")
    lesson_url = f"{base}/lesson/next"
    vocab_url = f"{base}/vocab"
    name = (user.first_name or user.username or "друг").strip() or "друг"

    subject = "Продолжим? Минутка английского в AdaptENG"

    lines = [
        f"Привет, {name}!",
        "",
        "Продолжим? Персональный урок английского уже готов.",
    ]
    if profile is not None and profile.goal:
        lines.append(f"Цель: {profile.goal}.")
    if streak > 0:
        lines.append(f"🔥 Серия: {streak} дн. подряд — не теряй ритм.")
    if due_words:
        lines.append("")
        lines.append("Слова к повторению:")
        for word in due_words:
            translation = f" — {word.translation}" if word.translation else ""
            lines.append(f"• {word.word}{translation}")
    lines += [
        "",
        f"Начать урок: {lesson_url}",
        f"Повторить слова: {vocab_url}",
        "",
        "Отключить напоминания можно в настройках профиля.",
    ]
    text = "\n".join(lines) + "\n"

    streak_html = ""
    if streak > 0:
        streak_html = (
            f'<p style="margin:0 0 12px;color:{TEXT};font-size:15px;">'
            f"🔥 Серия: <b>{streak} дн. подряд</b> — не теряй ритм.</p>"
        )

    goal_html = ""
    if profile is not None and profile.goal:
        goal_html = (
            f'<p style="margin:0 0 12px;color:{MUTED};font-size:14px;">'
            f"Цель: {_safe(profile.goal)}.</p>"
        )

    words_html = ""
    if due_words:
        items = "".join(
            "<li style=\"margin:0 0 6px;\">"
            f"<b>{_safe(word.word)}</b>"
            + (f" — {_safe(word.translation)}" if word.translation else "")
            + "</li>"
            for word in due_words
        )
        words_html = (
            f'<p style="margin:20px 0 8px;color:{TEXT};font-size:15px;font-weight:600;">'
            "Слова к повторению</p>"
            f'<ul style="margin:0 0 20px;padding-left:20px;color:{MUTED};font-size:15px;">'
            f"{items}</ul>"
        )

    html_body = f"""\
<!DOCTYPE html>
<html lang="ru">
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:520px;background:#ffffff;border-radius:16px;overflow:hidden;">
          <tr>
            <td style="background:{ACCENT};padding:24px 32px;">
              <span style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:0.3px;">AdaptENG</span>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <h1 style="margin:0 0 12px;color:{TEXT};font-size:22px;line-height:1.3;">
                Продолжим?
              </h1>
              <p style="margin:0 0 12px;color:{MUTED};font-size:15px;line-height:1.6;">
                Привет, {_safe(name)}! Персональный урок английского уже готов.
              </p>
              {goal_html}
              {streak_html}
              {words_html}
              <p style="margin:0 0 12px;">
                <a href="{_safe(lesson_url)}"
                   style="display:inline-block;background:{ACCENT};color:#ffffff;text-decoration:none;
                          padding:14px 28px;border-radius:10px;font-size:15px;font-weight:600;">
                  Начать урок
                </a>
              </p>
              <p style="margin:0 0 8px;">
                <a href="{_safe(vocab_url)}"
                   style="color:{ACCENT};font-size:15px;font-weight:600;text-decoration:none;">
                  Повторить слова →
                </a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background:#f9fafb;color:{MUTED};font-size:12px;line-height:1.6;">
              Отключить напоминания можно в настройках профиля.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return ReminderEmail(subject=subject, text=text, html=html_body)


async def _reminded_recently(
    repo: Repository, user_id: int, now: datetime
) -> bool:
    """Было ли письмо этому пользователю за последние 24 часа (по events)."""
    since = (now - timedelta(hours=REMINDER_INTERVAL_HOURS)).isoformat()
    try:
        events = await repo.get_events(user_id, "reminder_sent", since)
    except Exception:  # noqa: BLE001 - аналитика не должна блокировать рассылку
        logger.warning("Не удалось проверить дедупликацию напоминаний", exc_info=True)
        return False
    return bool(events)


async def send_daily_reminders(
    repo: Repository,
    sender: EmailSender,
    settings: Settings,
    now: datetime | None = None,
) -> int:
    """Один проход рассылки. Возвращает число реально отправленных писем.

    Ошибка отправки одному пользователю логируется и не прерывает остальных.
    В dev-режиме (``SMTP_HOST`` пуст) письма не уходят, но попытка всё равно
    помечается событием — иначе планировщик будет «спамить» в лог каждый час.
    """
    current = _as_utc(now)
    base_url = settings.public_webapp_url
    recipients = await select_recipients(
        repo,
        current,
        min_age_days=settings.reminder_min_age_days,
    )

    sent = 0
    for recipient in recipients:
        if await _reminded_recently(repo, recipient.user.id, current):
            continue

        email = render_reminder(
            recipient.user,
            recipient.profile,
            recipient.due_words,
            recipient.streak,
            base_url=base_url,
        )
        try:
            delivered = await sender.send_reminder(
                recipient.user.email or "", email.subject, email.text, email.html
            )
        except Exception as exc:  # noqa: BLE001 - один сбой не роняет батч
            logger.warning(
                "Напоминание для %s не отправлено: %s",
                recipient.user.email,
                exc,
            )
            continue

        if delivered:
            sent += 1
        else:
            logger.info(
                "Напоминание для %s не отправлено (dev-режим или SMTP): см. лог",
                recipient.user.email,
            )

        try:
            await repo.append_event(
                recipient.user.id,
                "reminder_sent",
                {
                    "sent": delivered,
                    "due": len(recipient.due_words),
                    "streak": recipient.streak,
                },
            )
        except Exception:  # noqa: BLE001 - событие не должно ронять рассылку
            logger.warning("Не удалось записать событие reminder_sent", exc_info=True)

    logger.info(
        "Email-напоминания: отправлено %s из %s получателей", sent, len(recipients)
    )
    return sent


def in_reminder_window(now: datetime, hour: int) -> bool:
    """Попадает ли текущий час в окно ``REMINDER_HOUR_UTC`` (по UTC)."""
    current = _as_utc(now)
    target = int(hour) % 24
    return (current.hour - target) % 24 < REMINDER_WINDOW_HOURS


async def _tick(
    repo: Repository, sender: EmailSender, settings: Settings
) -> None:
    """Джоб планировщика: раз в час, но рассылает только в нужный час."""
    now = datetime.now(timezone.utc)
    if not in_reminder_window(now, settings.reminder_hour_utc):
        return
    try:
        await send_daily_reminders(repo, sender, settings, now)
    except Exception:  # noqa: BLE001 - планировщик не должен умирать
        logger.exception("Сбой рассылки ежедневных напоминаний")


#: Один планировщик на процесс: повторный lifespan (перезагрузка, тесты) не
#: должен плодить дублирующие джобы.
_scheduler: AsyncIOScheduler | None = None


def setup_reminder_scheduler(
    repo: Repository, sender: EmailSender, settings: Settings
) -> AsyncIOScheduler | None:
    """Создаёт планировщик напоминаний или ``None``, если он выключен.

    Включается только ``REMINDERS_ENABLED=1`` (по умолчанию 0, чтобы dev и
    тесты не рассылали письма). Возвращённый планировщик нужно запустить:
    ``scheduler.start()``.
    """
    global _scheduler

    if not int(settings.reminders_enabled or 0):
        return None
    if _scheduler is not None:
        # Планировщик уже создан в этом процессе — второй не нужен.
        logger.info("Планировщик напоминаний уже создан в этом процессе")
        return None

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(hours=1),
        args=[repo, sender, settings],
        id="email_reminders",
        replace_existing=True,
        # Первый тик сразу при старте: дино Heroku перезапускается в случайное
        # время, и ждать час до первой проверки «наш ли час» не нужно.
        next_run_time=datetime.now(timezone.utc),
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    _scheduler = scheduler
    logger.info(
        "Планировщик email-напоминаний создан (час=%s UTC)", settings.reminder_hour_utc
    )
    return scheduler
