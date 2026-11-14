'use client';

import { useEffect, useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { getAdminUser, grantSubscription, toggleBlock, deleteUser, type AdminUserDetail } from '@/lib/api';
import { useSession } from '@/lib/session';

const GHOST =
  'inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-slate-300 transition hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40';

export default function AdminUserPage() {
  const t = useTranslations('admin.users');
  const router = useRouter();
  const { user } = useSession();

  const [userData, setUserData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [blocking, setBlocking] = useState(false);
  const [granting, setGranting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadUser = useCallback(async () => {
    if (sessionLoading) return;
    setLoading(true);
    try {
      const data = await getAdminUser(userId);
      setUserData(data);
    } catch (err) {
      console.error('Failed to load user', err);
    } finally {
      setLoading(false);
    }
  }, [userId, sessionLoading]);

  useEffect(() => {
    loadUser();
  }, [loadUser, userId]);

  const handleGrant = async (days: number) => {
    setGranting(true);
    try {
      await grantSubscription(userId, days);
      void loadUser();
    } catch (err) {
      console.error('Failed to grant subscription', err);
    } finally {
      setGranting(false);
    }
  };

  const handleBlock = async (blocked: boolean) => {
    setBlocking(true);
    try {
      await toggleBlock(userId, blocked);
      void loadUser();
    } catch (err) {
      console.error('Failed to toggle block', err);
    } finally {
      setBlocking(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(t('admin.users.confirmDelete'))) return;
    setDeleting(true);
    try {
      await deleteUser(userId);
      router.push('/admin/users');
    } catch (err) {
      console.error('Failed to delete user', err);
    } finally {
      setDeleting(false);
    }
  };

  if (sessionLoading) return null;
  if (!user) {
    router.replace('/login');
    return null;
  }

  const u = userData?.user;
  const stats = userData?.stats;
  const sub = userData?.subscription;
  const recentActivity = userData?.recentActivity || [];

  if (!u || loading) {
    return (
      <main className="mx-auto max-w-7xl px-4 py-8">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">{t('admin.users.title')}</h1>
            <Link href="/admin/users" className={GHOST}>
              {t('admin.back')}
            </Link>
          </div>
        </div>
        <div className="mt-8 flex justify-center items-center min-h-[200px]">
          <p className="text-sm text-slate-400">{t('admin.users.loading')}</p>
        </div>
      </div>
    </main>
  );
}

const formatDate = (dateString?: string | null) => {
  if (!dateString) return '—';
  try {
    return new Date(dateString).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return dateString;
  }
};

export default function AdminUserPage() {
  const t = useTranslations('admin.users');
  const router = useRouter();
  const { user } = useSession();

  const [userData, setUserData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [blocking, setBlocking] = useState(false);
  const [granting, setGranting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadUser = useCallback(async () => {
    if (sessionLoading) return;
    setLoading(true);
    try {
      const data = await getAdminUser(userId);
      setUserData(data);
    } catch (err) {
      console.error('Failed to load user', err);
    } finally {
      setLoading(false);
    }
  }, [userId, sessionLoading]);

  useEffect(() => {
    loadUser();
  }, [loadUser, userId]);

  const handleGrant = async (days: number) => {
    setGranting(true);
    try {
      await grantSubscription(userId, days);
      void loadUser();
    } catch (err) {
      console.error('Failed to grant subscription', err);
    } finally {
      setGranting(false);
    }
  };

  const handleBlock = async (blocked: boolean) => {
    setBlocking(true);
    try {
      await toggleBlock(userId, blocked);
      void loadUser();
    } catch (err) {
      console.error('Failed to toggle block', err);
    } finally {
      setBlocking(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(t('admin.users.confirmDelete'))) return;
    setDeleting(true);
    try {
      await deleteUser(userId);
      router.push('/admin/users');
    } catch (err) {
      console.error('Failed to delete user', err);
    } finally {
      setDeleting(false);
    }
  };

  if (sessionLoading) return null;
  if (!user) {
    router.replace('/login');
    return null;
  }

  const u = userData?.user;
  const stats = userData?.stats;
  const sub = userData?.subscription;
  const recentActivity = userData?.recentActivity || [];

  if (!u || loading) {
    return (
      <main className="mx-auto max-w-7xl px-4 py-8">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">{t('admin.users.title')}</h1>
            <Link href="/admin/users" className={GHOST}>
              {t('admin.back')}
            </Link>
          </div>
        </div>
        <div className="mt-8 flex justify-center items-center min-h-[200px]">
          <p className="text-sm text-slate-400">{t('admin.users.loading')}</p>
        </div>
      </div>
    </main>
  );
}

export default function AdminUserPage() {
  const t = useTranslations('admin.users');
  const router = useRouter();
  const { user } = useSession();

  const [userData, setUserData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [blocking, setBlocking] = useState(false);
  const [granting, setGranting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadUser = useCallback(async () => {
    if (sessionLoading) return;
    setLoading(true);
    try {
      const data = await getAdminUser(userId);
      setUserData(data);
    } catch (err) {
      console.error('Failed to load user', err);
    } finally {
      setLoading(false);
    }
  }, [userId, sessionLoading]);

  useEffect(() => {
    loadUser();
  }, [loadUser, userId]);

  const handleGrant = async (days: number) => {
    setGranting(true);
    try {
      await grantSubscription(userId, days);
      void loadUser();
    } catch (err) {
      console.error('Failed to grant subscription', err);
    } finally {
      setGranting(false);
    }
  };

  const handleBlock = async (blocked: boolean) => {
    setBlocking(true);
    try {
      await toggleBlock(userId, blocked);
      void loadUser();
    } catch (err) {
      console.error('Failed to toggle block', err);
    } finally {
      setBlocking(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(t('admin.users.confirmDelete'))) return;
    setDeleting(true);
    try {
      await deleteUser(userId);
      router.push('/admin/users');
    } catch (err) {
      console.error('Failed to delete user', err);
    } finally {
      setDeleting(false);
    }
  };

  if (sessionLoading) return null;
  if (!user) {
    router.replace('/login');
    return null;
  }

  const u = userData?.user;
  const stats = userData?.stats;
  const sub = userData?.subscription;
  const recentActivity = userData?.recentActivity || [];

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('admin.users.title')}</h1>
          <Link href="/admin/users" className={GHOST}>
            {t('admin.back')}
          </Link>
        </div>
        <div className="mt-2 text-sm text-slate-400">
          {u.email} ({u.tg_id ? 'TG: ' + u.tg_id : 'без Telegram'})
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
        <div className="p-4 rounded-xl border border-white/10 bg-white/5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.level')}
          </p>
          <p className="mt-2 text-sm text-slate-200">{u.level || '—'}</p>
        </div>
        <div className="p-4 rounded-xl border border-white/10 bg-white/5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.interests')}
          </p>
          <p className="mt-2 text-sm text-slate-200">
            {u.interests?.join(', ') || '—'}
          </p>
        </div>
        <div className="p-4 rounded-xl border border-white/10 bg-white/5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.quota')}
          </p>
          <p className="mt-2 text-sm text-slate-200">
            {u.quota_left ?? '—'}{u.quota_total ? ' / ' + u.quota_total : ''}
          </p>
        </div>
        <div className="p-4 rounded-xl border border-white/10 bg-white/5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.created')}
          </p>
          <p className="mt-2 text-sm text-slate-200">{formatDate(u.createdAt)}</p>
        </div>
      </div>

      <div className="mt-6 grid gap-6 sm:grid-cols-3 lg:grid-cols-4">
        <div className="rounded-xl border border-white/10 bg-white/5 p-6">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.totalTurns')}
          </p>
          <p className="mt-2 text-sm text-slate-200">{stats?.total_turns ?? 0}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/5 p-6">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.correct')}
          </p>
          <p className="mt-2 text-sm text-slate-200">{stats?.correct ?? 0}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/5 p-6">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.errors')}
          </p>
          <p className="mt-2 text-sm text-slate-200">{stats?.errors ?? 0}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/5 p-6">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('admin.users.column.weak')}
          </p>
          <p className="mt-2 text-sm text-slate-200">{stats?.weak_areas?.length ?? 0}</p>
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-white/10 bg-white/5 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-xl font-bold text-slate-900">{t('admin.users.subscription')}</h1>
            <p className="mt-1 text-sm text-slate-400">{t('admin.users.subscriptionLabel')}</p>
          </div>
          <div className="flex gap-2">
            {sub ? (
              <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold text-white bg-gradient-to-r from-green-500 to-emerald-500">
                {t('admin.users.subscription.active')} &nbsp;•&nbsp; {formatDate(sub.expires_at)}
              </span>
            ) : (
              <span className="inline-flex rounded-full px-3 py-1 text-xs font-semibold text-white bg-slate-500/20">
                {t('admin.users.subscription.none')}
              </span>
            )}
          </div>
        </div>
        {sub ? (
          <div className="mt-4 flex flex-wrap gap-4">
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {t('admin.users.subscription.plan')}
              </p>
              <p className="mt-2 text-sm text-slate-200">{sub.planDays ?? '—'} {t('admin.users.subscription.days')}</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {t('admin.users.subscription.started')}
              </p>
              <p className="mt-2 text-sm text-slate-200">{formatDate(sub.granted_at)}</p>
            </div>
          </div>
        ) : null}
        <div className="mt-6">
          <button
            onClick={() => handleGrant(7)}
            disabled={granting}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {granting ? t('admin.users.granting') : t('admin.users.grant7')}
          </button>
          <button
            onClick={() => handleGrant(30)}
            disabled={granting}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-500/20 px-5 py-3 text-sm font-semibold text-slate-200 shadow-lg shadow-blue-950/40 transition hover:bg-blue-500/30 disabled:opacity-50"
          >
            {t('admin.users.grant30')}
          </button>
        </div>
        <div className="mt-6 flex flex-wrap items-start gap-3">
          <button
            onClick={() => handleBlock(!u.blocked)}
            disabled={blocking}
            className={`flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold transition disabled:opacity-50 ${
              u.blocked
                ? 'bg-red-500/20 text-red-500 hover:bg-red-500/30'
                : 'bg-slate-500/20 text-slate-500 hover:bg-slate-500/30'
            }`}
          >
            {u.blocked ? t('admin.users.action.unblock') : t('admin.users.action.block')}
          </button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="flex items-center gap-2 rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm font-semibold text-red-500 transition hover:bg-red-500/30 disabled:opacity-50"
          >
            {t('admin.users.action.delete')}
          </button>
        </div>
      </div>
    </main>
  );
}