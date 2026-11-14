'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import {
  ApiError,
  deleteUser,
  getAdminUser,
  grantSubscription,
  toggleBlock,
  type UserDetailResponse,
} from '@/lib/api';
import { useSession } from '@/lib/session';

const PRIMARY =
  'inline-flex items-center justify-center rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50';
const GHOST =
  'inline-flex items-center justify-center rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-semibold text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50';
const DANGER =
  'inline-flex items-center justify-center rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-300 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50';

type Status = 'loading' | 'ready' | 'notfound' | 'denied' | 'error' | 'unauth';

function formatDate(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-muted p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-2 text-sm text-slate-200">{value}</p>
    </div>
  );
}

export default function AdminUserPage() {
  const t = useTranslations('admin');
  const router = useRouter();
  const params = useParams<{ userId: string }>();
  const userId = Number.parseInt(String(params?.userId ?? ''), 10);
  const { user, loading: sessionLoading } = useSession();

  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<UserDetailResponse | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [grantDays, setGrantDays] = useState('7');

  useEffect(() => {
    if (sessionLoading) return;
    if (!user) {
      setStatus('unauth');
      router.replace('/login');
      return;
    }
    if (!Number.isFinite(userId) || userId <= 0) {
      setStatus('notfound');
      return;
    }
    let active = true;
    setStatus('loading');
    setError('');
    (async () => {
      try {
        const result = await getAdminUser(userId);
        if (!active) return;
        setData(result);
        setStatus('ready');
      } catch (err) {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          setStatus('unauth');
          router.replace('/login');
          return;
        }
        if (err instanceof ApiError && err.status === 403) {
          setStatus('denied');
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setStatus('notfound');
          return;
        }
        setError(err instanceof ApiError ? err.message : String(err));
        setStatus('error');
      }
    })();
    return () => {
      active = false;
    };
  }, [reloadKey, router, sessionLoading, userId, user]);

  const reload = () => setReloadKey((key) => key + 1);

  const handleGrant = async (daysOverride?: number) => {
    const days = daysOverride ?? Number.parseInt(grantDays, 10);
    if (!Number.isFinite(days) || days <= 0) {
      setError(t('users.grant.invalid'));
      return;
    }
    setBusy(true);
    try {
      await grantSubscription(userId, days);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleToggleBlock = async () => {
    if (!data) return;
    setBusy(true);
    try {
      await toggleBlock(userId, !data.user.blocked);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(t('users.confirm.delete'))) return;
    setBusy(true);
    try {
      await deleteUser(userId);
      router.push('/admin/users');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

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

  if (status === 'denied' || status === 'notfound' || status === 'error') {
    return (
      <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] px-4 py-10">
        <div className="panel mx-auto max-w-md p-8 text-center">
          <h1 className="text-xl font-bold text-white">
            {status === 'denied'
              ? t('deniedTitle')
              : status === 'notfound'
                ? t('users.detail.not_found')
                : t('error')}
          </h1>
          {status === 'error' && error ? (
            <p className="mt-2 text-sm text-red-200">{error}</p>
          ) : null}
          <Link href="/admin/users" className={`mt-6 ${PRIMARY}`}>
            {t('users.back')}
          </Link>
        </div>
      </main>
    );
  }

  if (status === 'loading' || !data) {
    return (
      <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] px-4 py-10">
        <div className="mx-auto max-w-5xl">
          <p className="text-sm text-slate-400">{t('users.loading')}</p>
        </div>
      </main>
    );
  }

  const u = data.user;
  const stats = data.stats;
  const sub = data.subscription;
  const name = u.first_name?.trim() || u.username?.trim() || u.email || `#${u.id}`;

  return (
    <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] px-4 py-10">
      <div className="mx-auto max-w-5xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {t('users.detail.id', { id: u.id })}
            </p>
            <h1 className="mt-1 text-3xl font-bold text-white">{name}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-400">
              {u.email ? <span>{u.email}</span> : null}
              <span>·</span>
              <span>
                {u.tg_id ? `TG ${u.tg_id}` : t('users.no_telegram')}
              </span>
              <span>·</span>
              <span
                className={
                  u.blocked
                    ? 'rounded-full border border-red-400/30 bg-red-500/10 px-2 py-0.5 text-[11px] text-red-300'
                    : 'rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300'
                }
              >
                {u.blocked ? t('users.status.blocked') : t('users.status_active')}
              </span>
            </div>
          </div>
          <Link href="/admin/users" className={GHOST}>
            {t('users.back')}
          </Link>
        </div>

        {error ? (
          <div role="alert" className="panel mt-4 border-red-400/30 bg-red-500/10 p-4 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            {t('users.detail.info')}
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <InfoCard label={t('users.column.email')} value={u.email || '—'} />
            <InfoCard label={t('users.column.tg')} value={u.tg_id ? String(u.tg_id) : '—'} />
            <InfoCard label={t('users.column.level')} value={u.level || '—'} />
            <InfoCard label={t('users.column.created')} value={formatDate(u.created_at)} />
            <InfoCard
              label={t('users.detail.email_verified')}
              value={u.email_verified_at ? formatDate(u.email_verified_at) : t('users.no')}
            />
            <InfoCard
              label={t('users.detail.reminders')}
              value={u.reminders_enabled ? t('users.yes') : t('users.no')}
            />
            <InfoCard
              label={t('users.detail.limit')}
              value={u.is_unlimited ? t('users.unlimited') : t('users.limited')}
            />
            <InfoCard
              label={t('users.column.subscription')}
              value={
                u.subscription_status === 'none'
                  ? t('users.subscription.none')
                  : t(`users.subscription.${u.subscription_status}`, {
                      date: formatDate(u.subscription_expires_at),
                    })
              }
            />
          </div>
        </section>

        <section className="mt-6 grid gap-4 lg:grid-cols-2">
          <div className="panel p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              {t('users.detail.stats')}
            </h2>
            <div className="mt-4 grid grid-cols-3 gap-3">
              <div>
                <p className="text-2xl font-bold text-sky-300">{stats.total_turns}</p>
                <p className="mt-1 text-xs text-slate-400">{t('users.stat.total_turns')}</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-emerald-300">{stats.correct}</p>
                <p className="mt-1 text-xs text-slate-400">{t('users.stat.correct')}</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-red-300">{stats.errors}</p>
                <p className="mt-1 text-xs text-slate-400">{t('users.stat.errors')}</p>
              </div>
            </div>
            <p className="mt-6 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {t('users.detail.top_categories')}
            </p>
            {stats.top_categories.length > 0 ? (
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                {stats.top_categories.map(([category, count]) => (
                  <li key={category} className="flex justify-between gap-3">
                    <span>{category}</span>
                    <span className="text-slate-400">{count}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-slate-500">{t('users.detail.no_stats')}</p>
            )}
          </div>

          <div className="panel p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              {t('users.column.subscription')}
            </h2>
            {sub ? (
              <dl className="mt-4 space-y-2 text-sm text-slate-300">
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-400">{t('users.detail.plan_days')}</dt>
                  <dd>{sub.plan_days}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-400">{t('users.detail.granted_at')}</dt>
                  <dd>{formatDateTime(sub.granted_at)}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-400">{t('users.detail.expires_at')}</dt>
                  <dd>{formatDateTime(sub.expires_at)}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-4 text-sm text-slate-500">{t('users.subscription.none')}</p>
            )}

            <div className="mt-6 flex flex-wrap items-end gap-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {t('users.modal.days')}
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={grantDays}
                  onChange={(event) => setGrantDays(event.target.value)}
                  className="mt-2 w-28 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-sky-400/50 focus:outline-none"
                />
              </label>
              <button type="button" onClick={() => void handleGrant()} disabled={busy} className={PRIMARY}>
                {t('users.btn.grant')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setGrantDays('7');
                  void handleGrant(7);
                }}
                disabled={busy}
                className={GHOST}
              >
                {t('users.grant.days', { days: 7 })}
              </button>
              <button
                type="button"
                onClick={() => {
                  setGrantDays('30');
                  void handleGrant(30);
                }}
                disabled={busy}
                className={GHOST}
              >
                {t('users.grant.days', { days: 30 })}
              </button>
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              <button type="button" onClick={handleToggleBlock} disabled={busy} className={GHOST}>
                {u.blocked ? t('users.btn.unblock') : t('users.btn.block')}
              </button>
              <button type="button" onClick={handleDelete} disabled={busy} className={DANGER}>
                {t('users.btn.delete')}
              </button>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
