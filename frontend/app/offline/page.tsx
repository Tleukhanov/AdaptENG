import type { Metadata } from 'next';
import { getTranslations } from 'next-intl/server';
import Link from 'next/link';
import OfflineRetry from '@/components/OfflineRetry';

export const metadata: Metadata = {
  title: 'AdaptENG — Offline',
  // Offline shell: keep it out of search results.
  robots: { index: false, follow: false },
};

/**
 * Offline fallback served by the service worker when a navigation fails.
 *
 * Fully self-contained (no data fetching) so the pre-cached HTML keeps working
 * without a network. "Повторить" reloads the failed URL, the link goes home.
 */
export default async function OfflinePage() {
  const t = await getTranslations();

  return (
    <main className="page-dark flex min-h-[calc(100vh-4rem)] items-center justify-center px-4 py-16">
      <div className="panel glow-soft w-full max-w-md p-8 text-center">
        <div
          aria-hidden
          className="adapteng-gradient mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-2xl font-bold text-white shadow-lg shadow-blue-950/40"
        >
          !
        </div>
        <h1 className="mt-6 text-2xl font-bold text-white">{t('offline.title')}</h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-300">{t('offline.subtitle')}</p>
        <OfflineRetry />
        <Link
          href="/"
          className="mt-3 inline-flex min-h-[44px] w-full items-center justify-center rounded-xl border border-white/15 bg-white/5 px-6 py-3 text-sm font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
        >
          {t('offline.home')}
        </Link>
        <p className="mt-4 text-xs text-slate-400">{t('offline.hint')}</p>
      </div>
    </main>
  );
}
