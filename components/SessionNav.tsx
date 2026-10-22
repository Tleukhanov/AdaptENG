'use client';

import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { useSession } from '@/lib/session';

/** Кнопки входа/выхода в шапке. */
export default function SessionNav() {
  const t = useTranslations();
  const router = useRouter();
  const { user, loading, logout } = useSession();

  if (loading) {
    return (
      <div
        className="h-9 w-20 animate-pulse rounded-xl border border-white/10 bg-white/10"
        aria-hidden
      />
    );
  }

  // Неавторизованным кнопку входа не показываем: основной путь — онбординг
  // «Начать бесплатно», а вход доступен ссылкой в футере.
  if (!user) {
    return null;
  }

  const label = user.email || user.first_name || t('nav.profile');

  return (
    <div className="flex items-center gap-2">
      <span className="hidden max-w-[160px] truncate text-xs text-slate-300 sm:inline">{label}</span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          router.push('/');
          router.refresh();
        }}
        className="inline-flex min-h-[44px] items-center rounded-xl border border-white/10 bg-white/5 px-3 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
      >
        {t('nav.logout')}
      </button>
    </div>
  );
}
