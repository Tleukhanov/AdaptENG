'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { ApiError, getAdminAnalytics } from '@/lib/api';
import type { AdminAnalytics, AdminCohortRow } from '@/lib/api';
import type { Locale } from '@/lib/i18n';
import { useSession } from '@/lib/session';

const PERIODS = [7, 30, 90] as const;
type Period = (typeof PERIODS)[number];

type Status = 'loading' | 'ready' | 'denied' | 'error' | 'unauth';

const PRIMARY =
  'inline-flex min-h-[44px] items-center justify-center rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]';

const GHOST =
  'inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-300 transition hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40';

function clampPercent(value: number | undefined | null): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function formatCount(value: number | undefined | null, formatter: Intl.NumberFormat): string {
  return typeof value === 'number' && Number.isFinite(value) ? formatter.format(value) : '—';
}

function formatPercent(value: number | undefined | null): string {
  const safe = clampPercent(value);
  return `${safe.toFixed(1).replace(/\.0$/, '')}%`;
}

function cohortName(row: AdminCohortRow): string {
  return row.first_name?.trim() || row.username?.trim() || `#${row.user_id}`;
}

/** KPI-карточка: цифра крупно, пояснение мелко. */
function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="panel p-5">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-2 text-3xl font-bold leading-none text-sky-300">{value}</p>
      {hint ? <p className="mt-2 text-xs leading-relaxed text-slate-400">{hint}</p> : null}
    </div>
  );
}

export default function AdminPage() {
  const t = useTranslations('admin');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();

  const [days, setDays] = useState<Period>(30);
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<AdminAnalytics | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (sessionLoading) {
      return;
    }
    if (!user) {
      setStatus('unauth');
      router.replace('/login');
      return;
    }
    let active = true;
    setStatus('loading');
    (async () => {
      try {
        const analytics = await getAdminAnalytics(days);
        if (!active) {
          return;
        }
        setData(analytics);
        setStatus('ready');
      } catch (error) {
        if (!active) {
          return;
        }
        if (error instanceof ApiError) {
          if (error.status === 401) {
            setStatus('unauth');
            router.replace('/login');
            return;
          }
          if (error.status === 403 || error.status === 404) {
            // 403 — не админ, 404 — метрики выключены в конфиге.
            setStatus('denied');
            return;
          }
        }
        setStatus('error');
      }
    })();
    return () => {
      active = false;
    };
  }, [days, reloadKey, router, sessionLoading, user]);

  if (status === 'unauth') {
    return (
      <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] px-4 py-10">
        <div className="mx-auto max-w-md text-center">
          <h1 className="text-2xl font-bold text-white">{t('needLogin')}</h1>
          <Link href="/login" className={`mt-6 ${PRIMARY}`}>
            {t('toLogin')}
          </Link>
        </div>
      </main>
    );
  }

  const formatter = new Intl.NumberFormat(locale === 'en' ? 'en-US' : 'ru-RU');
  const funnel = data?.funnel ?? null;
  const steps = funnel
    ? [
        { key: 'registered', label: t('step.registered'), value: funnel.funnel.registered },
        { key: 'onboarding', label: t('step.onboarding'), value: funnel.funnel.onboarding },
        { key: 'firstLesson', label: t('step.lesson'), value: funnel.funnel.first_lesson },
      ]
    : [];
  const funnelBase = Math.max(1, funnel?.funnel.registered ?? 0);
  // Бэкенд всегда отдаёт d1/d7/d30, но старый деплой не должен ронять страницу.
  const retention = {
    d1: funnel?.retention?.d1 ?? { percent: 0, cohort: 0 },
    d7: funnel?.retention?.d7 ?? { percent: 0, cohort: 0 },
    d30: funnel?.retention?.d30 ?? { percent: 0, cohort: 0 },
  };

  return (
    <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] overflow-hidden px-4 py-8 text-slate-100 sm:py-10">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_18%_-10%,rgba(37,99,235,0.28),transparent_70%)]"
      />
      <div className="relative mx-auto max-w-6xl">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-white">{t('title')}</h1>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-300">
              {t('subtitle')}
            </p>
          </div>
          <Link href="/dashboard" className={GHOST}>
            {t('toDashboard')}
          </Link>
        </header>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <div
            role="group"
            aria-label={t('period.label')}
            className="inline-flex rounded-xl border border-white/10 bg-white/5 p-1"
          >
            {PERIODS.map((period) => {
              const active = period === days;
              return (
                <button
                  key={period}
                  type="button"
                  onClick={() => setDays(period)}
                  aria-pressed={active}
                  className={`inline-flex min-h-[36px] items-center rounded-lg px-3 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
                    active
                      ? 'bg-blue-600 text-white shadow shadow-blue-950/40'
                      : 'text-slate-300 hover:bg-white/10 hover:text-white'
                  }`}
                >
                  {t('period.days', { days: period })}
                </button>
              );
            })}
          </div>
          {status === 'ready' && funnel ? (
            <p className="text-xs text-slate-400">
              {t('since', { date: funnel.since, days: funnel.days })}
            </p>
          ) : null}
        </div>

        {status === 'loading' || sessionLoading ? (
          <div
            role="status"
            aria-live="polite"
            className="panel mt-6 p-8 text-center text-sm text-slate-300"
          >
            {t('loading')}
          </div>
        ) : null}

        {status === 'denied' ? (
          <div
            role="status"
            className="panel mt-6 p-8 text-center"
          >
            <p aria-hidden="true" className="text-3xl">
              🔒
            </p>
            <h2 className="mt-3 text-xl font-semibold text-white">{t('deniedTitle')}</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-slate-300">
              {t('deniedHint')}
            </p>
            <Link href="/dashboard" className={`mt-6 ${PRIMARY}`}>
              {t('toDashboard')}
            </Link>
          </div>
        ) : null}

        {status === 'error' ? (
          <div role="alert" className="panel mt-6 border-red-400/30 bg-red-500/10 p-6">
            <p className="text-sm text-red-100">{t('error')}</p>
            <button
              type="button"
              onClick={() => setReloadKey((key) => key + 1)}
              className={`mt-4 ${PRIMARY}`}
            >
              {t('retry')}
            </button>
          </div>
        ) : null}

        {status === 'ready' && funnel ? (
          <div className="mt-6 space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi
                label={t('kpi.users')}
                value={formatCount(funnel.total_users, formatter)}
                hint={t('kpi.usersHint')}
              />
              <Kpi
                label={t('kpi.lessons')}
                value={formatCount(funnel.funnel.first_lesson, formatter)}
                hint={t('kpi.lessonsHint', {
                  percent: formatPercent(funnel.conversion.register_to_lesson),
                })}
              />
              <Kpi
                label={t('kpi.returned')}
                value={formatPercent(retention.d7.percent)}
                hint={t('kpi.returnedHint', { cohort: retention.d7.cohort })}
              />
              <Kpi
                label={t('kpi.activeToday')}
                value={formatCount(funnel.active_today, formatter)}
                hint={t('kpi.activeHint')}
              />
            </div>

            <section aria-labelledby="admin-funnel-title" className="panel p-5 sm:p-6">
              <h2 id="admin-funnel-title" className="text-base font-semibold text-white">
                {t('funnel.title')}
              </h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">
                {t('funnel.hint')}
              </p>
              <ol className="mt-5 space-y-4">
                {steps.map((step) => {
                  const share = (step.value / funnelBase) * 100;
                  return (
                    <li key={step.key}>
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="text-sm font-medium text-slate-200">{step.label}</span>
                        <span className="text-xs text-slate-400">
                          <span className="text-sm font-semibold text-sky-300">
                            {formatCount(step.value, formatter)}
                          </span>{' '}
                          · {formatPercent(share)}
                        </span>
                      </div>
                      <div
                        aria-hidden="true"
                        className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-white/10"
                      >
                        <span
                          className="block h-full rounded-full bg-gradient-to-r from-blue-600 via-blue-500 to-sky-400 transition-[width] duration-500"
                          style={{ width: `${clampPercent(share)}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ol>

              <div className="mt-6 grid gap-3 sm:grid-cols-3">
                {(
                  [
                    { key: 'd1', point: retention.d1 },
                    { key: 'd7', point: retention.d7 },
                    { key: 'd30', point: retention.d30 },
                  ] as const
                ).map((item) => (
                  <div key={item.key} className="panel-muted p-3.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                      {t(`retention.${item.key}`)}
                    </p>
                    <p className="mt-1 text-lg font-bold text-sky-300">
                      {formatPercent(item.point.percent)}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {t('retention.cohortSize', { cohort: item.point.cohort })}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            <section aria-labelledby="admin-cohorts-title" className="panel p-5 sm:p-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="admin-cohorts-title" className="text-base font-semibold text-white">
                  {t('cohorts.title')}
                </h2>
                <p className="text-xs text-slate-400">
                  {t('cohorts.hint', { count: data?.cohort_size ?? 0 })}
                </p>
              </div>

              {(data?.cohorts?.length ?? 0) === 0 ? (
                <p role="status" className="mt-4 text-sm text-slate-400">
                  {t('cohorts.empty')}
                </p>
              ) : (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[760px] border-collapse text-left text-sm">
                    <caption className="sr-only">{t('cohorts.title')}</caption>
                    <thead>
                      <tr className="border-b border-white/10 text-[11px] uppercase tracking-wide text-slate-400">
                        <th scope="col" className="py-2 pr-3 font-semibold">
                          {t('cohorts.user')}
                        </th>
                        <th scope="col" className="px-3 py-2 font-semibold">
                          {t('cohorts.level')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                          {t('cohorts.turns')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                          {t('cohorts.accuracy')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                          {t('cohorts.lessons')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                          {t('cohorts.words')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                          {t('cohorts.streak')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                          {t('cohorts.weekAccuracy')}
                        </th>
                        <th scope="col" className="py-2 pl-3 text-right font-semibold">
                          {t('cohorts.retention')}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {(data?.cohorts ?? []).map((row) => (
                        <tr
                          key={row.user_id}
                          className="border-b border-white/5 last:border-0 hover:bg-white/[0.03]"
                        >
                          <th
                            scope="row"
                            className="max-w-[180px] truncate py-2.5 pr-3 text-left font-medium text-slate-200"
                          >
                            {cohortName(row)}
                          </th>
                          <td className="px-3 py-2.5 text-slate-400">{row.level ?? '—'}</td>
                          <td className="px-3 py-2.5 text-right text-slate-300">
                            {formatCount(row.turns, formatter)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-slate-300">
                            {formatPercent(row.accuracy)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-slate-300">
                            {formatCount(row.lessons, formatter)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-slate-300">
                            {formatCount(row.words, formatter)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-slate-300">
                            {formatCount(row.streak_days, formatter)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-slate-300">
                            {formatPercent(row.accuracy_7d)}
                          </td>
                          <td className="py-2.5 pl-3 text-right text-slate-300">
                            {formatPercent(row.retention_30)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        ) : null}
      </div>
    </main>
  );
}
