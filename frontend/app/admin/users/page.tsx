'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState, useCallback } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import {
  AdminUserListItem,
  AdminSubscriptionStatus,
  getAdminUsers,
  grantSubscription,
  toggleBlock,
  deleteUser,
} from '@/lib/api';
import { useSession } from '@/lib/session';

const PERIODS = ['all', 'active', 'expired', 'none'] as const;
type Period = (typeof PERIODS)[number];

const SUBSCRIPTION_LABELS: Record<AdminSubscriptionStatus, string> = {
  active: 'Активная',
  expired: 'Истекла',
  none: 'Нет',
};

const STATUS_LABELS: Record<string, string> = {
  active: 'Активен',
  blocked: 'Заблокирован',
};

function initials(name?: string | null, email?: string | null): string {
  const n = (name || '').trim();
  if (n) return n.split(' ').map((p) => p[0]).join('').toUpperCase().slice(0, 2);
  return (email || '').split('@')[0]?.slice(0, 2).toUpperCase() || '?';
}

export default function AdminUsersPage() {
  const t = useTranslations('admin.users');
  const locale = useLocale() as Locale;
  const { user, loading: sessionLoading } = useSession();
  const router = useRouter();

  const [users, setUsers] = useState<AdminUserListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [subscription, setSubscription] = useState<AdminSubscriptionStatus | 'all'>('all');
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: 'created_at', dir: 'desc' });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (sessionLoading) return;
    void loadUsers();
  }, [sessionLoading, limit, offset, search, subscription, sort.key, sort.dir]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getAdminUsers({
        limit,
        offset,
        search: search || undefined,
        subscription: subscription === 'all' ? undefined : subscription,
      });
      let items = data.users;
      // Сортировка на клиенте (бэкенд пока не сортирует)
      items.sort((a, b) => {
        const aVal = (a as any)[sort.key] ?? '';
        const bVal = (b as any)[sort.key] ?? '';
        const cmp = String(aVal).localeCompare(String(b.val), locale, { numeric: true });
        return sort.dir === 'asc' ? cmp : -cmp;
      });
      setUsers(items);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to load users', err);
    } finally {
      setLoading(false);
    }
  }, [limit, offset, search, subscription, sort.key, sort.dir, sessionLoading]);

  const handleGrant = async (id: number) => {
    try {
      await grantSubscription(id, 7);
      void load();
    } catch (err) {
      alert('Не удалось выдать подписку');
    }
  };

  const handleToggleBlock = async (id: number, currentlyBlocked: boolean) => {
    try {
      await toggleBlock(id, !currentlyBlocked);
      void load();
    } catch (err) {
      alert('Не удалось изменить статус');
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('admin.users.confirmDelete'))) return;
    try {
      await deleteUser(id);
      void load();
    } catch (err) {
      alert('Не удалось удалить пользователя');
    }
  };

  if (sessionLoading) {
    return null;
  }
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
        <Link href="/admin" className={GHOST}>
          {t('admin.back')}
        </Link>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex flex-col gap-2">
          <input
            type="text"
            placeholder={t('admin.users.search')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setSubscription(p === 'all' ? 'all' : p)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                subscription === p
                  ? 'bg-blue-600 text-white shadow-blue-950/40'
                  : 'bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white'
              }`}
            >
              {t(`admin.users.filter.${p}`)}
            </button>
          ))}
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0}
            className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-300 hover:bg-white/10 transition disabled:opacity-50"
          >
            Назад
          </button>
          <button
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= total}
            className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-300 hover:bg-white/10 transition disabled:opacity-50"
          >
            Вперёд
          </button>
        </div>
      </div>

      {loading ? (
        <div className="panel p-8 text-center text-sm text-slate-300">
          {t('admin.users.loading')}
        </div>
      ) : (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <table className="w-full text-left text-sm text-slate-300">
            <thead>
              <tr className="border-b border-white/10 text-[11px] uppercase tracking-wide text-slate-400">
                <th className="pb-2.5 font-semibold">{t('admin.users.column.avatar')}</th>
                <th className="pb-2.5 font-semibold">{t('admin.users.column.name')}</th>
                <th className="pb-2.5 font-semibold">{t('admin.users.column.email')}</th>
                <th className="pb-2.5 font-semibold">{t('admin.users.column.tg')}</th>
                <th className="pb-2.5 font-semibold text-right">{t('admin.users.column.level')}</th>
                <th className="pb-2.5 font-semibold text-right">{t('admin.users.column.subscription')}</th>
                <th className="pb-2.5 font-semibold text-right">{t('admin.users.column.activity')}</th>
                <th className="pb-2.5 font-semibold text-right">{t('admin.users.column.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y border-white/5">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-white/5 transition-colors">
                  <td className="py-3 px-3">
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-full bg-blue-500/20 flex items-center justify-center text-blue-500 font-bold text-sm">
                        {initials(u.first_name, u.email)}
                      </div>
                      <div className="flex flex-col min-w-0">
                        <p className="text-sm font-semibold text-slate-900">{u.username || u.first_name || u.email}</p>
                        {u.email ? (
                          <p className="text-[10px] text-slate-500 truncate">{u.email}</p>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td className="py-3 px-3 text-sm text-slate-400">{u.email || '—'}</td>
                  <td className="py-3 px-3 text-sm text-slate-300">{u.tg_id ?? '—'}</td>
                  <td className="py-3 px-3 text-sm text-slate-400">{u.level ?? '—'}</td>
                  <td className="py-3 px-3 text-sm text-slate-400">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-1 text-[10px] font-semibold ${
                        u.subscription_status === 'active'
                          ? 'bg-green-500/20 text-green-400'
                          : u.subscription_status === 'expired'
                          ? 'bg-amber-500/20 text-amber-400'
                          : 'bg-slate-500/20 text-slate-500'
                      }`}
                    >
                      {u.subscription_status === 'active'
                        ? t('admin.users.subscription.active', { date: u.subscription_expires_at })
                        : u.subscription_status === 'expired'
                        ? t('admin.users.subscription.expired', { date: u.subscription_expires_at })
                        : t('admin.users.subscription.none')}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-sm text-slate-400 text-right">{u.created_at ?? '—'}</td>
                  <td className="py-3 px-3 text-right text-sm text-slate-400">
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleGrant(u.id)}
                        className="rounded-lg bg-green-600/20 px-3 py-1 text-[10px] font-semibold text-green-400 hover:bg-green-500/30 transition disabled:opacity-50"
                        disabled={u.subscription_status === 'active'}
                      >
                        {t('admin.users.btn.grant')}
                      </button>
                      <button
                        onClick={() => handleToggleBlock(u.id, u.blocked)}
                        className={`rounded-lg px-3 py-1 text-[10px] font-semibold text-white transition ${u.blocked ? 'bg-green-600 hover:bg-green-500' : 'bg-slate-500/20 text-slate-400 hover:bg-slate-500/30'}`}
                      >
                        {u.blocked ? t('admin.users.btn.unblock') : t('admin.users.btn.block')}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan="8" className="py-8 text-center text-sm text-slate-400">
                    {t('admin.users.empty')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

export default AdminUsersPage;