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
  { href: '/vocab', key: 'vocab', emoji: '📖' },
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
    <main className="relative isolate min-h-[calc(100dvh-4rem)] overflow-hidden bg-[linear-gradient(160deg,#0b1220_0%,#111c33_100%)] px-4 py-10 text-slate-100 sm:py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_20%_-10%,rgba(37,99,235,0.28),transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 right-[-10%] h-[380px] w-[380px] rounded-full bg-sky-500/10 blur-3xl"
      />

      <div className="relative mx-auto max-w-5xl">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-sky-300">AdaptENG</p>
            <h1 className="text-3xl font-bold text-white">
              {t('hello')}{name ? `, ${name}` : ''} 👋
            </h1>
            <p className="mt-2 text-sm text-slate-400">{t('subtitle')}</p>
          </div>
          <Link
            href="/"
            className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-300 transition hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
          >
            {t('home')}
          </Link>
        </div>

        <div className="mt-6 flex flex-wrap gap-3">
          <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-300 backdrop-blur">
            🎯 {t('level')}: <span className="text-sky-300">{level ?? '—'}</span>
          </span>
          <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-300 backdrop-blur">
            ⭐ {t('xp')}: <span className="text-sky-300">{progress?.xp ?? 0}</span>
          </span>
          <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-300 backdrop-blur">
            🔥 {t('streak')}: <span className="text-sky-300">{progress?.streak_days ?? 0}</span>
          </span>
          <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-300 backdrop-blur">
            💎 {t('quota')}: <span className="text-sky-300">{quota ?? '∞'}</span>
          </span>
        </div>

        <Link
          href="/lesson/0"
          className="mt-6 flex items-center gap-4 rounded-3xl border border-white/10 bg-white/5 px-5 py-4 shadow-[0_20px_50px_-30px_rgba(2,6,23,0.9)] backdrop-blur transition hover:-translate-y-0.5 hover:border-blue-400/40 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
        >
          <span
            aria-hidden="true"
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-blue-600 text-2xl shadow-lg shadow-blue-900/40"
          >
            📚
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-base font-bold text-white">{t('introLesson')}</span>
            <span className="mt-0.5 block text-xs leading-relaxed text-slate-400">
              {t('introLessonHint')}
            </span>
          </span>
          <span aria-hidden="true" className="text-lg text-sky-300">
            →
          </span>
        </Link>

        <Link
          href="/lesson"
          className="mt-6 block rounded-3xl bg-blue-600 p-6 text-white shadow-lg shadow-blue-900/40 transition hover:-translate-y-0.5 hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
        >
          <p className="text-2xl font-bold">{t('startLesson')}</p>
          <p className="mt-1 text-sm text-blue-100">{t('startLessonHint')}</p>
        </Link>

        <section className="mt-8">
          <h2 className="text-lg font-bold text-white">{t('topics')}</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {TOPICS.map((topic) => (
              <Link
                key={topic.id}
                href={`/lesson?topic=${encodeURIComponent(topic.en)}`}
                className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-slate-200 shadow-[0_20px_50px_-34px_rgba(2,6,23,0.9)] backdrop-blur transition hover:-translate-y-0.5 hover:border-blue-400/40 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
              >
                <span className="text-xl">{topic.emoji}</span>
                {ru ? topic.ru : topic.en}
              </Link>
            ))}
          </div>
        </section>

        <section className="mt-8">
          <h2 className="text-lg font-bold text-white">{t('sections')}</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm font-semibold text-slate-200 shadow-[0_20px_50px_-34px_rgba(2,6,23,0.9)] backdrop-blur transition hover:-translate-y-0.5 hover:border-blue-400/40 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
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
            className="mt-6 inline-block rounded-lg text-sm font-semibold text-slate-400 transition hover:text-sky-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
          >
            {t('toOnboarding')}
          </Link>
        ) : null}
      </div>
    </main>
  );
}
