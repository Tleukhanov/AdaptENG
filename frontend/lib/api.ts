export const TOKEN_KEY = 'adapteng_token';

export const API = process.env.NEXT_PUBLIC_API_URL ?? '';

export type ApiOptions = {
  method?: string;
  body?: unknown;
};

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function getToken(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.removeItem(TOKEN_KEY);
}

async function request(
  path: string,
  options: ApiOptions,
  kind: 'json' | 'blob',
): Promise<unknown> {
  if (!API) {
    throw new ApiError('API is not configured', 0);
  }

  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body,
  });

  if (!response.ok) {
    let message = 'request failed';
    try {
      const data = (await response.json()) as { error?: string; detail?: string };
      if (data && typeof data.error === 'string' && data.error) {
        message = data.error;
      } else if (data && typeof data.detail === 'string' && data.detail) {
        message = data.detail;
      }
    } catch {
      // response had no JSON body
    }
    throw new ApiError(message, response.status);
  }

  return kind === 'blob' ? response.blob() : response.json();
}

export function apiFetch<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  return request(path, options, 'json') as Promise<T>;
}

export function apiBlob(path: string, options: ApiOptions = {}): Promise<Blob> {
  return request(path, options, 'blob') as Promise<Blob>;
}
