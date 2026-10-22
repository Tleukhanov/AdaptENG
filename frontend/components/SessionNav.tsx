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
    return <div className="h-9 w-16 animate-pulse rounded-lg bg-slate-200" aria-hidden />;
  }

  // Неавторизованным кнопку входа не показываем: основной путь — онбординг
  // «Начать бесплатно», а вход доступен ссылкой в футере.
  if (!user) {
    return null;
  }

  const label = user.email || user.first_name || t('nav.profile');

  return (
    <div className="flex items-center gap-2">
      <span className="hidden max-w-[160px] truncate text-xs text-slate-500 sm:inline">{label}</span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          router.push('/');
          router.refresh();
        }}
        className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-slate-600 transition hover:text-slate-900"
      >
        {t('nav.logout')}
      </button>
    </div>
  );
}
