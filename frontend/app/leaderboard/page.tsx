'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { getLeaderboard, type LeaderboardEntry } from '@/lib/api';
import type { Locale } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { useRouter } from 'next/navigation';

type Status = 'loading' | 'ready' | 'error' | 'unauth';

type Row = LeaderboardEntry & { rank: number; isMe?: boolean };

function getStaticLeaderboard(locale: Locale): Row[] {
  const ru = locale !== 'en';
  const names = ru
    ? ['Анна', 'Дмитрий', 'Мария', 'Игорь', 'Елена', 'Тимур', 'Наталья', 'Олег', 'Ксения', 'Вы']
    : ['Anna', 'Dmitry', 'Maria', 'Igor', 'Elena', 'Timur', 'Natalia', 'Oleg', 'Ksenia', 'You'];
  return names.map((n, i) => {
    const isMe = i === names.length - 1;
    return {
      rank: i + 1,
      user_id: 1000 + i,
      username: null,
      first_name: n,
      level: ru ? 'Мастер' : 'Master',
      xp: 1200 - i * 110,
      total_lessons: 30 - i * 2,
      streak_days: 12 - i,
      isMe,
    };
  });
}

export default function LeaderboardPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('leaderboard');
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();
  const [status, setStatus] = useState<Status>('loading');
  const [rows, setRows] = useState<Row[]>([]);

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
        const list = await getLeaderboard();
        if (!active) return;
        setRows((Array.isArray(list) ? list : []).map((r, i) => ({ ...r, rank: i + 1 })));
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

  return (
    <main className="mx-auto max-w-4xl px-4 py-12">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-bold text-slate-900">{t('title')}</h1>
        <Link href="/" className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-600 hover:text-blue-500">
          {t('back')}
        </Link>
      </div>

      {status === 'loading' && <p className="mt-10 text-slate-600">...</p>}

      {status === 'ready' && (
        <div className="mt-8 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[280px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                  <th className="px-3 py-3 sm:px-5">{t('rank')}</th>
                  <th className="px-3 py-3 sm:px-5">{t('name')}</th>
                  <th className="px-3 py-3 text-right sm:px-5">{t('xp')}</th>
                  <th className="px-3 py-3 text-right sm:px-5">{t('lessons')}</th>
                  <th className="hidden px-5 py-3 text-right sm:table-cell">{t('streak')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.user_id} className={`border-b border-slate-100 last:border-0 ${r.isMe ? 'bg-blue-50' : ''}`}>
                    <td className="px-3 py-3 font-semibold text-slate-500 sm:px-5">
                      {r.rank}
                      {r.isMe ? <span className="ml-2 rounded-full bg-blue-500 px-2 py-0.5 text-[10px] font-bold text-white">{t('you')}</span> : null}
                    </td>
                    <td className="px-3 py-3 sm:px-5">
                      <p className="font-semibold text-slate-900">{r.first_name || r.username || `#${r.user_id}`}</p>
                      {r.level ? <p className="text-xs text-slate-500">{r.level}</p> : null}
                    </td>
                    <td className="px-3 py-3 text-right font-semibold text-slate-900 sm:px-5">{r.xp}</td>
                    <td className="px-3 py-3 text-right text-slate-600 sm:px-5">{r.total_lessons}</td>
                    <td className="hidden px-5 py-3 text-right text-slate-600 sm:table-cell">{r.streak_days}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length === 0 && <p className="p-6 text-slate-600">{t('noPlace')}</p>}
        </div>
      )}

      {status === 'error' && (
        <div className="mt-10 rounded-3xl border border-red-200 bg-red-50 p-6 text-red-700">
          {t('error')}
        </div>
      )}
    </main>
  );
}