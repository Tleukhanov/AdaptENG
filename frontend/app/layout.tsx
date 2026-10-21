import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { NextIntlClientProvider } from 'next-intl';
import { getTranslations } from 'next-intl/server';
import { getLocale, getMessages } from '@/lib/i18n';
import LocaleToggle from '@/components/LocaleToggle';
import SessionNav from '@/components/SessionNav';
import { SessionProvider } from '@/lib/session';
import './globals.css';

export const metadata: Metadata = {
  title: 'AdaptENG — AI English Tutor',
  description: 'Adaptive AI English tutor with personality characters.',
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const messages = getMessages(locale);
  const t = await getTranslations({ locale });

  return (
    <html lang={locale}>
      <body className="antialiased">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <SessionProvider>
            <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-white/80 backdrop-blur">
              <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
                <Link href="/" className="flex items-center gap-2 text-lg font-bold">
                  <span className="adapteng-gradient flex h-8 w-8 items-center justify-center rounded-xl text-sm font-bold text-white">
                    AE
                  </span>
                  <span className="adapteng-text-gradient">AdaptENG</span>
                </Link>
                <nav className="flex items-center gap-3 text-sm font-medium text-slate-600 sm:gap-5">
                  <Link
                    href="/"
                    className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 transition hover:text-slate-900"
                  >
                    {t('nav.home')}
                  </Link>
                  <Link
                    href="/dashboard"
                    className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 transition hover:text-slate-900"
                  >
                    {t('nav.profile')}
                  </Link>
                  <LocaleToggle />
                  <SessionNav />
                </nav>
              </div>
            </header>
            {children}
          </SessionProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
