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

  const method = request.method.toUpperCase();
  const hasBody = method !== 'GET' && method !== 'HEAD';

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: 'manual',
    });
  } catch (error) {
    return new Response(
      JSON.stringify({ detail: 'Бэкенд недоступен' }),
      { status: 502, headers: { 'content-type': 'application/json' } },
    );
  }

  const outHeaders = new Headers();
  for (const name of PASSTHROUGH_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) {
      outHeaders.set(name, value);
    }
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