'use client';

import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { ApiError, errorMessage, login, register } from '@/lib/api';
import { useSession } from '@/lib/session';

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
    <main className="mx-auto flex min-h-[70vh] w-full max-w-md flex-col justify-center px-4 py-10">
      <h1 className="text-2xl font-bold text-slate-900">{t('auth.title')}</h1>
      <p className="mt-2 text-sm text-slate-500">{t('auth.subtitle')}</p>

      <div className="mt-6 flex gap-1 rounded-xl bg-slate-100 p-1">
        <button
          type="button"
          onClick={() => setMode('login')}
          className={`min-h-[44px] flex-1 rounded-lg text-sm font-medium transition ${
            mode === 'login' ? 'bg-white text-slate-900 shadow' : 'text-slate-500'
          }`}
        >
          {t('auth.loginBtn')}
        </button>
        <button
          type="button"
          onClick={() => setMode('register')}
          className={`min-h-[44px] flex-1 rounded-lg text-sm font-medium transition ${
            mode === 'register' ? 'bg-white text-slate-900 shadow' : 'text-slate-500'
          }`}
        >
          {t('auth.registerBtn')}
        </button>
      </div>

      <form onSubmit={submit} className="mt-6 space-y-4">
        {mode === 'register' && (
          <label className="block">
            <span className="text-sm font-medium text-slate-700">{t('auth.name')}</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="name"
              maxLength={80}
              className="mt-1 min-h-[44px] w-full rounded-lg border border-slate-300 px-3 text-slate-900 outline-none focus:border-blue-500"
            />
          </label>
        )}

        <label className="block">
          <span className="text-sm font-medium text-slate-700">{t('auth.email')}</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="you@example.com"
            className="mt-1 min-h-[44px] w-full rounded-lg border border-slate-300 px-3 text-slate-900 outline-none focus:border-blue-500"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-slate-700">{t('auth.password')}</span>
          <input
            type="password"
            required
            minLength={mode === 'register' ? 8 : 1}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            className="mt-1 min-h-[44px] w-full rounded-lg border border-slate-300 px-3 text-slate-900 outline-none focus:border-blue-500"
          />
          {mode === 'register' && (
            <span className="mt-1 block text-xs text-slate-400">{t('auth.passwordHint')}</span>
          )}
        </label>

        {error && (
          <div role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          className="adapteng-gradient min-h-[44px] w-full rounded-lg px-4 py-2 font-semibold text-white transition disabled:opacity-60"
        >
          {busy ? t('auth.working') : mode === 'login' ? t('auth.loginBtn') : t('auth.registerBtn')}
        </button>
      </form>

      <p className="mt-6 text-center text-xs text-slate-400">
        {t('auth.privacyNote')}{' '}
        <Link href="/" className="underline">
          {t('auth.backHome')}
        </Link>
      </p>
    </main>
  );
}
