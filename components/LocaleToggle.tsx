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
      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl border border-white/15 bg-white/5 px-3 text-xs font-semibold uppercase tracking-wide text-slate-100 transition hover:border-white/25 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
    >
      {nextLocale.toUpperCase()}
    </button>
  );
}
