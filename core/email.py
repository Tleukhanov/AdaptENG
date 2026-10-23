"""Отправка писем подтверждения email.

Абстракция намеренно маленькая: продукту нужно только письмо со ссылкой
подтверждения. Два бэкенда:

* ``SMTPSender`` — реальная отправка через stdlib ``smtplib``; блокирующий
  вызов уводится в ``asyncio.to_thread``, чтобы не вешать event loop.
* ``DevEmailSender`` — если ``SMTP_HOST`` пуст: письмо не отправляется, ссылка
  пишется в лог (``sent=False``). Так локальная разработка и тесты не требуют
  почтового сервера.

Отправка всегда best-effort: сетевые ошибки логируются и превращаются в
``False``, а не в исключение — подтверждение email не должно ломать
регистрацию или запрос повторного письма.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from .config import Settings

logger = logging.getLogger(__name__)

#: Тёмно-синий акцент в письме (совпадает с брендом web-продукта).
ACCENT = "#1e3a8a"
TEXT = "#1f2937"
MUTED = "#6b7280"


def verification_link(settings: Settings, token: str) -> str:
    """Ссылка из письма: ``{WEBAPP_PUBLIC_URL}/api/auth/verify?token=...``."""
    base = settings.public_webapp_url.rstrip("/")
    return f"{base}/api/auth/verify?token={token}"


def verification_email_html(link: str, ttl_hours: int) -> str:
    """Простой аккуратный HTML-шаблон письма (тёмно-синий акцент)."""
    safe_link = link.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    return f"""\
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
                Подтвердите email
              </h1>
              <p style="margin:0 0 24px;color:{MUTED};font-size:15px;line-height:1.6;">
                Кто-то (надеемся, вы) указал этот адрес при регистрации в AdaptENG.
                Нажмите кнопку ниже, чтобы подтвердить почту.
              </p>
              <p style="margin:0 0 28px;">
                <a href="{safe_link}"
                   style="display:inline-block;background:{ACCENT};color:#ffffff;text-decoration:none;
                          padding:14px 28px;border-radius:10px;font-size:15px;font-weight:600;">
                  Подтвердить email
                </a>
              </p>
              <p style="margin:0 0 8px;color:{MUTED};font-size:13px;line-height:1.6;">
                Ссылка действует {ttl_hours} ч. Если кнопка не открывается, скопируйте адрес:
              </p>
              <p style="margin:0;font-size:13px;line-height:1.6;word-break:break-all;">
                <a href="{safe_link}" style="color:{ACCENT};">{safe_link}</a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background:#f9fafb;color:{MUTED};font-size:12px;line-height:1.6;">
              Если вы не регистрировались в AdaptENG, просто проигнорируйте письмо —
              аккаунт останется неподтверждённым.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def verification_email_text(link: str, ttl_hours: int) -> str:
    return (
        "Подтвердите email в AdaptENG\n\n"
        f"Откройте ссылку (действует {ttl_hours} ч):\n{link}\n\n"
        "Если вы не регистрировались, просто проигнорируйте письмо.\n"
    )


class EmailSender(ABC):
    """Минимальный интерфейс отправки писем."""

    @abstractmethod
    async def send_verification(self, email: str, link: str) -> bool:
        """Отправляет письмо со ссылкой. ``True`` — реально отправлено."""

    async def send_reminder(
        self, email: str, subject: str, text: str, html: str
    ) -> bool:
        """Ежедневное напоминание «Продолжим?». ``True`` — реально отправлено.

        Не абстрактный: сторонние отправители (тесты, будущие каналы) могут
        не поддерживать напоминания, и это не должно ломать их создание.
        """
        raise NotImplementedError


class DevEmailSender(EmailSender):
    """Dev-режим без SMTP: ссылка пишется в лог, письмо не уходит."""

    def __init__(self, ttl_hours: int = 24) -> None:
        self.ttl_hours = ttl_hours

    async def send_verification(self, email: str, link: str) -> bool:
        logger.info(
            "Email verification (dev mode, SMTP_HOST пуст): %s -> %s",
            email,
            link,
        )
        return False

    async def send_reminder(
        self, email: str, subject: str, text: str, html: str
    ) -> bool:
        logger.info(
            "Reminder email (dev mode, SMTP_HOST пуст): %s — %s",
            email,
            subject,
        )
        return False


class SMTPSender(EmailSender):
    """Отправка через SMTP (stdlib) в отдельном потоке."""

    def __init__(self, settings: Settings) -> None:
        self.host = settings.smtp_host.strip()
        self.port = settings.smtp_port
        self.user = settings.smtp_user.strip()
        self.password = settings.smtp_password
        self.starttls = bool(settings.smtp_starttls)
        self.sender = settings.email_from.strip() or "no-reply@adapteng.com"
        self.ttl_hours = settings.email_verify_ttl_hours

    def _build_message(self, email: str, link: str) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = "Подтвердите email в AdaptENG"
        message["From"] = self.sender
        message["To"] = email
        message.set_content(verification_email_text(link, self.ttl_hours))
        message.add_alternative(
            verification_email_html(link, self.ttl_hours), subtype="html"
        )
        return message

    def _build_reminder_message(
        self, email: str, subject: str, text: str, html: str
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = email
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        return message

    def _send_sync(self, email: str, link: str) -> None:
        message = self._build_message(email, link)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.ehlo()
            if self.starttls:
                smtp.starttls()
                smtp.ehlo()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)

    async def send_verification(self, email: str, link: str) -> bool:
        try:
            await asyncio.to_thread(self._send_sync, email, link)
        except Exception as exc:  # noqa: BLE001 - письмо не должно ломать запрос
            logger.warning("Не удалось отправить письмо на %s: %s", email, exc)
            return False
        logger.info("Письмо подтверждения отправлено на %s", email)
        return True

    def _send_reminder_sync(
        self, email: str, subject: str, text: str, html: str
    ) -> None:
        message = self._build_reminder_message(email, subject, text, html)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.ehlo()
            if self.starttls:
                smtp.starttls()
                smtp.ehlo()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(message)

    async def send_reminder(
        self, email: str, subject: str, text: str, html: str
    ) -> bool:
        try:
            await asyncio.to_thread(
                self._send_reminder_sync, email, subject, text, html
            )
        except Exception as exc:  # noqa: BLE001 - напоминание не должно ронять батч
            logger.warning("Не удалось отправить напоминание на %s: %s", email, exc)
            return False
        logger.info("Напоминание отправлено на %s", email)
        return True


def create_email_sender(settings: Settings) -> EmailSender:
    """SMTP, если задан ``SMTP_HOST``, иначе dev-режим (лог вместо письма)."""
    if settings.smtp_host.strip():
        return SMTPSender(settings)
    return DevEmailSender(settings.email_verify_ttl_hours)
