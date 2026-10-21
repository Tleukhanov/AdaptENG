/**
 * Прокси /api/* → бэкенд.
 *
 * Зачем: браузер общается только с одним доменом (adapteng.app), адрес API
 * не торчит наружу, CORS не нужен, а смена бэкенда — это переменная
 * окружения API_URL, без пересборки фронта.
 *
 * Целевой адрес берётся из API_URL (server-side, читается в рантайме).
 */

const API_URL = (process.env.API_URL ?? '').replace(/\/$/, '');

const HOP_BY_HOP = new Set([
  'host',
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'content-length',
  'accept-encoding',
]);

const PASSTHROUGH_RESPONSE_HEADERS = [
  'content-type',
  'cache-control',
  'etag',
  'last-modified',
  'retry-after',
  'content-disposition',
];

/** Максимальный размер тела, который пробрасываем на бэкенд (аудио в base64/multipart). */
const MAX_BODY_BYTES = 12 * 1024 * 1024;

/** Таймаут запроса к бэкенду. Heroku-роутер отдаёт 30 c, поэтому берём с запасом. */
const UPSTREAM_TIMEOUT_MS = 28_000;

/**
 * Реальный IP клиента.
 *
 * Heroku дописывает настоящий адрес в конец X-Forwarded-For, поэтому берём
 * ПОСЛЕДНЕЕ значение, а не первое: иначе клиент подменой заголовка обходит
 * rate limit по IP на бэкенде.
 */
function clientIp(request: Request): string {
  const xff = request.headers.get('x-forwarded-for');
  if (xff) {
    const parts = xff.split(',').map((p) => p.trim()).filter(Boolean);
    if (parts.length > 0) {
      return parts[parts.length - 1];
    }
  }
  return request.headers.get('x-real-ip') ?? 'unknown';
}

type Context = { params: Promise<{ path: string[] }> };

async function handler(request: Request, context: Context): Promise<Response> {
  if (!API_URL) {
    return new Response(
      JSON.stringify({ detail: 'API_URL не задан на сервере' }),
      { status: 500, headers: { 'content-type': 'application/json' } },
    );
  }

  const { path } = await context.params;
  const incoming = new URL(request.url);
  const target = new URL(`${API_URL}/api/${path.join('/')}`);
  target.search = incoming.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  headers.set('x-forwarded-host', incoming.host);
  headers.set('x-forwarded-proto', incoming.protocol.replace(':', ''));
  headers.set('x-forwarded-for', clientIp(request));

  const method = request.method.toUpperCase();
  const hasBody = method !== 'GET' && method !== 'HEAD';

  const declaredLength = Number(request.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_BODY_BYTES) {
    return new Response(
      JSON.stringify({ detail: 'Тело запроса слишком большое' }),
      { status: 413, headers: { 'content-type': 'application/json' } },
    );
  }

  let upstream: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: 'manual',
      signal: controller.signal,
    });
  } catch (error) {
    const aborted = controller.signal.aborted;
    return new Response(
      JSON.stringify({ detail: aborted ? 'Бэкенд не ответил вовремя' : 'Бэкенд недоступен' }),
      { status: aborted ? 504 : 502, headers: { 'content-type': 'application/json' } },
    );
  } finally {
    clearTimeout(timer);
  }

  const outHeaders = new Headers();
  for (const name of PASSTHROUGH_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) {
      outHeaders.set(name, value);
    }
  }
  // Куки сессии (HttpOnly) обязаны доехать до браузера.
  const setCookies = upstream.headers.getSetCookie?.() ?? [];
  for (const cookie of setCookies) {
    outHeaders.append('set-cookie', cookie);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: outHeaders,
  });
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const OPTIONS = handler;
export const HEAD = handler;