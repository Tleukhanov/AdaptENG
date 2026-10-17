'use client';

import { useLocale } from 'next-intl';

export default function LocaleToggle() {
  const locale = useLocale();
  const nextLocale = locale === 'ru' ? 'en' : 'ru';

  function handleToggle() {
    document.cookie = `locale=${nextLocale}; path=/; max-age=${60 * 60 * 24 * 365}; samesite=lax`;
    window.location.reload();
  }

  return (
    <button
      type="button"
      onClick={handleToggle}
      aria-label="Switch language"
      className="inline-flex min-h-[36px] min-w-[44px] items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold uppercase text-slate-600 transition hover:bg-slate-100"
    >
      {nextLocale.toUpperCase()}
    </button>
  );
}
