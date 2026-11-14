'use client';

import { useEffect, useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { getAdminUsers, grantSubscription, toggleBlock, deleteUser, type AdminUserListItem, type AdminSubscriptionStatus } from '@/lib/api';
import { useSession } from '@/lib/session';

const PAGE_SIZE = 20;

const SUBSCRIPTION_LABELS: Record<AdminSubscriptionStatus, string> = {
  active: 'Активна',
  expired: 'Истекла',
  none: 'Нет',
};

const SUBSCRIPTION_BADGE_COLORS: Record<AdminSubscriptionStatus, string> = {
  active: 'bg-green-100 text-green-700 border border-green-200',
  expired: 'bg-red-100 text-red-700 border border-red-200',
  none: 'bg-slate-100 text-slate-600 border border-slate-200',
};

function formatDate(dateString?: string | null): string {
  if (!dateString) return '—';
  try {
    return new Date(dateString).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return dateString;
  }
}

export default function AdminUsersPage() {
  const t = useTranslations('admin.users');
  const router = useRouter();
  const { user } = useSession();

  const [users, setUsers] = useState<AdminUserListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [subscriptionFilter, setSubscription] = useState<AdminSubscriptionStatus | 'all'>('all');
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState<Set<number>>(new Set());
  const [blocking, setBlocking] = useState<Set<number>>(new Set());

  const loadUsers = useCallback(async () => {
    if (sessionLoading) return;
    setLoading(true);
    try {
      const data = await getAdminUsers({ limit, offset, search: search || undefined, subscription: subscription === 'all' ? undefined : subscription });
      setUsers(data.users);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to load users', err);
    } finally {
      setLoading(false);
    }
  }, [limit, offset, search, subscription, sessionLoading]);

  useEffect(() => {
    loadUsers();
  }, [load]);

  const handleBlockToggle = async (id: number, currentlyBlocked: boolean) => {
    setBlocking((prev) => new Set([...prev, id]));
    try {
      await toggleBlock(id, !currentlyBlocked);
      setUsers((prev) => prev.map((u) => (u.id === id ? { ...u, blocked: !currentlyBlocked } : u)));
    } catch (err) {
      console.error('Failed to toggle block', err);
    } finally {
      setBlocking((prev) => new Set([...prev].filter((id) => id !== id)));
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('users.confirmDelete'))) return;
    setDeleting((prev) => new Set([...prev, id]));
    try {
      await deleteUser(id);
      setUsers((prev) => prev.filter((u) => u.id !== id));
      setTotal((prev) => prev - 1);
    } catch (err) {
      console.error('Failed to delete user', err);
    } finally {
      setDeleting((prev) => new Set([...prev].filter((id) => id !== id)));
    }
  };

  if (sessionLoading) return null;
  if (!user) {
    router.replace('/login');
    return null;
  }

  const filteredUsers = users;

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('admin.users.title')}</h1>
          <p className="mt-1 text-sm text-slate-400">{t('admin.users.subtitle')}</p>
        </div>
        <Link
          href="/admin"
          className={GHOST}
        >
          {t('admin.back')}
        </Link>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
        <div className="flex gap-2">
          <input
            type="text"
            placeholder={t('admin.users.searchPlaceholder')}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
            className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-400 focus:outline-none"
          />
          <select
            value={subscription}
            onChange={(e) => {
              setSubscription(e.target.value as AdminSubscriptionStatus);
              setOffset(0);
            }}
            className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-400 focus:outline-none"
          >
            <option value="all">{t('admin.users.filter.all')}</option>
            <option value="active">{t('admin.users.filter.active')}</option>
            <option value="expired">{t('admin.users.filter.expired')}</option>
            <option value="none">{t('admin.users.filter.none')}</option>
          </select>
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0}
            className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-sm font-medium text-slate-300 hover:bg-white/10 transition disabled:opacity-50"
          >
            {t('common.prev')}
          </button>
          <button
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= total}
            className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-sm font-semibold text-slate-300 transition hover:bg-white/10 disabled:opacity-50"
          >
            {t('admin.users.next')}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="mt-8 flex justify-center items-center min-h-[200px]">
          <p className="text-sm text-slate-400">{t('admin.users.loading')}</p>
        </div>
      ) : users.length === 0 ? (
        <div className="mt-8 panel p-8 text-center">
          <p className="text-sm text-slate-400">{t('admin.users.empty')}</p>
        </div>
      ) : (
        <div className="rounded-xl border border-white/10 bg-white/5 p-6 shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="border-b border-white/10 text-[11px] uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="pb-3 px-3 text-left">{t('admin.users.column.avatar')}</th>
                  <th className="pb-3 px-3 text-left">{t('admin.users.column.name')}</th>
                  <th className="pb-3 px-3 text-left">{t('admin.users.column.email')}</th>
                  <th className="pb-3 px-3 text-left">{t('admin.users.column.tg')}</th>
                  <th className="pb-3 px-3 text-left">{t('admin.users.column.level')}</th>
                  <th className="pb-3 px-3 text-right">{t('admin.users.column.subscription')}</th>
                  <th className="pb-3 px-3 text-right">{t('admin.users.column.status')}</th>
                  <th className="pb-3 px-3 text-right">{t('admin.users.column.actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-white/5 transition-colors">
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-500/20 text-slate-400 text-xs font-bold">
                          {(u.firstName || u.username || u.email || 'U').charAt(0)}
                        </div>
                        <div className="flex flex-col min-w-0">
                          <p className="text-sm font-semibold text-slate-100">{u.firstName || u.username || u.email}</p>
                          <p className="text-[11px] text-slate-500">{u.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-sm text-slate-300">{u.tg_id ?? '—'}</td>
                    <td className="py-3 px-3 text-sm text-slate-300">{u.level || '—'}</td>
                    <td className="py-3 px-3 text-right text-sm text-slate-300">
                      <span className={SUBSCRIPTION_BADGE_COLORS[u.subscriptionStatus]}>
                        {u.subscriptionStatus === 'active' ? t('admin.users.column.subscriptionActive', { date: u.subscriptionExpiresAt }) : u.subscription_status === 'expired' ? t('admin.users.subscription.expired') : t('admin.users.subscription.none')}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right text-sm text-slate-400">{u.createdAt || '—'}</td>
                    <td className="py-3 px-3 text-right text-sm text-slate-400">
                      <span className={`inline-flex items-center rounded-full px-2 py-1 text-[10px] font-semibold ${
                        u.blocked ? 'bg-red-500/20 text-red-500' : 'bg-green-500/20 text-green-500'
                      }`}>
                        {u.blocked ? t('admin.users.column.status.blocked') : t('admin.users.column.status.active')}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right text-sm text-slate-400">
                      <div className="flex gap-1">
                        <button
                          onClick={() => handleGrant(u.id)}
                          className="rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 transition hover:bg-white/10"
                        >
                          {t('admin.users.actions.grant')}
                        </button>
                        <button
                          onClick={() => handleToggleBlock(u.id, u.blocked)}
                          className={`rounded-lg px-3 py-2 text-xs font-semibold transition ${u.blocked ? 'bg-green-500/20 text-green-500 hover:bg-green-500/30' : 'bg-red-500/20 text-red-500 hover:bg-red-500/30'}`}
                        >
                          {u.blocked ? t('admin.users.actions.unblock') : t('admin.users.actions.block')}
                        </button>
                        <button
                          onClick={() => handleDelete(u.id)}
                          className="rounded-lg px-3 py-2 text-xs font-semibold text-red-500 hover:bg-red-500/20 transition"
                        >
                          {t('admin.users.actions.delete')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  );
}

export default AdminUsersPage;