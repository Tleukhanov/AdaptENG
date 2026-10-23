'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { apiFetch, ApiError, errorMessage } from '@/lib/api';
import { useSession } from '@/lib/session';

type MeResponse = {
  user: {
    email?: string;
    email_verified?: boolean;
  };
};

/**
 * Мягкое напоминание подтвердить email.
 *
 * Показывается только залогиненным с неподтверждённым адресом; не блокирует
 * продукт. Отправка письма — по кнопке (бэкенд ограничивает 1 раз в минуту).
 */
export default function VerifyEmailBanner() {
  const t = useTranslations('verify');
  const { user } = useSession();
  const [verified, setVerified] = useState(true);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!user) {
      return;
    }
    let active = true;
    (async () => {
      try {
        const me = await apiFetch<MeResponse>('/api/me');
        if (!active) return;
        setEmail(me.user.email ?? '');
        setVerified(me.user.email_verified !== false);
      } catch {
        // не блокируем страницу из-за баннера
      }
    })();
    return () => {
      active = false;
    };
  }, [user]);

  if (!user || verified) {
    return null;
  }

  async function send() {
    setBusy(true);
    setError('');
    try {
      await apiFetch('/api/auth/verify/request', { method: 'POST' });
      setSent(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError(t('tooOften'));
      } else {
        setError(errorMessage(err, t('sendError')));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-sky-300/25 bg-sky-400/10 px-4 py-3 text-sm text-sky-50">
      <p className="font-medium">{t('bannerTitle')}</p>
      <p className="mt-1 text-sky-100/80">
        {sent ? t('bannerSent', { email }) : t('bannerText', { email })}
      </p>
      {error ? <p className="mt-1 text-rose-200">{error}</p> : null}
      {!sent ? (
        <button
          type="button"
          onClick={send}
          disabled={busy}
          className="mt-2 inline-flex min-h-[36px] items-center rounded-lg bg-sky-500/20 px-3 py-2 text-xs font-semibold text-sky-50 transition hover:bg-sky-500/30 disabled:opacity-60"
        >
          {busy ? t('sending') : t('send')}
        </button>
      ) : null}
    </div>
  );
}
