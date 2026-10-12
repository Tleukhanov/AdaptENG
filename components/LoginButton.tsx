'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';

const API = process.env.NEXT_PUBLIC_API_URL ?? '';
const TG_USERNAME = process.env.NEXT_PUBLIC_TG_BOT_USERNAME ?? '';
const TOKEN_KEY = 'adapteng_token';

type TelegramUser = {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  auth_date?: number;
  hash?: string;
  photo_url?: string;
};

type TelegramWindow = Window & {
  onTelegramAuth?: (user: TelegramUser) => Promise<void>;
};

export default function LoginButton({ locale }: { locale: string }) {
  const t = useTranslations('login');
  const tRoot = useTranslations();
  const [toast, setToast] = useState<string | null>(null);
  const [showWidget, setShowWidget] = useState(false);
  const widgetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const telegramWindow = window as TelegramWindow;
    if (telegramWindow.onTelegramAuth) {
      return;
    }
    telegramWindow.onTelegramAuth = async (user: TelegramUser) => {
      try {
        const response = await fetch(`${API}/api/auth/tg`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(user),
        });
        const data = (await response.json()) as { token?: string; error?: string };
        if (data.token) {
          window.localStorage.setItem(TOKEN_KEY, data.token);
          window.location.href = '/dashboard';
        } else {
          window.alert(data.error ?? 'Auth failed');
        }
      } catch {
        window.alert('Auth failed');
      }
    };
  }, []);

  useEffect(() => {
    if (!showWidget || !widgetRef.current || !TG_USERNAME) {
      return;
    }
    const container = widgetRef.current;
    container.innerHTML = '';
    const script = document.createElement('script');
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.async = true;
    script.setAttribute('data-telegram-login', TG_USERNAME);
    script.setAttribute('data-size', 'large');
    script.setAttribute('data-onauth', 'onTelegramAuth(user)');
    script.setAttribute('data-request-access', 'write');
    container.appendChild(script);
  }, [showWidget]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const showDemoToast = useCallback(() => {
    setToast(tRoot('demo.toast'));
  }, [tRoot]);

  const handleTelegram = useCallback(() => {
    if (!API) {
      showDemoToast();
      return;
    }
    setShowWidget(true);
  }, [showDemoToast]);

  return (
    <div className="flex flex-col gap-3" data-locale={locale}>
      <button
        type="button"
        onClick={handleTelegram}
        className="w-full rounded-xl bg-gradient-to-r from-indigo-500 via-violet-500 to-pink-500 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-200 transition hover:opacity-95"
      >
        {t('telegram')}
      </button>
      <div ref={widgetRef} />
      <button
        type="button"
        onClick={showDemoToast}
        className="w-full rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
      >
        {t('demo')}
      </button>
      {toast ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-xl">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
