'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useSession } from '@/lib/session';
import { getProgress, getDueWords, reviewWord, type ReviewWord } from '@/lib/api';
import type { Locale } from '@/lib/i18n';

type Status = 'loading' | 'ready' | 'error' | 'unauth';

type ProgressData = {
  lessons: number;
  accuracy: number;
  streak: number;
  xp: number;
  weak: string[];
  strong: string[];
  nextTopic?: string | null;
};

function Stat({ label, value, children }: { label: string; value?: string | number; children?: ReactNode }) {
  return (
    <div className="rounded-3xl border border-ink-900/10 bg-ink-900/5 p-5 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      {value !== undefined && value !== null ? <p className="mt-2 text-lg font-bold text-accent-600">{value}</p> : null}
      {children}
    </div>
  );
}

function getStaticProgress(locale: Locale): ProgressData {
  const ru = locale !== 'en';
  return {
    lessons: 5,
    accuracy: 82,
    streak: 3,
    xp: 120,
    weak: ru ? ['Прошедшее время', 'Артикли'] : ['Past tense', 'Articles'],
    strong: ru ? ['Лексика путешествий', 'Вежливые фразы'] : ['Travel vocabulary', 'Polite phrases'],
    nextTopic: ru ? 'Путешествия: бронирование' : 'Travel: Booking',
  };
}

export default function ProgressPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('progress');
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<ProgressData | null>(null);
  const [due, setDue] = useState<ReviewWord[]>([]);
  const [reviewed, setReviewed] = useState<Set<string | number>>(new Set());

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
        const p = await getProgress();
        const d = await getDueWords();
        if (!active) return;
        setData({
          lessons: p.total_lessons ?? 0,
          accuracy: Math.round(p.accuracy ?? 0),
          streak: p.streak_days ?? 0,
          xp: p.xp ?? 0,
          weak: p.weak_areas ?? [],
          strong: p.strong_areas ?? [],
          nextTopic: p.next_topic ?? undefined,
        });
        setDue(Array.isArray(d) ? d : []);
        setStatus('ready');
      } catch {
        if (active) {
          setStatus('error');
        }
      }
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionLoading, user]);

  async function handleReview(id: string | number, quality: number) {
    if (user) {
      try {
        await reviewWord(id, quality);
      } catch {
        // ignore
      }
    }
    setReviewed((s) => new Set(s.add(id)));
  }

  const visibleDue = due.filter((w) => !reviewed.has(w.id));

  return (
    <main className="relative isolate min-h-[calc(100dvh-4rem)] overflow-hidden bg-paper-100 px-4 py-10 text-ink-900 sm:py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_20%_-10%,rgba(37,99,235,0.28),transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 right-[-10%] h-[380px] w-[380px] rounded-full bg-accent-500/10 blur-3xl"
      />

      <div className="relative mx-auto max-w-5xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-3xl font-bold text-ink-900">{t('title')}</h1>
          <Link
            href="/"
            className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-300 transition hover:text-ink-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/40"
          >
            {t('back')}
          </Link>
        </div>

        {status === 'loading' && <p className="mt-10 text-ink-700">...</p>}

        {status === 'ready' && data && (
          <>
            <div className="mt-8 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              <Stat label={t('lessons')} value={data.lessons} />
              <Stat label={t('accuracy')} value={`${data.accuracy}%`} />
              <Stat label={t('streak')} value={data.streak} />
              <Stat label={t('xp')} value={data.xp} />
              <Stat label={t('weak')} value={data.weak.length > 0 ? data.weak.join(', ') : '-'} />
              <Stat label={t('strong')} value={data.strong.length > 0 ? data.strong.join(', ') : '-'} />
            </div>

            {data.nextTopic && (
              <div className="mt-6 rounded-3xl border border-ink-900/10 bg-ink-900/5 p-6 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{t('nextTopic')}</p>
                <p className="mt-2 text-lg font-bold text-ink-900">{data.nextTopic}</p>
                <Link
                  href="/lesson"
                  className="mt-4 inline-flex items-center rounded-xl bg-accent-600 px-5 py-3 text-sm font-semibold text-ink-900 shadow-lg shadow-accent-900/40 transition hover:bg-accent-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/40"
                >
                  {t('startLesson')}
                </Link>
              </div>
            )}

            <div className="mt-8 rounded-3xl border border-ink-900/10 bg-ink-900/5 p-6 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur">
              <h2 className="text-lg font-bold text-ink-900">{t('dueTitle')}</h2>
              {visibleDue.length === 0 ? (
                <p className="mt-2 text-ink-700">{t('dueEmpty')}</p>
              ) : (
                <div className="mt-4 space-y-3">
                  {visibleDue.map((w) => (
                    <div
                      key={w.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-ink-900/10 bg-white/[0.03] p-4"
                    >
                      <div>
                        <p className="font-semibold text-ink-900">{w.word}</p>
                        <p className="text-sm text-ink-700">{w.translation}</p>
                        <p className="text-xs text-ink-500">{w.example}</p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleReview(w.id, 5)}
                          className="rounded-xl bg-emerald-500 px-4 py-2 text-xs font-semibold text-ink-900 shadow-sm transition hover:bg-emerald-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/40"
                        >
                          {t('know')}
                        </button>
                        <button
                          onClick={() => handleReview(w.id, 1)}
                          className="rounded-xl bg-amber-500 px-4 py-2 text-xs font-semibold text-ink-900 shadow-sm transition hover:bg-amber-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/40"
                        >
                          {t('dontKnow')}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

          </>
        )}

        {status === 'error' && (
          <div
            role="alert"
            className="mt-10 rounded-3xl border border-red-400/30 bg-red-500/10 p-6 text-red-200"
          >
            {t('error')}
          </div>
        )}
      </div>
    </main>
  );
}