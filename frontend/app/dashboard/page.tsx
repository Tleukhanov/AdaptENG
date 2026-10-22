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
    <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      {value ? <p className="mt-2 text-lg font-bold text-slate-900">{value}</p> : null}
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
    <main className="mx-auto max-w-5xl px-4 py-12">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-bold text-slate-900">{t('title')}</h1>
        <Link href="/" className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-600 hover:text-blue-500">
          {t('back')}
        </Link>
      </div>

      {status === 'loading' ? <p className="mt-10 text-slate-600">{t('loading')}</p> : null}

      {status === 'error' ? (
        <div className="mt-10 rounded-3xl border border-red-200 bg-red-50 p-6 text-red-700">
          {t('error')}
        </div>
      ) : null}

      {status === 'unauth' ? (
        <div className="mt-10 rounded-3xl border border-slate-200 bg-white p-8 text-center">
          <h2 className="text-xl font-semibold text-slate-900">{t('needLogin')}</h2>
          <p className="mt-2 text-slate-600">{t('needLoginHint')}</p>
          <Link
            href="/"
            className="mt-6 inline-block rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white"
          >
            {t('goHome')}
          </Link>
        </div>
      ) : null}

      {status === 'ready' && data ? (
        <div className="mt-8 space-y-8">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">{t('welcome')}</h2>
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
                        className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700"
                      >
                        {interest}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">{t('noInterests')}</p>
                )}
              </Stat>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {cards.map((card) => {
              const content = (
                <>
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-slate-900">{card.title}</h3>
                    {card.href ? null : (
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500">
                        {t('soon')}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-sm text-slate-600">{card.description}</p>
                </>
              );
              return card.href ? (
                <Link
                  key={card.title}
                  href={card.href}
                  className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
                >
                  {content}
                </Link>
              ) : (
                <div
                  key={card.title}
                  className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"
                >
                  {content}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </main>
  );
}
