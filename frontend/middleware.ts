import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const LOCALE_COOKIE = 'locale';
const ONE_YEAR = 60 * 60 * 24 * 365;

function detectLocale(request: NextRequest): 'ru' | 'en' {
  const acceptLanguage = (request.headers.get('accept-language') ?? '').toLowerCase();
  return acceptLanguage.includes('ru') ? 'ru' : 'en';
}

export function middleware(request: NextRequest) {
  const current = request.cookies.get(LOCALE_COOKIE)?.value;

  if (current === 'ru' || current === 'en') {
    return NextResponse.next();
  }

  const locale = detectLocale(request);
  request.cookies.set(LOCALE_COOKIE, locale);

  const response = NextResponse.next({ request: { headers: request.headers } });
  response.cookies.set(LOCALE_COOKIE, locale, {
    path: '/',
    maxAge: ONE_YEAR,
    sameSite: 'lax',
  });
  return response;
}

export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|svg|gif|webp|ico)$).*)',
  ],
};
