import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { NextIntlClientProvider } from 'next-intl';
import { Cormorant_Garamond, Golos_Text } from 'next/font/google';
import { getTranslations } from 'next-intl/server';
import { getLocale, getMessages } from '@/lib/i18n';
import LocaleToggle from '@/components/LocaleToggle';
import Logo from '@/components/Logo';
import PwaProvider from '@/components/PwaProvider';
import SessionNav from '@/components/SessionNav';
import { SessionProvider } from '@/lib/session';
import './globals.css';

const display = Cormorant_Garamond({
  subsets: ['latin', 'cyrillic'],
  variable: '--font-display',
  display: 'swap',
  weight: ['400', '500', '600', '700'],
  style: ['normal', 'italic'],
});

const body = Golos_Text({
  subsets: ['latin', 'cyrillic'],
  variable: '--font-body',
  display: 'swap',
  weight: ['400', '500', '600', '700'],
});

export const metadata: Metadata = {
  title: 'AdaptENG — AI English Tutor',
  description: 'Adaptive AI English tutor with personality characters.',
  applicationName: 'AdaptENG',
  // Устанавливаемое приложение: тёмная строка состояния на iOS.
  appleWebApp: {
    capable: true,
    title: 'AdaptENG',
    statusBarStyle: 'black-translucent',
  },
  icons: {
    // app/icon.svg остаётся фавиконом; явный icons.apple добавляем для iOS.
    icon: [{ url: '/icon.svg', type: 'image/svg+xml' }],
    apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#f4efe6',
  colorScheme: 'light',
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const messages = getMessages(locale);
  const t = await getTranslations({ locale });

  return (
    <html lang={locale}>
      <body className={`${display.variable} ${body.variable} antialiased`}>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <SessionProvider>
            <header className="sticky top-0 z-40 border-b border-ink-900/10 bg-paper-100/80 backdrop-blur">
              <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
                <Link href="/" className="flex items-center gap-2" aria-label="AdaptENG">
                  <span className="font-display text-2xl font-semibold tracking-tight text-ink-900">
                    Adapt<span className="text-accent-600">ENG</span>
                  </span>
                </Link>
                <nav className="flex items-center gap-1 text-sm font-medium text-ink-700 sm:gap-3">
                  <Link
                    href="/"
                    className="inline-flex min-h-[36px] items-center rounded-md px-3 py-2 transition hover:text-accent-600"
                  >
                    {t('nav.home')}
                  </Link>
                  <Link
                    href="/dashboard"
                    className="inline-flex min-h-[36px] items-center rounded-md px-3 py-2 transition hover:text-accent-600"
                  >
                    {t('nav.profile')}
                  </Link>
                  <LocaleToggle />
                  <SessionNav />
                </nav>
              </div>
            </header>
            {children}
            <PwaProvider />
          </SessionProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
