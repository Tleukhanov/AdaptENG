'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  errorMessage,
  getNotificationSettings,
  updateNotificationSettings,
} from '@/lib/api';

type LoadState = 'loading' | 'ready' | 'unavailable';
type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/**
 * Напоминания на почту: один переключатель, значение хранится на бэкенде
 * (`/api/me/notifications`). Письмо приходит раз в день и только если
 * ученик не занимался, поэтому подпись объясняет это прямым текстом.
 *
 * Если эндпоинт ещё не развёрнут (404/501) — блок остаётся на месте, но
 * переключатель выключен и показывает мягкое «пока недоступно», а не ошибку.
 */
export default function NotificationSettings() {
  const t = useTranslations('notifications');
  const [load, setLoad] = useState<LoadState>('loading');
  const [save, setSave] = useState<SaveState>('idle');
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const data = await getNotificationSettings();
        if (!active) {
          return;
        }
        setEnabled(data.email_reminders === true);
        setLoad('ready');
      } catch {
        if (active) {
          setLoad('unavailable');
        }
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function toggle() {
    if (load !== 'ready' || save === 'saving') {
      return;
    }
    const next = !enabled;
    const previous = enabled;
    // Оптимистично: переключатель реагирует сразу, при ошибке откатываем.
    setEnabled(next);
    setSave('saving');
    setError(null);
    try {
      const data = await updateNotificationSettings({ email_reminders: next });
      setEnabled(data.email_reminders === true);
      setSave('saved');
    } catch (err) {
      setEnabled(previous);
      setSave('error');
      setError(errorMessage(err, t('error')));
    }
  }

  // «Сохранено» — короткое подтверждение, а не постоянный статус.
  useEffect(() => {
    if (save !== 'saved') {
      return;
    }
    const timer = window.setTimeout(() => setSave('idle'), 2500);
    return () => window.clearTimeout(timer);
  }, [save]);

  const disabled = load !== 'ready' || save === 'saving';
  const checked = load === 'ready' && enabled;
  const descriptionId = 'notifications-hint';
  const stateText =
    load === 'unavailable'
      ? t('unavailable')
      : save === 'saving'
        ? t('saving')
        : save === 'error'
          ? (error ?? t('error'))
          : save === 'saved'
            ? t('saved')
            : t('hint');

  return (
    <section aria-labelledby="notifications-title" className="panel p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 id="notifications-title" className="text-sm font-semibold text-white">
            {t('title')}
          </h2>
          <p id={descriptionId} className="mt-1 text-xs leading-relaxed text-slate-400">
            {t('hint')}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          aria-labelledby="notifications-title"
          aria-describedby={descriptionId}
          aria-busy={save === 'saving'}
          disabled={disabled}
          onClick={() => void toggle()}
          className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:cursor-not-allowed disabled:opacity-50 ${
            checked
              ? 'border-blue-400/60 bg-blue-500'
              : 'border-white/15 bg-white/10 hover:bg-white/15'
          }`}
        >
          <span className="sr-only">{t('toggle')}</span>
          <span
            aria-hidden="true"
            className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${
              checked ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
      </div>

      <p
        role={save === 'error' || load === 'unavailable' ? 'status' : undefined}
        className={`mt-3 text-[11px] leading-relaxed ${
          save === 'error' || load === 'unavailable'
            ? 'text-amber-200/90'
            : save === 'saved'
              ? 'text-emerald-300/90'
              : 'text-slate-500'
        }`}
      >
        {load === 'loading' ? t('loading') : stateText}
      </p>
    </section>
  );
}
