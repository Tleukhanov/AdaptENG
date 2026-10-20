'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { getToken, getProgress, getDueWords, reviewWord, type ReviewWord } from '@/lib/api';
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
    <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      {value !== undefined && value !== null ? <p className="mt-2 text-lg font-bold text-slate-900">{value}</p> : null}
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
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<ProgressData | null>(null);
  const [due, setDue] = useState<ReviewWord[]>([]);
  const [reviewed, setReviewed] = useState<Set<string | number>>(new Set());

  const hasToken = () => {
    if (typeof window === 'undefined') {
      return false;
    }
    return !!getToken();
  };

  useEffect(() => {
    if (!hasToken()) {
      setData(getStaticProgress(locale));
      setStatus('unauth');
      setDue([
        { id: '1', word: 'destination', translation: locale === 'en' ? 'destination' : 'пункт назначения', example: locale === 'en' ? 'Our destination is Paris.' : 'Наш пункт назначения — Париж.' },
        { id: '2', word: 'boarding pass', translation: locale === 'en' ? 'boarding pass' : 'посадочный талон', example: locale === 'en' ? 'Show your boarding pass.' : 'Покажите посадочный талон.' },
      ]);
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
  }, [locale]);

  async function handleReview(id: string | number, quality: number) {
    if (hasToken()) {
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
    <main className="mx-auto max-w-5xl px-4 py-12">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-bold text-slate-900">{t('title')}</h1>
        <Link href="/" className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-indigo-600 hover:text-indigo-500">
          {t('back')}
        </Link>
      </div>

      {status === 'loading' && <p className="mt-10 text-slate-600">...</p>}

      {(status === 'ready' || status === 'unauth') && data && (
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
            <div className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t('nextTopic')}</p>
              <p className="mt-2 text-lg font-bold text-slate-900">{data.nextTopic}</p>
              <Link href="/lesson" className="mt-4 inline-flex items-center rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
                {t('startLesson')}
              </Link>
            </div>
          )}

          <div className="mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-bold text-slate-900">{t('dueTitle')}</h2>
            {visibleDue.length === 0 ? (
              <p className="mt-2 text-slate-600">{t('dueEmpty')}</p>
            ) : (
              <div className="mt-4 space-y-3">
                {visibleDue.map((w) => (
                  <div key={w.id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 p-4">
                    <div>
                      <p className="font-semibold text-slate-900">{w.word}</p>
                      <p className="text-sm text-slate-600">{w.translation}</p>
                      <p className="text-xs text-slate-500">{w.example}</p>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => handleReview(w.id, 5)} className="rounded-xl bg-emerald-500 px-4 py-2 text-xs font-semibold text-white shadow-sm">
                        {t('know')}
                      </button>
                      <button onClick={() => handleReview(w.id, 1)} className="rounded-xl bg-amber-500 px-4 py-2 text-xs font-semibold text-white shadow-sm">
                        {t('dontKnow')}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {status === 'unauth' && (
            <p className="mt-4 text-sm text-slate-600">{t('demoHint')}</p>
          )}
        </>
      )}

      {status === 'error' && (
        <div className="mt-10 rounded-3xl border border-red-200 bg-red-50 p-6 text-red-700">
          {t('error')}
        </div>
      )}
    </main>
  );
}