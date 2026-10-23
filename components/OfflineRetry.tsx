'use client';

import { useTranslations } from 'next-intl';

/**
 * "Retry" button for the offline page.
 *
 * A full reload re-runs the failed navigation: while the network is still down
 * the service worker answers with this page again, once it is back the reload
 * reaches the real page. `navigator.onLine` is only a hint, so the button is
 * never disabled.
 */
export default function OfflineRetry() {
  const t = useTranslations();

  return (
    <button
      type="button"
      onClick={() => window.location.reload()}
      className="mt-7 inline-flex min-h-[48px] w-full items-center justify-center rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-900/40 transition hover:from-blue-500 hover:to-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
    >
      {t('offline.retry')}
    </button>
  );
}
