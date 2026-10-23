'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  ApiError,
  apiBlob,
  apiFetch,
  errorMessage,
  finishTutorSession,
  serverSttAvailable,
  streamTutorTurn,
  startTutorSession,
  transcribeAudio,
} from '@/lib/api';
import type {
  TutorCorrection,
  TutorFinishResponse,
  TutorMode,
  TutorSummary,
} from '@/lib/api';
import { sampleCharacters } from '@/lib/characters';
import type { Character, Locale } from '@/lib/characters';
import { useRecorder } from '@/lib/recorder';
import { useSession } from '@/lib/session';
import { createSpeechRecognizer, isSpeechSupported } from '@/lib/speech';
import AddToVocabButton, { VocabFlyTarget } from '@/app/vocab/AddToVocabButton';

/**
 * Диалог с наставником-аватаром — общий экран для «Урока 0» (`mode="intro"`)
 * и обычного урока (`mode="lesson"`).
 *
 * Сессия живёт на бэкенде (`/api/tutor/*`), гость привязан к подписанной
 * HttpOnly-cookie `adapteng_tutor`, поэтому для знакомства авторизация не
 * нужна — залогиненному пользователю сессия привязывается к аккаунту
 * автоматически. Урок в режиме `lesson` стартует с повтора прошлой ошибки
 * и объявления темы; `topic` необязателен — без него бэкенд выбирает тему.
 *
 * Голос: реплики наставника озвучиваются через `/api/chat/tts`; если
 * эндпоинт недоступен (гость / нет ключа TTS) — мягкий откат на
 * `window.speechSynthesis`. Автоплей, заблокированный браузером,
 * разблокируется первым кликом/тапом по экрану (кнопка «Начать»).
 */

export type { TutorMode };

type Props = {
  mode: TutorMode;
  /** Тема урока (только для `mode="lesson"`). Без неё бэкенд выберет сам. */
  topic?: string;
};

type TutorCharacter = {
  id: string;
  name: string;
  emoji: string;
  avatar?: string;
  palette: string[];
};

type Bubble = {
  id: number;
  role: 'tutor' | 'user';
  text: string;
  correction?: TutorCorrection | null;
  interests?: string[];
  failed?: boolean;
  /** Реплика ещё стримится (показываем курсор). */
  streaming?: boolean;
};

type AvatarState = 'idle' | 'thinking' | 'speaking';

type Banner = {
  text: string;
  action?: 'retry-send' | 'restart' | 'finish';
  retryText?: string;
  retryId?: number;
};

const FALLBACK_PALETTE = ['#3b82f6', '#60a5fa'];

/** Тишина для разблокировки автоплея первым жестом пользователя. */
const SILENT_WAV =
  'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=';

const MUTE_STORAGE_KEY = 'adapteng_lesson0_muted';

function toTutorCharacter(item: Character): TutorCharacter {
  return {
    id: item.id,
    name: item.name,
    emoji: item.emoji,
    avatar: item.avatar,
    palette:
      Array.isArray(item.palette) && item.palette.length >= 2
        ? item.palette
        : FALLBACK_PALETTE,
  };
}

function MentorAvatar({
  character,
  state = 'idle',
  animated = false,
  size = 'md',
}: {
  character: TutorCharacter;
  state?: AvatarState;
  animated?: boolean;
  size?: 'sm' | 'md' | 'lg';
}) {
  const palette =
    Array.isArray(character.palette) && character.palette.length >= 2
      ? character.palette
      : FALLBACK_PALETTE;
  const box =
    size === 'sm'
      ? 'h-9 w-9 rounded-xl text-lg'
      : size === 'lg'
        ? 'h-[72px] w-[72px] rounded-[22px] text-3xl sm:h-24 sm:w-24 sm:rounded-[26px] sm:text-4xl'
        : 'h-12 w-12 rounded-2xl text-xl';

  const animation = animated ? `tutor-avatar tutor-avatar--${state}` : '';

  return (
    <span
      className={`relative flex shrink-0 items-center justify-center ${box} ${animation}`}
      style={{
        backgroundImage: `linear-gradient(140deg, ${palette[0]}, ${palette[1]})`,
        boxShadow: animated
          ? `0 18px 45px -20px ${palette[0]}, 0 0 0 1px rgba(255,255,255,0.08) inset`
          : undefined,
      }}
      aria-hidden={animated ? undefined : true}
    >
      {character.avatar ? (
        <img
          src={character.avatar}
          alt={character.name}
          className={`${size === 'sm' ? 'h-9 w-9' : size === 'lg' ? 'h-full w-full' : 'h-12 w-12'} rounded-[inherit] object-cover`}
        />
      ) : (
        <span className="tutor-avatar__face select-none leading-none">{character.emoji}</span>
      )}
    </span>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
      <path
        d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M5 11a7 7 0 0 0 14 0" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 18v3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
      <path d="M5 12h13" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function TutorSession({ mode, topic }: Props) {
  const locale = useLocale() as Locale;
  const t = useTranslations('lesson0');
  const recorder = useRecorder();
  const { user, loading: sessionLoading } = useSession();
  const isLesson = mode === 'lesson';

  const [characters, setCharacters] = useState<TutorCharacter[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [startError, setStartError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [turnIndex, setTurnIndex] = useState(0);
  const [maxTurns, setMaxTurns] = useState(7);
  const [shouldFinish, setShouldFinish] = useState(false);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [result, setResult] = useState<TutorFinishResponse | null>(null);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [voiceUnavailable, setVoiceUnavailable] = useState(false);
  const [avatarState, setAvatarState] = useState<AvatarState>('idle');
  /** Тема текущей сессии; после «Следующего урока» — null (новая тема). */
  const [activeTopic, setActiveTopic] = useState<string | null>(
    isLesson ? topic?.trim() || null : null,
  );

  const idRef = useRef(0);
  const startedRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const characterIdRef = useRef('default');
  const mutedRef = useRef(false);
  const speechTokenRef = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastReplyRef = useRef('');
  const replayLockRef = useRef(0);
  const primedRef = useRef(false);
  const sendingRef = useRef(false);
  const finishingRef = useRef(false);
  const guestRef = useRef(false);
  const topicRef = useRef<string | undefined>(isLesson ? topic?.trim() || undefined : undefined);

  const character: TutorCharacter =
    characters[0] ?? {
      id: 'default',
      name: t('mentor'),
      emoji: '📚',
      palette: FALLBACK_PALETTE,
    };

  characterIdRef.current = character.id;
  guestRef.current = !sessionLoading && !user;

  function nextId(): number {
    idRef.current += 1;
    return idRef.current;
  }

  // ---------- звук ----------

  const stopAudio = useCallback(() => {
    speechTokenRef.current += 1;
    const audio = audioRef.current;
    if (audio) {
      try {
        audio.pause();
        audio.src = '';
      } catch {
        // уже остановлено
      }
      audioRef.current = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // speechSynthesis может быть недоступен
      }
    }
    setAvatarState('idle');
  }, []);

  const speakInBrowser = useCallback((text: string, token: number): boolean => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      return false;
    }
    try {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'en-US';
      utterance.rate = 0.98;
      utterance.onend = () => {
        if (speechTokenRef.current === token) {
          setAvatarState('idle');
        }
      };
      utterance.onerror = (event) => {
        // Браузер может запретить синтез до первого жеста — тогда покажем «Начать».
        if (event.error === 'not-allowed') {
          setAudioBlocked(true);
        }
        if (speechTokenRef.current === token) {
          setAvatarState('idle');
        }
      };
      window.speechSynthesis.speak(utterance);
      setAvatarState('speaking');
      return true;
    } catch {
      return false;
    }
  }, []);

  const speak = useCallback(
    async (text: string) => {
      const clean = text.trim();
      if (!clean) {
        return;
      }
      lastReplyRef.current = clean;
      stopAudio();
      if (mutedRef.current) {
        return;
      }
      const token = speechTokenRef.current;
      setAvatarState('speaking');

      // /api/chat/tts требует авторизации: гостю читаем голосом браузера.
      if (guestRef.current) {
        if (!speakInBrowser(clean, token)) {
          setVoiceUnavailable(true);
          setAvatarState('idle');
        }
        return;
      }

      try {
        const blob = await apiBlob('/api/chat/tts', {
          method: 'POST',
          body: { text: clean, character_id: characterIdRef.current },
        });
        if (token !== speechTokenRef.current || mutedRef.current) {
          return;
        }
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = () => {
          URL.revokeObjectURL(url);
          if (audioRef.current === audio) {
            audioRef.current = null;
          }
          if (speechTokenRef.current === token) {
            setAvatarState('idle');
          }
        };
        audio.onerror = () => {
          URL.revokeObjectURL(url);
          if (audioRef.current === audio) {
            audioRef.current = null;
          }
          if (speechTokenRef.current === token) {
            setAvatarState('idle');
          }
        };
        try {
          await audio.play();
          setAudioBlocked(false);
        } catch {
          URL.revokeObjectURL(url);
          audioRef.current = null;
          if (token !== speechTokenRef.current || mutedRef.current) {
            return;
          }
          // Браузер заблокировал автоплей — разблокируем первым жестом.
          setAudioBlocked(true);
          setAvatarState('idle');
          if (!speakInBrowser(clean, token)) {
            setVoiceUnavailable(true);
          }
        }
      } catch {
        if (token !== speechTokenRef.current || mutedRef.current) {
          return;
        }
        // Гость или TTS не настроен — читаем голосом браузера.
        if (!speakInBrowser(clean, token)) {
          setVoiceUnavailable(true);
          setAvatarState('idle');
        }
      }
    },
    [speakInBrowser, stopAudio],
  );

  function replayLast() {
    const now = Date.now();
    if (now - replayLockRef.current < 900) {
      return;
    }
    replayLockRef.current = now;
    if (lastReplyRef.current) {
      void speak(lastReplyRef.current);
    }
  }

  function unlockAudio() {
    if (!primedRef.current) {
      primedRef.current = true;
      // Немного тишины на первом жесте снимает запрет автоплея в браузере.
      try {
        const primer = new Audio(SILENT_WAV);
        primer.volume = 0;
        void primer
          .play()
          .then(() => primer.pause())
          .catch(() => {});
      } catch {
        // браузер всё равно попробует проиграть позже
      }
    }
    if (audioBlocked) {
      setAudioBlocked(false);
      replayLast();
    }
  }

  function toggleMute() {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    if (next) {
      stopAudio();
    }
    try {
      window.localStorage.setItem(MUTE_STORAGE_KEY, next ? '1' : '0');
    } catch {
      // приватный режим — не критично
    }
  }

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(MUTE_STORAGE_KEY);
      if (stored === '1') {
        mutedRef.current = true;
        setMuted(true);
      }
    } catch {
      // localStorage недоступен
    }
  }, []);

  useEffect(() => {
    return () => {
      speechTokenRef.current += 1;
      if (audioRef.current) {
        try {
          audioRef.current.pause();
        } catch {
          // уже остановлено
        }
      }
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          // нет синтеза речи
        }
      }
    };
  }, []);

  // ---------- персонажи ----------

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const raw = await apiFetch<Character[]>(`/api/characters?lang=${locale}`);
        if (!active) {
          return;
        }
        if (Array.isArray(raw) && raw.length > 0) {
          setCharacters(raw.map(toTutorCharacter));
          return;
        }
      } catch {
        // ниже — локальный фолбэк
      }
      if (active) {
        const fallback = sampleCharacters(locale).map(toTutorCharacter);
        setCharacters(fallback);
      }
    })();
    return () => {
      active = false;
    };
  }, [locale]);

  // ---------- ошибки ----------

  function describeError(error: unknown): string {
    if (error instanceof ApiError) {
      if (error.status === 429) {
        return t('error.quota');
      }
      if (error.status === 404) {
        return t('error.session');
      }
      if (error.status === 409) {
        return t('error.finished');
      }
      if (error.status === 502 || error.status === 503 || error.status === 504) {
        return t('error.llm');
      }
    }
    return errorMessage(error, t('error.generic'));
  }

  // ---------- сессия ----------

  async function begin() {
    setStatus('loading');
    setStartError(null);
    setBanner(null);
    setResult(null);
    setBubbles([]);
    setSessionId(null);
    setTurnIndex(0);
    setShouldFinish(false);
    sendingRef.current = false;
    finishingRef.current = false;
    try {
      const data = await startTutorSession(mode, isLesson ? topicRef.current : undefined);
      setSessionId(data.session_id);
      setTurnIndex(data.turn_index);
      setMaxTurns(data.max_turns);
      setShouldFinish(Boolean(data.turn.should_finish));
      setBubbles([
        {
          id: nextId(),
          role: 'tutor',
          text: data.turn.reply,
          correction: data.turn.correction ?? null,
          interests: data.turn.interests ?? [],
        },
      ]);
      setStatus('ready');
      void speak(data.turn.reply);
    } catch (error) {
      setStartError(describeError(error));
      setStatus('error');
    }
  }

  useEffect(() => {
    if (startedRef.current) {
      return;
    }
    startedRef.current = true;
    void begin();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [bubbles, sending]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 3600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  /** «Следующий урок»: новая сессия в режиме lesson без темы — её выберет бэкенд. */
  function startNextLesson() {
    if (!isLesson) {
      return;
    }
    stopAudio();
    topicRef.current = undefined;
    setActiveTopic(null);
    void begin();
  }

  // ---------- ходы ----------

  async function submitText(raw: string) {
    const text = raw.trim();
    if (!text || !sessionId || sendingRef.current || finishingRef.current) {
      return;
    }
    sendingRef.current = true;
    const uid = nextId();
    setInput('');
    setBanner(null);
    setToast(null);
    setBubbles((prev) => [...prev, { id: uid, role: 'user', text }]);
    setSending(true);
    setAvatarState('thinking');

    try {
      // Стримим реплику: пузырь появляется сразу и наполняется по мере
      // генерации — наставник «печатает», а не молчит 5–8 секунд.
      const bubbleId = nextId();
      let streamed = '';
      setBubbles((prev) => [
        ...prev,
        { id: bubbleId, role: 'tutor', text: '', correction: null, interests: [], streaming: true },
      ]);
      const data = await streamTutorTurn(sessionId, text, (chunk) => {
        streamed += chunk;
        setBubbles((prev) =>
          prev.map((item) => (item.id === bubbleId ? { ...item, text: streamed } : item)),
        );
      });
      setTurnIndex(data.turn_index);
      setMaxTurns(data.max_turns);
      setShouldFinish(Boolean(data.should_finish || data.turn.should_finish));
      setBubbles((prev) =>
        prev.map((item) =>
          item.id === bubbleId
            ? {
                ...item,
                text: data.turn.reply || item.text,
                correction: data.turn.correction ?? null,
                interests: data.turn.interests ?? [],
                streaming: false,
              }
            : item,
        ),
      );
      sendingRef.current = false;
      setSending(false);
      void speak(data.turn.reply || streamed);
    } catch (error) {
      sendingRef.current = false;
      setSending(false);
      setAvatarState('idle');
      const message = describeError(error);
      if (error instanceof ApiError && error.status === 409) {
        setBubbles((prev) => prev.filter((item) => item.id !== uid));
        setShouldFinish(true);
        setBanner({ text: message, action: 'finish' });
        return;
      }
      setBubbles((prev) =>
        prev.map((item) => (item.id === uid ? { ...item, failed: true } : item)),
      );
      if (error instanceof ApiError && error.status === 404) {
        setBanner({ text: message, action: 'restart' });
        return;
      }
      setBanner({ text: message, action: 'retry-send', retryText: text, retryId: uid });
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitText(input);
  }

  function handleBannerAction() {
    if (!banner) {
      return;
    }
    const action = banner.action;
    const retryText = banner.retryText;
    const retryId = banner.retryId;
    setBanner(null);
    if (action === 'restart') {
      void begin();
      return;
    }
    if (action === 'finish') {
      void submitFinish();
      return;
    }
    if (action === 'retry-send' && retryText) {
      if (retryId !== undefined) {
        setBubbles((prev) => prev.filter((item) => item.id !== retryId));
      }
      void submitText(retryText);
    }
  }

  // ---------- итог ----------

  async function submitFinish() {
    if (!sessionId || finishingRef.current || sendingRef.current) {
      return;
    }
    finishingRef.current = true;
    stopAudio();
    setFinishing(true);
    setBanner(null);
    try {
      const data = await finishTutorSession(sessionId);
      setResult(data);
      setStatus('ready');
    } catch (error) {
      const message = describeError(error);
      if (error instanceof ApiError && error.status === 404) {
        setBanner({ text: message, action: 'restart' });
      } else {
        setBanner({ text: message, action: 'finish' });
      }
    } finally {
      finishingRef.current = false;
      setFinishing(false);
    }
  }

  // ---------- микрофон ----------

  function listenInBrowser() {
    if (!isSpeechSupported()) {
      setBanner({ text: t('voice.notSupported') });
      return;
    }
    const recognition = createSpeechRecognizer('en-US', {
      onFinal: (text) => {
        setInput((prev) => (prev ? `${prev} ${text}` : text));
        setToast(t('voice.captured'));
      },
      onError: (message) => setBanner({ text: message }),
    });
    if (!recognition) {
      setBanner({ text: t('voice.unavailable') });
      return;
    }
    try {
      recognition.start();
      setToast(t('voice.listening'));
    } catch {
      setBanner({ text: t('voice.unavailable') });
    }
  }

  async function handleVoice() {
    if (recorder.recording) {
      const blob = await recorder.stop();
      if (!blob) {
        setBanner({ text: t('voice.error') });
        return;
      }
      setBanner(null);
      try {
        const res = await transcribeAudio(blob, { mode: 'free' });
        const transcript = (res.transcript ?? '').trim();
        if (!transcript) {
          setBanner({ text: t('voice.error') });
          return;
        }
        setInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
        setToast(t('voice.captured'));
      } catch (error) {
        if (error instanceof ApiError && (error.status === 503 || error.status === 502)) {
          listenInBrowser();
          return;
        }
        setBanner({ text: errorMessage(error, t('voice.error')) });
      }
      return;
    }
    setBanner(null);
    if (!(await serverSttAvailable())) {
      listenInBrowser();
      return;
    }
    const started = await recorder.start();
    if (!started) {
      setBanner({ text: t('voice.error') });
    }
  }

  // ---------- отрисовка ----------

  const stateLabel =
    avatarState === 'thinking'
      ? t('state.thinking')
      : avatarState === 'speaking'
        ? t('state.speaking')
        : t('state.idle');

  if (result) {
    return (
      <FinishScreen
        mode={mode}
        character={character}
        result={result}
        onNextLesson={startNextLesson}
      />
    );
  }

  if (status === 'loading') {
    return (
      <Shell>
        <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 pb-24 text-center">
          <MentorAvatar character={character} state="thinking" animated size="lg" />
          <p role="status" className="text-sm font-medium text-blue-200/80">
            {isLesson ? t('lessonLoading') : t('loading')}
          </p>
          <div className="h-1 w-40 overflow-hidden rounded-full bg-white/10">
            <span className="block h-full w-1/2 animate-pulse motion-reduce:animate-none rounded-full bg-gradient-to-r from-blue-500 to-cyan-400" />
          </div>
        </div>
      </Shell>
    );
  }

  if (status === 'error') {
    return (
      <Shell>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-5 px-4 pb-24 text-center">
          <MentorAvatar character={character} state="idle" animated size="lg" />
          <p role="alert" className="rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">
            {startError ?? t('error.generic')}
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <button type="button" onClick={() => void begin()} className={primaryButton}>
              {t('error.retry')}
            </button>
            <Link href={isLesson ? '/menu' : '/welcome'} className={secondaryButton}>
              {t('back')}
            </Link>
          </div>
        </div>
      </Shell>
    );
  }

  const reachedLimit = turnIndex >= maxTurns;
  const canFinish = shouldFinish || reachedLimit;
  const voiceBusy = recorder.recording || recorder.busy;

  return (
    <Shell onPointerDown={unlockAudio}>
      <header className="border-b border-white/10 px-4 pb-3 pt-4 sm:px-6">
        <div className="flex items-center gap-3 sm:gap-4">
          <MentorAvatar character={character} state={avatarState} animated size="lg" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-300/70">
              {isLesson ? t('lessonBadge') : t('badge')}
            </p>
            <h1 className="truncate text-base font-bold text-white sm:text-lg">
              {character.name}
            </h1>
            {isLesson ? (
              <p className="mt-1 max-w-full truncate">
                <span className="inline-flex max-w-full items-center gap-1 rounded-full border border-blue-400/30 bg-blue-500/10 px-2.5 py-0.5 text-[11px] font-medium text-blue-100">
                  <span aria-hidden="true">🎯</span>
                  <span className="truncate">{activeTopic ?? t('newTopic')}</span>
                </span>
              </p>
            ) : null}
            <p className="mt-0.5 flex items-center gap-1.5 text-xs text-blue-200/70">
              <span
                aria-hidden="true"
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  avatarState === 'speaking'
                    ? 'bg-cyan-300'
                    : avatarState === 'thinking'
                      ? 'bg-amber-300'
                      : 'bg-emerald-400'
                }`}
              />
              {stateLabel}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <VocabFlyTarget />
            <button
              type="button"
              onClick={toggleMute}
              aria-pressed={muted}
              aria-label={muted ? t('unmute') : t('mute')}
              title={muted ? t('unmute') : t('mute')}
              className={iconButton}
            >
              <span aria-hidden="true">{muted ? '🔇' : '🔊'}</span>
            </button>
            <button
              type="button"
              onClick={replayLast}
              disabled={!lastReplyRef.current}
              aria-label={t('repeat')}
              title={t('repeat')}
              className={iconButton}
            >
              <span aria-hidden="true">↻</span>
            </button>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs font-medium text-blue-200/70">
            {t('progress', { current: Math.min(turnIndex, maxTurns), total: maxTurns })}
          </p>
          <button
            type="button"
            onClick={() => void submitFinish()}
            disabled={finishing || sending}
            className="inline-flex min-h-[44px] items-center rounded-lg px-2.5 text-xs font-semibold text-blue-200 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:opacity-50"
          >
            {finishing ? t('finishing') : t('finish')}
          </button>
        </div>

        <div
          role="progressbar"
          aria-label={t('progressLabel')}
          aria-valuemin={0}
          aria-valuemax={maxTurns}
          aria-valuenow={Math.min(turnIndex, maxTurns)}
          className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10"
        >
          <span
            className="block h-full rounded-full bg-gradient-to-r from-blue-500 via-blue-400 to-cyan-300 transition-[width] duration-500"
            style={{ width: `${Math.min(100, Math.round((turnIndex / Math.max(1, maxTurns)) * 100))}%` }}
          />
        </div>
      </header>

      {audioBlocked && !muted ? (
        <div className="mx-4 mt-3 flex flex-wrap items-center gap-3 rounded-2xl border border-blue-400/30 bg-blue-500/10 px-4 py-3 sm:mx-6">
          <span aria-hidden="true" className="text-lg">
            🔊
          </span>
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-blue-100/80">
            {t('startHint')}
          </p>
          <button
            type="button"
            onClick={() => {
              unlockAudio();
              replayLast();
            }}
            className="inline-flex min-h-[44px] items-center justify-center rounded-xl bg-blue-500 px-4 text-sm font-semibold text-white transition hover:bg-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
          >
            {t('start')}
          </button>
        </div>
      ) : null}

      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label={t('logLabel')}
        className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6"
      >
        {bubbles.map((bubble) =>
          bubble.role === 'user' ? (
            <div key={bubble.id} className="flex flex-col items-end gap-1">
              <div
                className={`max-w-[85%] whitespace-pre-wrap break-words rounded-3xl rounded-br-lg px-4 py-3 text-sm leading-relaxed ${
                  bubble.failed
                    ? 'bg-red-500/20 text-red-50 ring-1 ring-red-400/40'
                    : 'bg-blue-600 text-white shadow-lg shadow-blue-950/40'
                }`}
              >
                {bubble.text}
              </div>
              {bubble.failed ? (
                <p className="text-[11px] text-red-300/90">{t('failed')}</p>
              ) : null}
            </div>
          ) : (
            <div key={bubble.id} className="flex items-start gap-2.5">
              <MentorAvatar character={character} size="sm" />
              <div className="min-w-0 max-w-[85%] space-y-2">
                <div className="whitespace-pre-wrap break-words rounded-3xl rounded-bl-lg border border-white/10 bg-white/[0.06] px-4 py-3 text-sm leading-relaxed text-blue-50">
                  {bubble.text}
                  {bubble.streaming ? (
                    <span
                      aria-hidden
                      className="ml-1 inline-block h-4 w-[2px] animate-pulse bg-sky-300 align-middle"
                    />
                  ) : null}
                  {bubble.streaming && !bubble.text ? (
                    <span className="sr-only">{t('state.thinking')}</span>
                  ) : null}
                </div>
                {bubble.correction ? (
                  <div className="rounded-2xl border border-amber-300/25 bg-amber-400/10 px-3.5 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-200/80">
                      {t('correctionTitle')}
                    </p>
                    {bubble.correction.corrected_text ? (
                      <p className="mt-1 text-sm leading-relaxed text-amber-50">
                        {bubble.correction.corrected_text}
                      </p>
                    ) : null}
                    {(bubble.correction.issues ?? []).length > 0 ? (
                      <ul className="mt-2 space-y-1 text-xs leading-relaxed text-amber-100/80">
                        {(bubble.correction.issues ?? []).map((issue, index) => (
                          <li key={index}>
                            {issue.problem}
                            {issue.suggestion ? ` — ${issue.suggestion}` : ''}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {user ? (
                      <div className="mt-2.5 flex flex-wrap items-center gap-2">
                        <AddToVocabButton manual />
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {user && !bubble.correction ? (
                  <div className="pt-0.5">
                    <AddToVocabButton manual />
                  </div>
                ) : null}
                {bubble.interests && bubble.interests.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] font-medium text-blue-200/60">
                      {t('remembered')}
                    </span>
                    {bubble.interests.map((interest) => (
                      <span
                        key={interest}
                        className="rounded-full border border-blue-400/30 bg-blue-500/10 px-2.5 py-0.5 text-[11px] font-medium text-blue-100"
                      >
                        {interest}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ),
        )}

        {sending ? (
          <div className="flex items-start gap-2.5">
            <MentorAvatar character={character} size="sm" />
            <div className="flex items-center gap-1 rounded-2xl rounded-bl-lg border border-white/10 bg-white/[0.06] px-4 py-3">
              <span className="sr-only">{t('state.thinking')}</span>
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-300/70 motion-reduce:animate-none [animation-delay:-0.3s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-300/70 motion-reduce:animate-none [animation-delay:-0.15s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-300/70 motion-reduce:animate-none" />
            </div>
          </div>
        ) : null}

        <div ref={bottomRef} />
      </div>

      <div className="border-t border-white/10 bg-[#0b1425]/80 px-4 pb-4 pt-3 backdrop-blur sm:px-6">
        {canFinish ? (
          <div className="mb-3 rounded-2xl border border-blue-400/30 bg-blue-500/10 px-4 py-3">
            <p className="text-sm font-semibold text-blue-50">
              {isLesson ? t('lessonFinishTitle') : t('finishTitle')}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-blue-100/70">{t('finishHint')}</p>
            <button
              type="button"
              onClick={() => void submitFinish()}
              disabled={finishing}
              className="mt-3 inline-flex min-h-[44px] w-full items-center justify-center rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-5 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:from-blue-500 hover:to-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:opacity-60 sm:w-auto"
            >
              {finishing ? t('finishing') : t('finish')}
            </button>
          </div>
        ) : null}

        {banner ? (
          <div
            role="alert"
            className="mb-3 flex flex-col gap-2 rounded-2xl border border-amber-300/30 bg-amber-400/10 px-4 py-3 sm:flex-row sm:items-center"
          >
            <p className="min-w-0 flex-1 text-sm leading-relaxed text-amber-100">
              {banner.text}
            </p>
            {banner.action ? (
              <button
                type="button"
                onClick={handleBannerAction}
                className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-xl border border-amber-300/40 px-4 text-sm font-semibold text-amber-50 transition hover:bg-amber-300/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
              >
                {banner.action === 'retry-send'
                  ? t('retry')
                  : banner.action === 'restart'
                    ? t('restart')
                    : t('finish')}
              </button>
            ) : null}
          </div>
        ) : null}

        {voiceUnavailable && !muted ? (
          <p className="mb-2 text-[11px] text-blue-200/50">{t('voiceUnavailable')}</p>
        ) : null}

        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={reachedLimit ? t('limitReached') : t('placeholder')}
            disabled={reachedLimit || finishing}
            aria-label={t('inputLabel')}
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.06] px-4 py-3 text-sm text-blue-50 outline-none transition placeholder:text-blue-200/40 focus:border-blue-400/60 focus:ring-2 focus:ring-blue-500/30 disabled:opacity-60"
          />
          <button
            type="button"
            onClick={() => void handleVoice()}
            disabled={voiceBusy || sending || reachedLimit || finishing}
            aria-label={t('mic')}
            title={t('mic')}
            aria-pressed={recorder.recording}
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:cursor-not-allowed disabled:opacity-50 ${
              recorder.recording
                ? 'border-red-400/50 bg-red-500/20 text-red-200'
                : 'border-white/10 bg-white/[0.06] text-blue-200 hover:bg-white/10'
            }`}
          >
            <MicIcon />
          </button>
          <button
            type="submit"
            disabled={sending || finishing || reachedLimit || input.trim().length === 0}
            aria-label={t('send')}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-500 text-white transition hover:bg-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-blue-200/40"
          >
            <SendIcon />
          </button>
        </form>
      </div>

      {toast ? (
        <div
          role="status"
          className="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900/95 px-4 py-3 text-sm text-white shadow-xl ring-1 ring-white/10"
        >
          {toast}
        </div>
      ) : null}
    </Shell>
  );
}

const primaryButton =
  'inline-flex min-h-[48px] items-center justify-center rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-6 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:from-blue-500 hover:to-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]';

const secondaryButton =
  'inline-flex min-h-[48px] items-center justify-center rounded-xl border border-white/15 px-6 text-sm font-semibold text-blue-100 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]';

const iconButton =
  'flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-base text-blue-100 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:cursor-not-allowed disabled:opacity-40';

function Shell({
  children,
  onPointerDown,
}: {
  children: ReactNode;
  onPointerDown?: () => void;
}) {
  return (
    <main
      onPointerDown={onPointerDown}
      className="relative isolate min-h-[calc(100dvh-4rem)] overflow-hidden bg-[linear-gradient(160deg,#0b1220_0%,#111c33_100%)] text-white"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_20%_-10%,rgba(37,99,235,0.28),transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-32 right-[-15%] h-[380px] w-[380px] rounded-full bg-blue-500/10 blur-3xl"
      />
      <div className="relative mx-auto flex h-[calc(100dvh-4rem)] w-full max-w-3xl flex-col">
        {children}
      </div>
    </main>
  );
}

function SummarySection({
  title,
  items,
}: {
  title: string;
  items: string[];
}) {
  if (!items || items.length === 0) {
    return null;
  }
  return (
    <section className="mt-5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-slate-700">
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className="flex gap-2">
            <span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FinishScreen({
  mode,
  character,
  result,
  onNextLesson,
}: {
  mode: TutorMode;
  character: TutorCharacter;
  result: TutorFinishResponse;
  onNextLesson: () => void;
}) {
  const t = useTranslations('lesson0');
  const summary: TutorSummary = result.summary;
  const isLesson = mode === 'lesson';

  return (
    <main className="relative isolate min-h-[calc(100dvh-4rem)] overflow-hidden bg-[linear-gradient(160deg,#0b1220_0%,#111c33_100%)] px-4 py-8 text-white sm:py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_50%_-12%,rgba(37,99,235,0.32),transparent_70%)]"
      />
      <div className="relative mx-auto w-full max-w-2xl">
        <header className="flex flex-col items-center text-center">
          <MentorAvatar character={character} state="idle" animated size="lg" />
          <span className="mt-4 inline-flex items-center rounded-full border border-blue-400/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold tracking-wide text-blue-200">
            {isLesson ? t('result.lessonBadge') : t('result.badge')}
          </span>
          <h1 className="mt-4 text-2xl font-bold leading-tight text-white sm:text-3xl">
            {isLesson ? t('result.lessonTitle') : t('result.title')}
          </h1>
          <p className="mt-2 max-w-lg text-sm leading-relaxed text-blue-100/70">
            {t('result.subtitle')}
          </p>
        </header>

        <div className="mt-7 rounded-[28px] bg-white p-5 text-slate-900 shadow-[0_40px_90px_-30px_rgba(37,99,235,0.55)] ring-1 ring-white/20 sm:p-7">
          <div className="flex items-center gap-4 rounded-2xl bg-blue-50 p-4">
            <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-blue-500 text-xl font-bold text-white">
              {summary.level}
            </span>
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                {t('result.level')}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">
                {t('result.levelHint')}
              </p>
            </div>
          </div>

          <p
            className={`mt-3 rounded-2xl px-4 py-3 text-sm font-medium ${
              summary.matches_self_level
                ? 'bg-emerald-50 text-emerald-800'
                : 'bg-amber-50 text-amber-800'
            }`}
          >
            {summary.matches_self_level ? t('result.matches') : t('result.differs')}
          </p>

          {summary.interests.length > 0 ? (
            <section className="mt-5">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {t('result.interests')}
              </h3>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {summary.interests.map((interest) => (
                  <span
                    key={interest}
                    className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-800"
                  >
                    {interest}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          <SummarySection title={t('result.strengths')} items={summary.strengths} />
          <SummarySection title={t('result.weaknesses')} items={summary.weaknesses} />

          {summary.recommendation ? (
            <section className="mt-5 rounded-2xl border border-blue-100 bg-blue-50/70 p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                {t('result.recommendation')}
              </h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-700">
                {summary.recommendation}
              </p>
            </section>
          ) : null}

          {summary.praise ? (
            <p className="mt-5 border-l-2 border-blue-300 pl-3 text-sm italic leading-relaxed text-slate-600">
              {summary.praise}
            </p>
          ) : null}

          {result.registered ? (
            <div className="mt-5 flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-600 px-3.5 py-1.5 text-xs font-semibold text-white">
                ⭐ {t('result.xp', { xp: result.xp })}
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-3.5 py-1.5 text-xs font-semibold text-orange-700">
                🔥 {t('result.streak', { days: result.streak_days })}
              </span>
            </div>
          ) : (
            <p className="mt-5 rounded-2xl border border-blue-100 bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-600">
              {t('result.guestNote')}
            </p>
          )}

          {isLesson ? (
            <div className="mt-6 flex flex-col gap-2.5 sm:flex-row">
              <button
                type="button"
                onClick={onNextLesson}
                className="inline-flex min-h-[48px] flex-1 items-center justify-center rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:from-blue-500 hover:to-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2"
              >
                {t('nextLesson')}
              </button>
              <Link
                href="/menu"
                className="inline-flex min-h-[48px] flex-1 items-center justify-center rounded-xl border border-slate-200 bg-white px-5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2"
              >
                {t('result.toMenu')}
              </Link>
            </div>
          ) : (
            <div className="mt-6 flex flex-col gap-2.5 sm:flex-row-reverse">
              {result.registered ? null : (
                <Link
                  href="/login"
                  className="inline-flex min-h-[48px] flex-1 items-center justify-center rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:from-blue-500 hover:to-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2"
                >
                  {t('result.save')}
                </Link>
              )}
              <Link
                href="/menu"
                className={`inline-flex min-h-[48px] flex-1 items-center justify-center rounded-xl px-5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 ${
                  result.registered
                    ? 'bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-lg shadow-blue-500/25 hover:from-blue-500 hover:to-blue-400'
                    : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                {t('result.continue')}
              </Link>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
