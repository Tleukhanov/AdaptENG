'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useTranslations } from 'next-intl';

/**
 * Страница после перехода по ссылке из письма.
 *
 * Сам токен уже проверил бэкенд (`GET /api/auth/verify` → редирект сюда
 * со `status=ok|error`), поэтому здесь только показываем результат.
 */
export default function VerifyPage() {
  const t = useTranslations('verify');
  const params = useSearchParams();
  const [status, setStatus] = useState<'ok' | 'error' | 'checking'>('checking');

  useEffect(() => {
    const value = params.get('status');
    setStatus(value === 'ok' ? 'ok' : value === 'error' ? 'error' : 'checking');
  }, [params]);

  return (
    <main className="page-dark flex min-h-screen items-center justify-center px-4">
      <div className="panel glow-soft w-full max-w-md p-8 text-center">
        {status === 'checking' && (
          <p className="text-slate-300" role="status">
            {t('checking')}
          </p>
        )}

        {status === 'ok' && (
          <>
            <p className="text-4xl" aria-hidden>
              ✅
            </p>
            <h1 className="mt-4 text-2xl font-bold text-white">{t('okTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('okText')}</p>
            <Link
              href="/menu"
              className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-500"
            >
              {t('toMenu')}
            </Link>
          </>
        )}

        {status === 'error' && (
          <>
            <p className="text-4xl" aria-hidden>
              ⚠️
            </p>
            <h1 className="mt-4 text-2xl font-bold text-white">{t('errorTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('errorText')}</p>
            <Link
              href="/menu"
              className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-500"
            >
              {t('toMenu')}
            </Link>
          </>
        )}
      </div>
    </main>
  );
}
