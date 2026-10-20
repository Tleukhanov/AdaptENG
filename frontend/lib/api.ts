export const TOKEN_KEY = 'adapteng_token';

/**
 * Адрес API — всегда тот же домен, что и сайт: /api/* проксирует Next.js
 * (frontend/app/api/[...path]/route.ts) на бэкенд, адрес которого задан
 * в окружении сервера (API_URL). Так клиент не знает про бэкенд, CORS не
 * нужен, а смена бэкенда не требует пересборки.
 */
export const API = '';

/**
 * Доступен ли бэкенд. Запросы всегда идут на тот же домен (/api/* проксирует
 * Next.js), поэтому «демо-режим» определяется наличием токена, а не адресом.
 */
export const API_ENABLED = true;

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

export type Level = string;

export type ProgressData = {
  level?: Level | null;
  xp?: number;
  total_lessons?: number;
  total_turns?: number;
  correct?: number;
  errors?: number;
  accuracy?: number;
  weak_areas?: string[];
  strong_areas?: string[];
  streak_days?: number;
  character?: unknown;
  interests?: string[];
  next_topic?: string | null;
  due_words?: number | null;
};

export type ReviewWord = {
  id: string | number;
  word: string;
  translation: string;
  example: string;
};

async function request(
  path: string,
  options: ApiOptions,
  kind: 'json' | 'blob',
): Promise<unknown> {
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

  const response = await fetch(path, {
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

/**
 * Текст ошибки от сервера (он более точный, чем локализованный запасной):
 * «Дневной лимит исчерпан» ≠ «очередь переполнена» ≠ «слишком часто пишешь».
 */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message && error.message !== 'request failed') {
    return error.message;
  }
  return fallback;
}

export function apiBlob(path: string, options: ApiOptions = {}): Promise<Blob> {
  return request(path, options, 'blob') as Promise<Blob>;
}

export type StartLessonResponse = {
  deck?: unknown;
  session_id?: number;
  preset?: string;
  topic?: string;
  plan_hint?: string;
};

export function startLesson(topic?: string, preset?: string): Promise<StartLessonResponse> {
  const body = {
    ...(topic !== undefined ? { topic } : {}),
    ...(preset !== undefined ? { preset } : {}),
  };
  return apiFetch<StartLessonResponse>('/api/lesson/new', { method: 'POST', body });
}

export type AnswerQuizResponse = {
  correct: boolean;
  answer_index: number;
  explanation?: string;
  explanation_ru?: string;
};

export function answerQuiz(quizIndex: number, chosen: number): Promise<AnswerQuizResponse> {
  return apiFetch<AnswerQuizResponse>('/api/lesson/answer', {
    method: 'POST',
    body: { quiz_index: quizIndex, chosen },
  });
}

export type QuizAnswerItem = {
  quiz_index: number;
  chosen: number;
  correct: boolean;
};

export type FinishLessonPayload = {
  score: number;
  preset?: string;
  quiz_answers: QuizAnswerItem[];
  flashcards: Record<string, boolean>;
  session_id?: number;
};

export type FinishLessonResponse = {
  score: number;
  xp?: number;
  next_topic?: string | null;
  preset?: string;
  repeat_words?: string[];
};

export function finishLesson(payload: FinishLessonPayload): Promise<FinishLessonResponse> {
  return apiFetch<FinishLessonResponse>('/api/lesson/finish', { method: 'POST', body: payload });
}

export type VoiceAnswerPayload = {
  audio_base64: string;
  expected_line?: string;
  word?: string;
};

export type VoiceAnswerResponse = {
  transcript?: string;
  rating?: number;
  tip?: string;
  expected_line?: string;
};

export function voiceAnswer(payload: VoiceAnswerPayload): Promise<VoiceAnswerResponse> {
  return apiFetch<VoiceAnswerResponse>('/api/lesson/voice', { method: 'POST', body: payload });
}

export type GetProgressResponse = ProgressData & {
  next_topic?: string | null;
  due_words?: number | null;
};

export function getProgress(): Promise<GetProgressResponse> {
  return apiFetch<GetProgressResponse>('/api/progress');
}

export type GetDueWordsResponse = ReviewWord[];

export function getDueWords(): Promise<GetDueWordsResponse> {
  return apiFetch<GetDueWordsResponse>('/api/review/due');
}

export type ReviewWordPayload = {
  word_id: string | number;
  quality: number;
};

export type ReviewWordResponse = {
  ok: boolean;
};

export function reviewWord(wordId: string | number, quality: number): Promise<ReviewWordResponse> {
  return apiFetch<ReviewWordResponse>('/api/review/answer', {
    method: 'POST',
    body: { word_id: wordId, quality } satisfies ReviewWordPayload,
  });
}

export type AchievementItem = {
  id: string;
  name: string;
  emoji: string;
  description: string;
  condition: string;
  earned: boolean;
};

export type LevelInfo = {
  name: string;
  emoji: string;
  xp: number;
  next_level?: string | null;
  xp_needed?: number | null;
};

export type AchievementsResponse = {
  level: LevelInfo;
  achievements: AchievementItem[];
};

export function getAchievements(): Promise<AchievementsResponse> {
  return apiFetch<AchievementsResponse>('/api/achievements');
}

export type LeaderboardEntry = {
  user_id: number;
  username?: string | null;
  first_name?: string | null;
  level?: string | null;
  xp: number;
  total_lessons: number;
  streak_days: number;
};

export function getLeaderboard(limit = 20): Promise<LeaderboardEntry[]> {
  return apiFetch<LeaderboardEntry[]>(`/api/leaderboard?limit=${limit}`);
}

export type ProfileData = {
  goal: string;
  interests: string[];
  weak_areas: string[];
  preferred_format: string;
  notes: string;
  level: string | null;
  character: string;
  has_profile: boolean;
};

export type ProfilePayload = {
  goal?: string;
  interests?: string[];
  weak_areas?: string[];
  preferred_format?: string;
  notes?: string;
  level?: string;
};

export function getProfile(): Promise<ProfileData> {
  return apiFetch<ProfileData>('/api/me/profile');
}

export function updateProfile(payload: ProfilePayload): Promise<ProfileData> {
  return apiFetch<ProfileData>('/api/me/profile', {
    method: 'PUT',
    body: payload satisfies ProfilePayload,
  });
}

export type DiagnosticTask = {
  text: string;
  level_hint: string;
};

export type DiagnosticResult = {
  level: string;
  confidence: number;
  explanation_ru: string;
  strengths: string[];
  weaknesses: string[];
  recommendation: string;
};

export function startDiagnostic(): Promise<{ tasks: DiagnosticTask[] }> {
  return apiFetch<{ tasks: DiagnosticTask[] }>('/api/diagnostic/start', {
    method: 'POST',
  });
}

export function finishDiagnostic(
  answers: string[],
  tasks: DiagnosticTask[],
): Promise<DiagnosticResult> {
  return apiFetch<DiagnosticResult>('/api/diagnostic/finish', {
    method: 'POST',
    body: { answers, tasks },
  });
}