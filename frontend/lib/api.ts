/**
 * Сессия живёт в HttpOnly-cookie (`adapteng_session`), поэтому токен не лежит
 * в localStorage и недоступен скриптам. Браузер сам прикладывает cookie к
 * запросам на тот же домен (same-origin прокси /api/*).
 */
export const UNAUTHORIZED_EVENT = 'adapteng:unauthorized';
/** Событие «сессия изменилась» — его слушает SessionProvider. */
export const SESSION_EVENT = 'adapteng:session';

function notifySessionChanged(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(SESSION_EVENT));
  }
}

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

export type SessionUser = {
  id: number;
  tg_id?: number | null;
  email?: string;
  username?: string;
  first_name?: string;
  level?: string | null;
  character?: string;
  interests?: string[];
  quota_left?: number | null;
  quota_total?: number | null;
  is_unlimited?: boolean;
  total_turns?: number;
  correct?: number;
  errors?: number;
};

let sessionUser: SessionUser | null = null;
let sessionLoaded = false;

function notifyUnauthorized(): void {
  sessionUser = null;
  sessionLoaded = true;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}

export function cachedSession(): SessionUser | null {
  return sessionUser;
}

export function resetSession(): void {
  sessionUser = null;
  sessionLoaded = false;
}

/** Текущий пользователь (null, если сессии нет). Кэшируется до logout/401. */
export async function getSession(force = false): Promise<SessionUser | null> {
  if (sessionLoaded && !force) {
    return sessionUser;
  }
  try {
    const data = await apiFetch<{ user: SessionUser }>('/api/me');
    sessionUser = data.user;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      sessionUser = null;
    } else {
      sessionUser = null;
    }
  }
  sessionLoaded = true;
  return sessionUser;
}

/** Доступно ли серверное распознавание речи (иначе — распознаём в браузере). */
let sttAvailable: boolean | null = null;

export async function serverSttAvailable(force = false): Promise<boolean> {
  if (sttAvailable !== null && !force) {
    return sttAvailable;
  }
  try {
    const data = await apiFetch<{ ok: boolean; stt_available?: boolean }>('/api/health');
    sttAvailable = data.stt_available === true;
  } catch {
    sttAvailable = false;
  }
  return sttAvailable;
}

export type AuthResult = { user: SessionUser };

export async function login(email: string, password: string): Promise<AuthResult> {
  const data = await apiFetch<{ token: string; user: SessionUser }>('/api/auth/login', {
    method: 'POST',
    body: { email, password },
  });
  sessionUser = data.user;
  sessionLoaded = true;
  notifySessionChanged();
  return { user: data.user };
}

export async function register(
  email: string,
  password: string,
  name?: string,
): Promise<AuthResult> {
  const data = await apiFetch<{ token: string; user: SessionUser }>('/api/auth/register', {
    method: 'POST',
    body: { email, password, name: name ?? '' },
  });
  sessionUser = data.user;
  sessionLoaded = true;
  notifySessionChanged();
  return { user: data.user };
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<{ ok: boolean }>('/api/auth/logout', { method: 'POST' });
  } catch {
    // даже если запрос не прошёл — сбрасываем локальное состояние
  }
  resetSession();
  notifySessionChanged();
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

  const response = await fetch(path, {
    method: options.method ?? 'GET',
    headers,
    body,
    credentials: 'include',
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
    if (response.status === 401) {
      notifyUnauthorized();
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

export type TranscribeResponse = {
  transcript?: string;
  rating?: number;
  tip?: string;
  expected_line?: string;
  duration_sec?: number;
};

/**
 * Распознавание речи вне урока: файл уходит multipart-файлом (без base64),
 * поэтому не раздувается на треть и не упирается в лимит JSON.
 */
export async function transcribeAudio(
  blob: Blob,
  options: { expectedLine?: string; word?: string; mode?: 'free' | 'word' | 'lesson' } = {},
): Promise<TranscribeResponse> {
  const form = new FormData();
  const name = blob.type.includes('mp4') ? 'voice.m4a' : blob.type.includes('ogg') ? 'voice.ogg' : 'voice.webm';
  form.append('file', blob, name);
  if (options.expectedLine) {
    form.append('expected_line', options.expectedLine);
  }
  if (options.word) {
    form.append('word', options.word);
  }
  form.append('mode', options.mode ?? 'free');

  const response = await fetch('/api/voice', {
    method: 'POST',
    body: form,
    credentials: 'include',
  });
  if (!response.ok) {
    let message = 'request failed';
    try {
      const data = (await response.json()) as { detail?: string };
      if (data && typeof data.detail === 'string' && data.detail) {
        message = data.detail;
      }
    } catch {
      // без JSON-тела
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as TranscribeResponse;
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

// ---------- гостевой онбординг (до регистрации) ----------

export type GuestGoal = 'exam' | 'communication' | 'work' | 'general';
export type GuestMinutes = 10 | 20 | 30 | 60;
export type GuestLevel = 'A1' | 'A2' | 'B1' | 'B2' | 'C1';

/**
 * Ответы гостевого онбординга. Живут в подписанной HttpOnly-cookie
 * (`adapteng_guest`), поэтому читать их из JS нельзя — только через
 * `getGuestProfile`. При регистрации сервер переносит их в профиль.
 */
export type GuestProfile = {
  goal: GuestGoal;
  minutes: GuestMinutes;
  level: GuestLevel;
};

/** Гостевой профиль из cookie; `null`, если гость ещё не отвечал. */
export async function getGuestProfile(): Promise<GuestProfile | null> {
  const data = await apiFetch<{ profile: GuestProfile | null }>('/api/guest/profile');
  return data.profile ?? null;
}

/** Сохраняет ответы онбординга (ставит HttpOnly-cookie). */
export async function saveGuestProfile(profile: GuestProfile): Promise<GuestProfile> {
  const data = await apiFetch<{ profile: GuestProfile }>('/api/guest/profile', {
    method: 'POST',
    body: profile satisfies GuestProfile,
  });
  return data.profile;
}

/** Сбрасывает гостевой профиль. */
export async function clearGuestProfile(): Promise<void> {
  await apiFetch<{ ok: boolean }>('/api/guest/profile', { method: 'DELETE' });
}

// ---------- «Урок 0»: знакомство с наставником ----------
//
// Работает и для гостя (сессия привязана к подписанной HttpOnly-cookie
// `adapteng_tutor`), и для залогиненного пользователя. Повторный
// `startTutorSession()` вернёт ту же активную сессию.

export type TutorTurnKind = 'ask' | 'teach' | 'correct' | 'praise' | 'finish' | string;

export type TutorIssue = {
  problem: string;
  suggestion: string;
};

export type TutorCorrection = {
  corrected_text: string;
  issues: TutorIssue[];
};

export type TutorTurn = {
  /** Текст наставника — его же читает TTS. */
  reply: string;
  kind: TutorTurnKind;
  question?: string | null;
  correction?: TutorCorrection | null;
  /** Приходят не во всех версиях бэкенда — поэтому опциональны. */
  interests?: string[];
  level_signal?: string;
  should_finish?: boolean;
};

export type TutorSessionResponse = {
  session_id: number;
  turn: TutorTurn;
  turn_index: number;
  max_turns: number;
};

export type TutorTurnResponse = {
  turn: TutorTurn;
  turn_index: number;
  max_turns: number;
  should_finish: boolean;
};

export type TutorSummary = {
  level: string;
  confidence: number;
  matches_self_level: boolean;
  interests: string[];
  strengths: string[];
  weaknesses: string[];
  recommendation: string;
  praise: string;
};

export type TutorFinishResponse = {
  summary: TutorSummary;
  turns: number;
  xp: number;
  streak_days: number;
  registered: boolean;
};

export function startTutorSession(mode: 'intro' = 'intro'): Promise<TutorSessionResponse> {
  return apiFetch<TutorSessionResponse>('/api/tutor/session', {
    method: 'POST',
    body: { mode },
  });
}

export function sendTutorTurn(sessionId: number, text: string): Promise<TutorTurnResponse> {
  return apiFetch<TutorTurnResponse>('/api/tutor/turn', {
    method: 'POST',
    body: { session_id: sessionId, text },
  });
}

export function finishTutorSession(sessionId: number): Promise<TutorFinishResponse> {
  return apiFetch<TutorFinishResponse>('/api/tutor/finish', {
    method: 'POST',
    body: { session_id: sessionId },
  });
}

// ---------- словарь ----------

export type VocabStatus = 'learning' | 'known';

export type VocabWord = {
  id: number;
  word: string;
  translation: string;
  example?: string;
  status?: VocabStatus | string;
  next_review?: string | null;
};

export type VocabListResponse = {
  words: VocabWord[];
  total: number;
  due: number;
};

export type VocabAddPayload = {
  word: string;
  translation: string;
  example?: string;
};

export type VocabCheckPayload = {
  word_id: number;
  translation: string;
  sentence: string;
};

export type VocabCheckResponse = {
  translation_ok: boolean;
  sentence_ok: boolean;
  score: number;
  feedback?: string;
  improved?: string;
};

/** Словарь пользователя: слова из уроков и добавленные вручную. */
export function getVocab(limit = 50, offset = 0): Promise<VocabListResponse> {
  return apiFetch<VocabListResponse>(`/api/vocab?limit=${limit}&offset=${offset}`);
}

/** Добавляет слово. Идемпотентно: повторный вызов не создаёт дубль. */
export function addVocabWord(payload: VocabAddPayload): Promise<{ word: VocabWord }> {
  return apiFetch<{ word: VocabWord }>('/api/vocab', {
    method: 'POST',
    body: payload satisfies VocabAddPayload,
  });
}

/** Проверка перевода и своего предложения (перевод + мягкая обратная связь). */
export function checkVocabWord(payload: VocabCheckPayload): Promise<VocabCheckResponse> {
  return apiFetch<VocabCheckResponse>('/api/vocab/check', {
    method: 'POST',
    body: payload satisfies VocabCheckPayload,
  });
}

export function deleteVocabWord(id: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/vocab/${id}`, { method: 'DELETE' });
}