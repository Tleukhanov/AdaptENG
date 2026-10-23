'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';

/** Chrome/Edge `beforeinstallprompt` — не входит в lib.dom.d.ts. */
type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
};

const DISMISS_KEY = 'adapteng:pwa-install-dismissed';

/**
 * PWA-обвязка приложения:
 *  - регистрирует service worker (`/sw.js`) после `load`;
 *  - показывает аккуратную кнопку установки по `beforeinstallprompt`;
 *  - рисует тонкую полоску «Нет соединения» при потере сети.
 *
 * Регистрация SW только в production: в dev кэш статики ломает HMR.
 */
export default function PwaProvider() {
  const t = useTranslations();
  const [installEvent, setInstallEvent] = useState<InstallPromptEvent | null>(null);
  const [offline, setOffline] = useState(false);

  // Service worker: регистрируем после полной загрузки, чтобы не конкурировать
  // с первым рендером и запросами страницы.
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production' || !('serviceWorker' in navigator)) {
      return;
    }
    const register = () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
        // Офлайн-режим — не критичная функция: молча живём без него.
      });
    };
    if (document.readyState === 'complete') {
      register();
      return;
    }
    window.addEventListener('load', register, { once: true });
    return () => window.removeEventListener('load', register);
  }, []);

  // online/offline: начальное значение — только на клиенте, чтобы не было
  // расхождения с серверным HTML.
  useEffect(() => {
    const sync = () => setOffline(!navigator.onLine);
    sync();
    window.addEventListener('online', sync);
    window.addEventListener('offline', sync);
    return () => {
      window.removeEventListener('online', sync);
      window.removeEventListener('offline', sync);
    };
  }, []);

  // Полоска фиксирована внизу — освобождаем место, чтобы не перекрывать контент.
  useEffect(() => {
    document.body.classList.toggle('is-offline', offline);
    return () => document.body.classList.remove('is-offline');
  }, [offline]);

  useEffect(() => {
    const onBeforeInstall = (event: Event) => {
      event.preventDefault();
      if (window.localStorage.getItem(DISMISS_KEY) === '1') {
        return;
      }
      if (window.matchMedia('(display-mode: standalone)').matches) {
        return;
      }
      setInstallEvent(event as InstallPromptEvent);
    };
    const onInstalled = () => setInstallEvent(null);

    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  function dismiss() {
    setInstallEvent(null);
    try {
      window.localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      // Приватный режим без localStorage — просто скрываем на эту сессию.
    }
  }

  async function install() {
    if (!installEvent) {
      return;
    }
    try {
      await installEvent.prompt();
      const choice = await installEvent.userChoice;
      setInstallEvent(null);
      if (choice.outcome === 'dismissed') {
        dismiss();
      }
    } catch {
      dismiss();
    }
  }

  return (
    <>
      <div
        role="status"
        aria-live="polite"
        className={`fixed inset-x-0 bottom-0 z-50 flex items-center justify-center gap-2 bg-amber-500/95 px-4 py-1.5 text-xs font-medium text-[#0b1220] transition-transform duration-300 ${
          offline ? 'translate-y-0' : 'pointer-events-none translate-y-full'
        }`}
      >
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#0b1220]" />
        {offline ? t('pwa.offline') : null}
      </div>

      {installEvent ? (
        <div className="fixed inset-x-4 bottom-4 z-50 sm:left-auto sm:w-80">
          <div className="panel flex items-start gap-3 p-4 shadow-2xl shadow-blue-950/60">
            <span
              aria-hidden
              className="adapteng-gradient flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-sm font-bold text-white"
            >
              A
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white">{t('pwa.installTitle')}</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-300">{t('pwa.installHint')}</p>
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={install}
                  className="inline-flex min-h-[36px] items-center justify-center rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
                >
                  {t('pwa.install')}
                </button>
                <button
                  type="button"
                  onClick={dismiss}
                  aria-label={t('pwa.dismiss')}
                  className="inline-flex min-h-[36px] items-center justify-center rounded-lg px-3 py-1.5 text-xs font-medium text-slate-400 transition hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
                >
                  {t('pwa.dismiss')}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
