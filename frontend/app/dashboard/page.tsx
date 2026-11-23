'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { sampleCharacters } from '@/lib/characters';
import type { Locale } from '@/lib/i18n';
import { apiFetch, getAdminAnalytics } from '@/lib/api';
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
    <div className="rounded-2xl border border-ink-900/10 bg-paper-50 p-5 shadow-[0_20px_50px_-32px_rgba(26,22,18,0.18)]">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500">{label}</p>
      {value ? <p className="mt-2 font-display text-2xl font-semibold text-ink-900">{value}</p> : null}
      {children}
    </div>
  );
}

export default function DashboardPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('dashboard');
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<MeResponse | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const adminCheckedRef = useRef(false);
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

  useEffect(() => {
    if (sessionLoading || !user || adminCheckedRef.current) {
      return;
    }
    adminCheckedRef.current = true;
    let active = true;
    (async () => {
      try {
        await getAdminAnalytics(7);
        if (active) {
          setIsAdmin(true);
        }
      } catch {
        if (active) {
          setIsAdmin(false);
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
    <main className="relative isolate min-h-[calc(100dvh-4rem)] bg-paper-100 px-4 py-10 sm:py-12">
      <div className="mx-auto max-w-5xl">
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-ink-900/10 pb-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-ink-500">
              {t('title')}
            </p>
            <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight text-ink-900">
              {t('welcome')}
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {isAdmin ? (
              <Link
                href="/admin"
                className="inline-flex min-h-[36px] items-center rounded-full border border-ink-900/10 bg-paper-50 px-4 py-2 text-sm font-semibold text-ink-900 transition hover:border-accent-600 hover:text-accent-600"
              >
                {t('admin')}
              </Link>
            ) : null}
            <Link
              href="/"
              className="inline-flex min-h-[36px] items-center rounded-full px-3 py-2 text-sm font-semibold text-ink-500 transition hover:text-accent-600"
            >
              {t('back')}
            </Link>
          </div>
        </div>

        {status === 'loading' ? (
          <p className="mt-10 text-ink-500">{t('loading')}</p>
        ) : null}

        {status === 'error' ? (
          <div
            role="alert"
            className="mt-10 rounded-2xl border border-accent-600/30 bg-accent-50 p-6 text-accent-700"
          >
            {t('error')}
          </div>
        ) : null}

        {status === 'unauth' ? (
          <div className="mt-10 rounded-2xl border border-ink-900/10 bg-paper-50 p-8 text-center">
            <h2 className="font-display text-2xl font-semibold text-ink-900">{t('needLogin')}</h2>
            <p className="mt-2 text-ink-500">{t('needLoginHint')}</p>
            <Link
              href="/"
              className="mt-6 inline-block rounded-full bg-ink-900 px-6 py-3 text-sm font-semibold text-paper-50 transition hover:bg-accent-600"
            >
              {t('goHome')}
            </Link>
          </div>
        ) : null}

        {status === 'ready' && data ? (
          <div className="mt-10 space-y-10">
            <div>
              <h2 className="font-display text-xl font-semibold text-ink-900">
                {t('welcome')}
              </h2>
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
                          className="rounded-full border border-accent-600/30 bg-accent-50 px-3 py-1 text-xs font-medium text-accent-700"
                        >
                          {interest}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-ink-500">{t('noInterests')}</p>
                  )}
                </Stat>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {cards.map((card) => {
                const content = (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="font-display text-lg font-semibold text-ink-900">{card.title}</h3>
                      {card.href ? null : (
                        <span className="rounded-full border border-ink-900/10 bg-paper-200 px-2.5 py-1 text-xs font-medium text-ink-500">
                          {t('soon')}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-ink-500">{card.description}</p>
                  </>
                );
                return card.href ? (
                  <Link
                    key={card.title}
                    href={card.href}
                    className="group rounded-2xl border border-ink-900/10 bg-paper-50 p-6 shadow-[0_20px_50px_-32px_rgba(26,22,18,0.18)] transition hover:-translate-y-1 hover:border-accent-600/40 hover:shadow-[0_24px_60px_-30px_rgba(194,65,12,0.18)]"
                  >
                    {content}
                  </Link>
                ) : (
                  <div
                    key={card.title}
                    className="rounded-2xl border border-ink-900/10 bg-paper-50 p-6 shadow-[0_20px_50px_-32px_rgba(26,22,18,0.18)]"
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
