'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { getAchievements, type AchievementItem, type LevelInfo } from '@/lib/api';
import type { Locale } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { useRouter } from 'next/navigation';

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
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<Data | null>(null);

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
  }, [sessionLoading, user]);

  const earned: AchievementItem[] = [];
  const locked: AchievementItem[] = [];
  (data?.achievements ?? []).forEach((a) => (a.earned ? earned : locked).push(a));

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
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-3xl font-bold text-white">{t('title')}</h1>
          <Link
            href="/"
            className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-300 transition hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
          >
            {t('back')}
          </Link>
        </div>

        {status === 'loading' && <p className="mt-10 text-slate-300">...</p>}

        {status === 'ready' && data && (
          <>
            <div className="mt-8 flex items-center gap-5 rounded-3xl border border-white/10 bg-white/5 p-6 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur">
              <span className="text-4xl">{data.level.emoji}</span>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {t('level')} · <span className="text-sky-300">{t('xp')} {data.level.xp}</span>
                </p>
                <p className="text-xl font-bold text-white">{data.level.name}</p>
                <p className="mt-1 text-sm text-slate-300">
                  {data.level.next_level
                    ? t('nextLevel', { next: data.level.next_level, xp: data.level.xp_needed ?? 0 })
                    : t('maxLevel')}
                </p>
              </div>
            </div>

            {earned.length > 0 && (
              <section className="mt-8">
                <h2 className="text-lg font-bold text-white">{t('earned')}</h2>
                <div className="mt-4 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
                  {earned.map((a, i) => (
                    <div
                      key={a.id}
                      className="rounded-3xl border border-emerald-400/25 bg-emerald-500/10 p-5 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur"
                    >
                      <p className="text-3xl">{a.emoji || DEFAULT_EMOJI[i % DEFAULT_EMOJI.length]}</p>
                      <p className="mt-2 font-semibold text-white">{a.name}</p>
                      <p className="mt-1 text-sm text-slate-300">{a.description}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {locked.length > 0 && (
              <section className="mt-8">
                <h2 className="text-lg font-bold text-white">{t('locked')}</h2>
                <div className="mt-4 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
                  {locked.map((a, i) => (
                    <div
                      key={a.id}
                      className="rounded-3xl border border-white/10 bg-white/5 p-5 opacity-60 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur"
                    >
                      <p className="text-3xl grayscale">{a.emoji || DEFAULT_EMOJI[i % DEFAULT_EMOJI.length]}</p>
                      <p className="mt-2 font-semibold text-slate-400">{a.name}</p>
                      <p className="mt-1 text-xs text-slate-400">{a.description}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}

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