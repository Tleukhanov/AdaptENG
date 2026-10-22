'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  apiFetch,
  getProgress,
  type GetProgressResponse,
  type ProfileData,
} from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useSession } from '@/lib/session';
import type { Locale } from '@/lib/i18n';

type Topic = { id: string; ru: string; en: string; emoji: string };

const TOPICS: Topic[] = [
  { id: 'travel', ru: 'Путешествия', en: 'Travel', emoji: '✈️' },
  { id: 'food', ru: 'Еда и кофе', en: 'Food and coffee', emoji: '☕' },
  { id: 'work', ru: 'Работа и карьера', en: 'Work and career', emoji: '💼' },
  { id: 'movies', ru: 'Кино и сериалы', en: 'Movies and series', emoji: '🎬' },
  { id: 'technology', ru: 'Технологии', en: 'Technology', emoji: '💻' },
  { id: 'smalltalk', ru: 'Small talk', en: 'Small talk', emoji: '💬' },
];

const LINKS = [
  { href: '/lesson', key: 'lesson', emoji: '🚀' },
  { href: '/chat', key: 'chat', emoji: '💬' },
  { href: '/progress', key: 'progress', emoji: '📈' },
  { href: '/achievements', key: 'achievements', emoji: '🏆' },
  { href: '/leaderboard', key: 'leaderboard', emoji: '🥇' },
  { href: '/#characters', key: 'characters', emoji: '🧑‍🏫' },
];

type MeResponse = {
  user: { first_name?: string; level?: string | null; quota_left?: number | null };
};

export default function MenuPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('menu');
  const ru = locale !== 'en';
  const [name, setName] = useState('');
  const [quota, setQuota] = useState<number | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [progress, setProgress] = useState<GetProgressResponse | null>(null);
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();

  useEffect(() => {
    if (sessionLoading) {
      return;
    }
    if (!user) {
      router.replace('/login');
      return;
    }
    let active = true;
    (async () => {
      try {
        const [me, prog] = await Promise.all([
          apiFetch<MeResponse>('/api/me'),
          getProgress(),
        ]);
        if (!active) return;
        setName(me?.user?.first_name ?? '');
        setQuota(me?.user?.quota_left ?? null);
        setLevel(me?.user?.level ?? null);
        setProgress(prog);
      } catch {
        // ошибки загрузки не блокируют меню
      }
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionLoading, user]);

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-500">AdaptENG</p>
          <h1 className="text-3xl font-bold text-slate-900">
            {t('hello')}{name ? `, ${name}` : ''} 👋
          </h1>
          <p className="mt-2 text-sm text-slate-600">{t('subtitle')}</p>
        </div>
        <Link href="/" className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-600 hover:text-blue-500">
          {t('home')}
        </Link>
      </div>

      <div className="mt-6 flex flex-wrap gap-3">
        <span className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700">
          🎯 {t('level')}: {level ?? '—'}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700">
          ⭐ {t('xp')}: {progress?.xp ?? 0}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700">
          🔥 {t('streak')}: {progress?.streak_days ?? 0}
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700">
          💎 {t('quota')}: {quota ?? '∞'}
        </span>
      </div>

      <Link
        href="/lesson/0"
        className="mt-6 flex items-center gap-4 rounded-3xl border border-blue-200 bg-blue-50/80 px-5 py-4 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md"
      >
        <span
          aria-hidden="true"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-cyan-400 text-2xl shadow-lg shadow-blue-500/30"
        >
          📚
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-base font-bold text-blue-950">{t('introLesson')}</span>
          <span className="mt-0.5 block text-xs leading-relaxed text-blue-800/70">
            {t('introLessonHint')}
          </span>
        </span>
        <span aria-hidden="true" className="text-lg text-blue-500">
          →
        </span>
      </Link>

      <Link
        href="/lesson"
        className="mt-6 block rounded-3xl bg-gradient-to-r from-blue-500 via-sky-500 to-cyan-400 p-6 text-white shadow-lg transition hover:opacity-95"
      >
        <p className="text-2xl font-bold">{t('startLesson')}</p>
        <p className="mt-1 text-sm text-blue-100">{t('startLessonHint')}</p>
      </Link>

      <section className="mt-8">
        <h2 className="text-lg font-bold text-slate-900">{t('topics')}</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {TOPICS.map((topic) => (
            <Link
              key={topic.id}
              href={`/lesson?topic=${encodeURIComponent(topic.en)}`}
              className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
            >
              <span className="text-xl">{topic.emoji}</span>
              {ru ? topic.ru : topic.en}
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-bold text-slate-900">{t('sections')}</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-2xl border border-slate-200 bg-white px-4 py-4 text-sm font-semibold text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
            >
              <span className="mr-2">{link.emoji}</span>
              {t(link.key)}
            </Link>
          ))}
        </div>
      </section>

      {user ? (
        <Link
          href="/onboarding?force=1"
          className="mt-4 inline-block text-sm font-semibold text-slate-500 hover:text-blue-600"
        >
          {t('toOnboarding')}
        </Link>
      ) : null}
    </main>
  );
}
