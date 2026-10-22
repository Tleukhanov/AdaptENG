'use client';

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { ApiError, errorMessage, login, register } from '@/lib/api';
import { useSession } from '@/lib/session';

const FOCUS_RING =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]';

export default function LoginPage() {
  const t = useTranslations();
  const router = useRouter();
  const { refresh } = useSession();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (mode === 'login') {
        await login(email.trim(), password);
      } else {
        await register(email.trim(), password, name.trim());
      }
      // Обновляем сессию в контексте ДО перехода: иначе целевая страница
      // увидит "пользователя нет" и вернёт на страницу входа.
      await refresh();
      router.push('/menu');
      router.refresh();
    } catch (err) {
      setError(errorMessage(err, t('auth.error')));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-dark relative isolate flex min-h-[calc(100vh-4rem)] items-center justify-center overflow-hidden px-4 py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(800px_420px_at_50%_-10%,#17386b_0%,transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 top-1/3 h-[320px] w-[320px] rounded-full bg-blue-500/10 blur-3xl"
      />

      <div className="relative w-full max-w-md">
        <div className="panel glow-soft p-6 sm:p-8">
          <span aria-hidden="true" className="adapteng-gradient block h-1 w-14 rounded-full" />
          <h1 className="mt-4 text-2xl font-bold text-white">{t('auth.title')}</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">{t('auth.subtitle')}</p>

          <div className="mt-6 flex gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
            <button
              type="button"
              aria-pressed={mode === 'login'}
              onClick={() => setMode('login')}
              className={`min-h-[44px] flex-1 rounded-lg text-sm font-semibold transition ${FOCUS_RING} ${
                mode === 'login'
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/40'
                  : 'text-slate-300 hover:bg-white/5 hover:text-white'
              }`}
            >
              {t('auth.loginBtn')}
            </button>
            <button
              type="button"
              aria-pressed={mode === 'register'}
              onClick={() => setMode('register')}
              className={`min-h-[44px] flex-1 rounded-lg text-sm font-semibold transition ${FOCUS_RING} ${
                mode === 'register'
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/40'
                  : 'text-slate-300 hover:bg-white/5 hover:text-white'
              }`}
            >
              {t('auth.registerBtn')}
            </button>
          </div>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === 'register' && (
              <label className="block">
                <span className="text-sm font-medium text-slate-300">{t('auth.name')}</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  maxLength={80}
                  className="field mt-1"
                />
              </label>
            )}

            <label className="block">
              <span className="text-sm font-medium text-slate-300">{t('auth.email')}</span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="you@example.com"
                className="field mt-1"
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-300">{t('auth.password')}</span>
              <input
                type="password"
                required
                minLength={mode === 'register' ? 8 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                className="field mt-1"
              />
              {mode === 'register' && (
                <span className="mt-1 block text-xs text-slate-400">{t('auth.passwordHint')}</span>
              )}
            </label>

            {error && (
              <div
                role="alert"
                className="rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-200"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className={`inline-flex min-h-[48px] w-full items-center justify-center rounded-xl bg-blue-600 px-4 py-2 font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 ${FOCUS_RING} disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-slate-400 disabled:shadow-none`}
            >
              {busy ? t('auth.working') : mode === 'login' ? t('auth.loginBtn') : t('auth.registerBtn')}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          {t('auth.privacyNote')}{' '}
          <Link
            href="/"
            className={`rounded text-sky-300 underline decoration-sky-300/40 underline-offset-4 transition hover:text-sky-200 ${FOCUS_RING}`}
          >
            {t('auth.backHome')}
          </Link>
        </p>
      </div>
    </main>
  );
}
