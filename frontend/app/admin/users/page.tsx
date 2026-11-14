'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import {
  ApiError,
  deleteUser,
  getAdminUsers,
  grantSubscription,
  toggleBlock,
  type AdminSubscriptionStatus,
  type AdminUserListItem,
  type AdminUserListResponse,
} from '@/lib/api';
import { useSession } from '@/lib/session';

const PAGE_SIZE = 20;

const PRIMARY =
  'inline-flex items-center justify-center rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50';
const GHOST =
  'inline-flex items-center justify-center rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-semibold text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50';
const DANGER =
  'inline-flex items-center justify-center rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-300 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50';

type Status = 'loading' | 'ready' | 'denied' | 'error' | 'unauth';
type Filter = 'all' | AdminSubscriptionStatus;

const FILTERS: Filter[] = ['all', 'active', 'expired', 'none'];

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

function displayName(user: AdminUserListItem): string {
  return user.first_name?.trim() || user.username?.trim() || user.email || `#${user.id}`;
}

export default function AdminUsersPage() {
  const t = useTranslations('admin');
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();

  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<AdminUserListResponse | null>(null);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [page, setPage] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState('');

  const [grantTarget, setGrantTarget] = useState<AdminUserListItem | null>(null);
  const [grantDays, setGrantDays] = useState('7');
  const [busyId, setBusyId] = useState<number | null>(null);

  // Поиск с задержкой, чтобы не дёргать API на каждый символ.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (sessionLoading) return;
    if (!user) {
      setStatus('unauth');
      router.replace('/login');
      return;
    }
    let active = true;
    setStatus('loading');
    setError('');
    (async () => {
      try {
        const result = await getAdminUsers({
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
          search: query || undefined,
          subscription: filter === 'all' ? undefined : filter,
        });
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
        setError(err instanceof ApiError ? err.message : String(err));
        setStatus('error');
      }
    })();
    return () => {
      active = false;
    };
  }, [filter, page, query, reloadKey, router, sessionLoading, user]);

  const reload = () => setReloadKey((key) => key + 1);

  const handleGrant = async () => {
    if (!grantTarget) return;
    const days = Number.parseInt(grantDays, 10);
    if (!Number.isFinite(days) || days <= 0) {
      setError(t('users.grant.invalid'));
      return;
    }
    setBusyId(grantTarget.id);
    try {
      await grantSubscription(grantTarget.id, days);
      setGrantTarget(null);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const handleToggleBlock = async (target: AdminUserListItem) => {
    setBusyId(target.id);
    try {
      await toggleBlock(target.id, !target.blocked);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (target: AdminUserListItem) => {
    if (!window.confirm(t('users.confirm.delete'))) return;
    setBusyId(target.id);
    try {
      await deleteUser(target.id);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const filterLabel = (item: Filter): string => {
    if (item === 'active') return t('users.filter_active');
    if (item === 'expired') return t('users.filter_expired');
    if (item === 'none') return t('users.filter_none');
    return t('users.filter_all');
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

  if (status === 'denied') {
    return (
      <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] px-4 py-10">
        <div className="panel mx-auto max-w-md p-8 text-center">
          <h1 className="text-xl font-bold text-white">{t('deniedTitle')}</h1>
          <p className="mt-2 text-sm text-slate-300">{t('deniedHint')}</p>
          <Link href="/dashboard" className={`mt-6 ${PRIMARY}`}>
            {t('toDashboard')}
          </Link>
        </div>
      </main>
    );
  }

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const users = data?.users ?? [];

  return (
    <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] px-4 py-10">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-white">{t('users.title')}</h1>
            <p className="mt-2 text-sm text-slate-400">{t('users.subtitle')}</p>
          </div>
          <Link href="/admin" className={GHOST}>
            {t('users.back')}
          </Link>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('users.search')}
            className="min-w-[240px] flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-sky-400/50 focus:outline-none"
          />
          <div className="flex flex-wrap gap-2">
            {FILTERS.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => {
                  setFilter(item);
                  setPage(0);
                }}
                className={item === filter ? PRIMARY : GHOST}
              >
                {filterLabel(item)}
              </button>
            ))}
          </div>
        </div>

        {error ? (
          <div role="alert" className="panel mt-4 border-red-400/30 bg-red-500/10 p-4 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        {status === 'loading' ? (
          <p className="mt-8 text-sm text-slate-400">{t('users.loading')}</p>
        ) : null}

        {status === 'error' ? (
          <div className="panel mt-8 p-8 text-center">
            <p className="text-sm text-red-200">{t('error')}</p>
            <button type="button" onClick={reload} className={`mt-4 ${PRIMARY}`}>
              {t('retry')}
            </button>
          </div>
        ) : null}

        {status === 'ready' && users.length === 0 ? (
          <p className="mt-8 text-sm text-slate-400">{t('users.empty')}</p>
        ) : null}

        {status === 'ready' && users.length > 0 ? (
          <div className="panel mt-6 overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="border-b border-white/10 text-[11px] uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3 font-semibold">{t('users.column.name')}</th>
                  <th className="px-4 py-3 font-semibold">{t('users.column.email')}</th>
                  <th className="px-4 py-3 font-semibold">{t('users.column.tg')}</th>
                  <th className="px-4 py-3 font-semibold">{t('users.column.level')}</th>
                  <th className="px-4 py-3 font-semibold">{t('users.column.subscription')}</th>
                  <th className="px-4 py-3 font-semibold">{t('users.column.created')}</th>
                  <th className="px-4 py-3 text-right font-semibold">{t('users.column.actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {users.map((item) => (
                  <tr key={item.id} className="align-top">
                    <td className="px-4 py-3">
                      <Link
                        href={`/admin/users/${item.id}`}
                        className="font-semibold text-white hover:text-sky-300"
                      >
                        {displayName(item)}
                      </Link>
                      <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
                        <span
                          className={
                            item.blocked
                              ? 'rounded-full border border-red-400/30 bg-red-500/10 px-2 py-0.5 text-red-300'
                              : 'rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-emerald-300'
                          }
                        >
                          {item.blocked ? t('users.status.blocked') : t('users.status_active')}
                        </span>
                        {item.is_unlimited ? (
                          <span className="rounded-full border border-sky-400/30 bg-sky-500/10 px-2 py-0.5 text-sky-300">
                            {t('users.unlimited')}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-300">{item.email || '—'}</td>
                    <td className="px-4 py-3 text-slate-400">{item.tg_id ?? '—'}</td>
                    <td className="px-4 py-3 text-slate-300">{item.level || '—'}</td>
                    <td className="px-4 py-3">
                      <span
                        className={
                          item.subscription_status === 'active'
                            ? 'text-emerald-300'
                            : item.subscription_status === 'expired'
                              ? 'text-red-300'
                              : 'text-slate-400'
                        }
                      >
                        {item.subscription_status === 'none'
                          ? t('users.subscription.none')
                          : t(`users.subscription.${item.subscription_status}`, {
                              date: formatDate(item.subscription_expires_at),
                            })}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400">{formatDate(item.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setGrantDays('7');
                            setGrantTarget(item);
                          }}
                          disabled={busyId === item.id}
                          className={GHOST}
                        >
                          {t('users.btn.grant')}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggleBlock(item)}
                          disabled={busyId === item.id}
                          className={GHOST}
                        >
                          {item.blocked ? t('users.btn.unblock') : t('users.btn.block')}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(item)}
                          disabled={busyId === item.id}
                          className={DANGER}
                        >
                          {t('users.btn.delete')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {status === 'ready' && total > 0 ? (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-slate-400">
              {t('users.count', { total })}
              {' · '}
              {t('users.page', { page: page + 1, pages })}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((value) => Math.max(0, value - 1))}
                disabled={page === 0}
                className={GHOST}
              >
                {t('users.prev')}
              </button>
              <button
                type="button"
                onClick={() => setPage((value) => Math.min(pages - 1, value + 1))}
                disabled={page >= pages - 1}
                className={GHOST}
              >
                {t('users.next')}
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {grantTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 px-4">
          <div className="panel w-full max-w-sm p-6">
            <h2 className="text-lg font-bold text-white">{t('users.modal.title')}</h2>
            <p className="mt-1 text-sm text-slate-400">{displayName(grantTarget)}</p>
            <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-400">
              {t('users.modal.days')}
              <input
                type="number"
                min={1}
                max={365}
                value={grantDays}
                onChange={(event) => setGrantDays(event.target.value)}
                className="mt-2 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-sky-400/50 focus:outline-none"
              />
            </label>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setGrantTarget(null)}
                disabled={busyId === grantTarget.id}
                className={GHOST}
              >
                {t('users.modal.cancel')}
              </button>
              <button
                type="button"
                onClick={handleGrant}
                disabled={busyId === grantTarget.id}
                className={PRIMARY}
              >
                {t('users.modal.confirm')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
