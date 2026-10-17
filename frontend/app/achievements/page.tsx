'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { getAchievements, getToken, type AchievementItem, type LevelInfo } from '@/lib/api';
import type { Locale } from '@/lib/i18n';

type Status = 'loading' | 'ready' | 'error' | 'unauth';

type Data = {
  level: LevelInfo;
  achievements: AchievementItem[];
};

function getStaticAchievements(locale: Locale): Data {
  const ru = locale !== 'en';
  const label = (id: string, nameRu: string, nameEn: string, earned: boolean) => ({
    id,
    name: ru ? nameRu : nameEn,
    emoji: '',
    description: '',
    condition: '',
    earned,
  });
  return {
    level: { name: ru ? 'Ученик' : 'Apprentice', emoji: '📗', xp: 120, next_level: ru ? 'Знаток' : 'Expert', xp_needed: 180 },
    achievements: [
      label('first_lesson', 'Первый шаг', 'First step', true),
      label('five_lessons', 'Пять уроков', 'Five lessons', true),
      label('ten_lessons', 'Десять уроков', 'Ten lessons', false),
      label('first_correct', 'Безупречно', 'Perfect', true),
      label('fifty_turns', '50 реплик', '50 turns', false),
      label('streak_3', 'Три дня подряд', 'Three days in a row', true),
      label('streak_7', 'Неделя без перерыва', 'Week streak', false),
      label('accuracy_80', 'Точный стрелок', 'Sharp shooter', false),
      label('xp_100', '100 XP', '100 XP', true),
      label('xp_500', '500 XP', '500 XP', false),
    ],
  };
}

const DEFAULT_EMOJI = ['👶', '📚', '🏆', '✅', '💬', '🔥', '🌟', '🎯', '⭐', '🌠', '💎', '🧠', '💯', '🎓', '🏅'];

export default function AchievementsPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('achievements');
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<Data | null>(null);

  const hasToken = () => {
    if (typeof window === 'undefined') {
      return false;
    }
    return !!getToken();
  };

  useEffect(() => {
    if (!hasToken()) {
      setData(getStaticAchievements(locale));
      setStatus('unauth');
      return;
    }
    let active = true;
    (async () => {
      try {
        const res = await getAchievements();
        if (!active) return;
        setData({
          level: res.level ?? { name: '—', emoji: '🌱', xp: 0 },
          achievements: Array.isArray(res.achievements) ? res.achievements : [],
        });
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

  const earned: AchievementItem[] = [];
  const locked: AchievementItem[] = [];
  (data?.achievements ?? []).forEach((a) => (a.earned ? earned : locked).push(a));

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
          <div className="mt-8 flex items-center gap-5 rounded-3xl border border-slate-200 bg-gradient-to-r from-indigo-50 to-violet-50 p-6 shadow-sm">
            <span className="text-4xl">{data.level.emoji}</span>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {t('level')} · {t('xp')} {data.level.xp}
              </p>
              <p className="text-xl font-bold text-slate-900">{data.level.name}</p>
              <p className="mt-1 text-sm text-slate-600">
                {data.level.next_level
                  ? t('nextLevel', { next: data.level.next_level, xp: data.level.xp_needed ?? 0 })
                  : t('maxLevel')}
              </p>
            </div>
          </div>

          {earned.length > 0 && (
            <section className="mt-8">
              <h2 className="text-lg font-bold text-slate-900">{t('earned')}</h2>
<div className="mt-4 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
            {earned.map((a, i) => (
                  <div key={a.id} className="rounded-3xl border border-emerald-200 bg-emerald-50/60 p-5 shadow-sm">
                    <p className="text-3xl">{a.emoji || DEFAULT_EMOJI[i % DEFAULT_EMOJI.length]}</p>
                    <p className="mt-2 font-semibold text-slate-900">{a.name}</p>
                    <p className="mt-1 text-sm text-slate-600">{a.description}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {locked.length > 0 && (
            <section className="mt-8">
              <h2 className="text-lg font-bold text-slate-900">{t('locked')}</h2>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
                {locked.map((a, i) => (
                  <div key={a.id} className="rounded-3xl border border-slate-200 bg-white p-5 opacity-70 shadow-sm">
                    <p className="text-3xl grayscale">{a.emoji || DEFAULT_EMOJI[i % DEFAULT_EMOJI.length]}</p>
                    <p className="mt-2 font-semibold text-slate-400">{a.name}</p>
                    <p className="mt-1 text-xs text-slate-500">{a.description}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {status === 'unauth' && <p className="mt-4 text-sm text-slate-600">{t('demoHint')}</p>}
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