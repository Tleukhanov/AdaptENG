'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { sampleCharacters } from '@/lib/characters';
import type { Locale } from '@/lib/i18n';
import { apiFetch } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useSession } from '@/lib/session';
import VerifyEmailBanner from '@/components/VerifyEmailBanner';

type MeResponse = {
  user: {
    id: number;
    tg_id: number;
    level: string | null;
    character?: string;
    interests?: string[];
    quota_left?: number | null;
  };
  character?: { id: string; name: string; tagline?: string; emoji?: string };
};

const demoProfile: MeResponse = {
  user: {
    id: 0,
    tg_id: 0,
    level: 'B1',
    character: 'chill',
    interests: ['music', 'travel', 'technology'],
    quota_left: 5,
  },
  character: { id: 'chill', name: 'Chill Teacher', emoji: '😎' },
};

type Status = 'loading' | 'ready' | 'error' | 'unauth';

function Stat({
  label,
  value,
  children,
}: {
  label: string;
  value?: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-5 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      {value ? <p className="mt-2 text-lg font-bold text-sky-300">{value}</p> : null}
      {children}
    </div>
  );
}

export default function DashboardPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('dashboard');
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<MeResponse | null>(null);
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
        const json = await apiFetch<MeResponse>('/api/me');
        if (active) {
          setData(json);
          setStatus('ready');
        }
      } catch {
        if (active) {
          setStatus('error');
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [sessionLoading, user]);

  const characterId = data?.user?.character;
  const fallbackCharacter = sampleCharacters(locale).find(
    (item) => item.id === characterId,
  );
  const characterName =
    data?.character?.name ?? fallbackCharacter?.name ?? characterId ?? '—';
  const interests = data?.user?.interests ?? [];

  const cards: { title: string; description: string; href?: string }[] = [
    { title: t('menu'), description: t('menuDesc'), href: '/menu' },
    { title: t('lesson'), description: t('lessonDesc'), href: '/lesson' },
    { title: t('progress'), description: t('progressDesc'), href: '/progress' },
    { title: t('achievements'), description: t('achievementsDesc'), href: '/achievements' },
    { title: t('leaderboard'), description: t('leaderboardDesc'), href: '/leaderboard' },
    { title: t('characters'), description: t('charactersDesc'), href: '/#characters' },
  ];

  return (
    <main className="relative isolate min-h-[calc(100dvh-4rem)] overflow-hidden bg-[linear-gradient(160deg,#0b1220_0%,#111c33_100%)] px-4 py-10 text-slate-100 sm:py-12">
      
      <VerifyEmailBanner />
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

        {status === 'loading' ? (
          <p className="mt-10 text-slate-300">{t('loading')}</p>
        ) : null}

        {status === 'error' ? (
          <div
            role="alert"
            className="mt-10 rounded-3xl border border-red-400/30 bg-red-500/10 p-6 text-red-200"
          >
            {t('error')}
          </div>
        ) : null}

        {status === 'unauth' ? (
          <div className="mt-10 rounded-3xl border border-white/10 bg-white/5 p-8 text-center backdrop-blur">
            <h2 className="text-xl font-semibold text-white">{t('needLogin')}</h2>
            <p className="mt-2 text-slate-300">{t('needLoginHint')}</p>
            <Link
              href="/"
              className="mt-6 inline-block rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-900/40 transition hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
            >
              {t('goHome')}
            </Link>
          </div>
        ) : null}

        {status === 'ready' && data ? (
          <div className="mt-8 space-y-8">
            <div>
              <h2 className="text-xl font-semibold text-white">{t('welcome')}</h2>
              <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label={t('level')} value={String(data.user.level)} />
                <Stat label={t('character')} value={characterName} />
                <Stat
                  label={t('quota')}
                  value={data.user.quota_left != null ? String(data.user.quota_left) : '—'}
                />
                <Stat label={t('interests')}>
                  {interests.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {interests.map((interest) => (
                        <span
                          key={interest}
                          className="rounded-full border border-blue-400/30 bg-blue-500/10 px-3 py-1 text-xs font-medium text-sky-200"
                        >
                          {interest}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-slate-400">{t('noInterests')}</p>
                  )}
                </Stat>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {cards.map((card) => {
                const content = (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="font-semibold text-white">{card.title}</h3>
                      {card.href ? null : (
                        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-medium text-slate-400">
                          {t('soon')}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-sm text-slate-300">{card.description}</p>
                  </>
                );
                return card.href ? (
                  <Link
                    key={card.title}
                    href={card.href}
                    className="rounded-3xl border border-white/10 bg-white/5 p-6 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur transition hover:-translate-y-1 hover:border-blue-400/40 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
                  >
                    {content}
                  </Link>
                ) : (
                  <div
                    key={card.title}
                    className="rounded-3xl border border-white/10 bg-white/5 p-6 shadow-[0_20px_50px_-32px_rgba(2,6,23,0.9)] backdrop-blur"
                  >
                    {content}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}
