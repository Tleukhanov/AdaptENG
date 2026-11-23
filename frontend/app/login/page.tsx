'use client';

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { ApiError, errorMessage, login, register } from '@/lib/api';
import { useSession } from '@/lib/session';

const FOCUS_RING =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#14110f]';

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
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(800px_420px_at_50%_-10%,rgba(194,65,12,0.18)_0%,transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 top-1/3 h-[320px] w-[320px] rounded-full bg-accent-500/10 blur-3xl"
      />

      <div className="relative w-full max-w-md">
        <div className="panel glow-soft p-6 sm:p-8">
          <span aria-hidden="true" className="adapteng-gradient block h-1 w-14 rounded-full" />
          <h1 className="mt-4 font-display text-2xl font-semibold text-paper-50">
            {t('auth.title')}
          </h1>
          <p className="mt-1 text-sm text-paper-300">{t('auth.subtitle')}</p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === 'register' ? (
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-paper-300">
                  {t('auth.name')}
                </span>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="field mt-2"
                  placeholder={t('auth.namePlaceholder')}
                  autoComplete="name"
                />
              </label>
            ) : null}

            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-paper-300">
                {t('auth.email')}
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="field mt-2"
                placeholder="you@example.com"
                autoComplete="email"
                required
              />
            </label>

            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-paper-300">
                {t('auth.password')}
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="field mt-2"
                placeholder="••••••••"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={8}
              />
            </label>

            {error ? (
              <div
                role="alert"
                className="rounded-xl border border-accent-600/30 bg-accent-600/10 px-4 py-3 text-sm text-accent-100"
              >
                {error}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={busy}
              className="inline-flex min-h-[48px] w-full items-center justify-center rounded-full bg-accent-600 px-6 py-3 text-sm font-semibold text-paper-50 transition hover:bg-accent-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy
                ? t('auth.submitting')
                : mode === 'login'
                  ? t('auth.submitLogin')
                  : t('auth.submitRegister')}
            </button>
          </form>

          <div className="mt-6 flex items-center justify-between text-sm">
            <button
              type="button"
              onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
              className="font-semibold text-accent-500 transition hover:text-accent-600"
            >
              {mode === 'login' ? t('auth.switchToRegister') : t('auth.switchToLogin')}
            </button>
            <Link
              href="/"
              className="text-paper-300 transition hover:text-paper-50"
            >
              {t('auth.backHome')}
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
