'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useSession } from '@/lib/session';
import { sampleCharacters } from '@/lib/characters';
import type { Character, Locale } from '@/lib/characters';
import {
  ApiError,
  apiBlob,
  apiFetch,
  errorMessage,
  serverSttAvailable,
  transcribeAudio,
} from '@/lib/api';
import { useRecorder } from '@/lib/recorder';
import { createSpeechRecognizer, isSpeechSupported } from '@/lib/speech';

type ChatCharacter = {
  id: string;
  name: string;
  emoji: string;
  avatar?: string;
  palette: string[];
  tagline?: string;
};

type Message = {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  correctedText?: string;
  isCorrect?: boolean;
  issues?: { category?: string; note?: string }[];
};

type MeResponse = {
  user?: {
    id?: number;
    character?: string;
    level?: string | null;
    quota_left?: number | null;
  };
  character?: {
    id: string;
    name: string;
    emoji?: string;
    tagline?: string;
    palette?: string[];
    avatar?: string;
  };
};

type ChatResponse = {
  reply?: string;
  next_question?: string;
  corrected_text?: string;
  is_correct?: boolean;
  issues?: { category?: string; note?: string }[];
  character?: { id: string; name: string; emoji?: string };
};

type Status = 'loading' | 'ready' | 'error' | 'needLogin';

const FALLBACK_PALETTE = ['#3b82f6', '#60a5fa'];


function toChatCharacter(item: Character): ChatCharacter {
  return {
    id: item.id,
    name: item.name,
    emoji: item.emoji,
    avatar: item.avatar,
    palette:
      Array.isArray(item.palette) && item.palette.length >= 2
        ? item.palette
        : FALLBACK_PALETTE,
    tagline: item.tagline,
  };
}

function Avatar({
  character,
  size = 'md',
}: {
  character: ChatCharacter;
  size?: 'sm' | 'md';
}) {
  const palette =
    Array.isArray(character.palette) && character.palette.length >= 2
      ? character.palette
      : FALLBACK_PALETTE;
  const box = size === 'sm' ? 'h-7 w-7 text-sm' : 'h-11 w-11 text-xl';

  if (character.avatar) {
    return (
      <img
        src={character.avatar}
        alt={character.name}
        className={`${box} shrink-0 rounded-2xl object-cover`}
      />
    );
  }

  return (
    <span
      className={`flex ${box} shrink-0 items-center justify-center rounded-2xl text-white`}
      style={{ backgroundImage: `linear-gradient(135deg, ${palette[0]}, ${palette[1]})` }}
    >
      {character.emoji}
    </span>
  );
}

function BackIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
      <path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
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

export default function ChatPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('chat');

  const [status, setStatus] = useState<Status>('loading');
  const [character, setCharacter] = useState<ChatCharacter | null>(null);
  const [characters, setCharacters] = useState<ChatCharacter[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [voiceOff, setVoiceOff] = useState(false);
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();
  const recorder = useRecorder();

  const idRef = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  function nextId() {
    idRef.current += 1;
    return idRef.current;
  }

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const greeting: Message = { id: nextId(), role: 'assistant', text: t('greeting') };

    if (sessionLoading) {
      return;
    }
    if (!user) {
      router.replace('/login');
      return;
    }

    let active = true;
    (async () => {
      try {
        const me = await apiFetch<MeResponse>('/api/me');
        let list: ChatCharacter[] = [];
        try {
          const raw = await apiFetch<Character[]>(`/api/characters?lang=${locale}`);
          if (Array.isArray(raw) && raw.length > 0) {
            list = raw.map(toChatCharacter);
          }
        } catch {
          list = [];
        }
        if (list.length === 0) {
          list = sampleCharacters(locale).map(toChatCharacter);
        }
        const currentId = me.character?.id ?? me.user?.character;
        const current = list.find((item) => item.id === currentId) ?? list[0] ?? null;
        if (!active) {
          return;
        }
        setCharacters(list);
        setCharacter(current);
        setMessages([greeting]);
        setStatus('ready');
      } catch {
        if (active) {
          setStatus('error');
        }
      }
    })();

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, sending]);

  async function speak(text: string, characterId: string) {
    try {
      const blob = await apiBlob('/api/chat/tts', {
        method: 'POST',
        body: { text, character_id: characterId },
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch {
      // TTS — best-effort: показываем заметку один раз.
      setVoiceOff(true);
    }
  }

  // Запасной путь: если серверное распознавание недоступно (нет ключа
  // облачного STT или провайдер перегружен) — распознаём прямо в браузере.
  function listenInBrowser() {
    if (!isSpeechSupported()) {
      setBanner(t('voice.notSupported'));
      return;
    }
    setBanner(null);
    const recognition = createSpeechRecognizer('en-US', {
      onFinal: (text) => {
        setInput((prev) => (prev ? `${prev} ${text}` : text));
        setToast(t('voiceCaptured'));
      },
      onError: (message) => setBanner(message),
    });
    if (!recognition) {
      setBanner(t('voice.unavailable'));
      return;
    }
    try {
      recognition.start();
      setToast(t('voiceListening'));
    } catch {
      setBanner(t('voice.unavailable'));
    }
  }

  async function handleVoice() {
    if (recorder.recording) {
      const blob = await recorder.stop();
      if (!blob) {
        setBanner(t('error'));
        return;
      }
      setBanner(null);
      try {
        const res = await transcribeAudio(blob, { mode: 'free' });
        const transcript = (res.transcript ?? '').trim();
        if (!transcript) {
          setBanner(t('error'));
          return;
        }
        setInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
        setToast(t('voiceCaptured'));
      } catch (error) {
        if (error instanceof ApiError && (error.status === 503 || error.status === 502)) {
          listenInBrowser();
          return;
        }
        setBanner(errorMessage(error, t('error')));
      }
      return;
    }
    setBanner(null);
    // Если серверного распознавания нет (нет ключа STT) — сразу в браузер,
    // не тратя время на запись и загрузку файла.
    if (!(await serverSttAvailable())) {
      listenInBrowser();
      return;
    }
    const started = await recorder.start();
    if (!started) {
      setBanner(t('error'));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || sending || !character) {
      return;
    }

    setInput('');
    setBanner(null);
    const userMessageId = nextId();
    setMessages((prev) => [...prev, { id: userMessageId, role: 'user', text }]);
    setSending(true);

    if (!user) {
      router.replace('/login');
      setSending(false);
      return;
    }

    try {
      const data = await apiFetch<ChatResponse>('/api/chat', {
        method: 'POST',
        body: { text },
      });
      const reply = data.reply?.trim() || data.next_question?.trim() || '';
      if (!reply) {
        setBanner(t('error'));
        return;
      }
      setMessages((prev) => [...prev, { id: nextId(), role: 'assistant', text: reply }]);

      const corrected = data.corrected_text?.trim() ?? '';
      const wrong = corrected && corrected !== text && data.is_correct === false;
      if (wrong) {
        setMessages((prev) =>
          prev.map((message) =>
            message.id === userMessageId
              ? {
                  ...message,
                  correctedText: corrected,
                  isCorrect: false,
                  issues: data.issues ?? [],
                }
              : message,
          ),
        );
      }

      const returned = data.character;
      if (returned && returned.id) {
        setCharacter((prev) =>
          prev
            ? {
                ...prev,
                id: returned.id,
                name: returned.name || prev.name,
                emoji: returned.emoji || prev.emoji,
              }
            : prev,
        );
      }
      void speak(reply, returned?.id ?? character.id);
    } catch (error) {
      const quota =
        (error instanceof ApiError && error.status === 429) ||
        (error instanceof ApiError && /quota|limit|лимит/i.test(error.message));
      setBanner(errorMessage(error, quota ? t('quota') : t('error')));
    } finally {
      setSending(false);
    }
  }

  async function selectMentor(next: ChatCharacter) {
    if (next.id === character?.id) {
      return;
    }
    setCharacter(next);
    setBanner(null);
    if (!user) {
      return;
    }
    try {
      await apiFetch('/api/me/character', {
        method: 'PUT',
        body: { character_id: next.id },
      });
      setToast(t('selected'));
    } catch (error) {
      setBanner(error instanceof Error ? error.message : t('error'));
    }
  }


  if (status === 'error') {
    return (
      <main className="relative isolate flex min-h-[calc(100dvh-4rem)] items-center justify-center overflow-hidden bg-[linear-gradient(160deg,#0b1220_0%,#111c33_100%)] px-4 text-white">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_50%_-12%,rgba(37,99,235,0.28),transparent_72%)]"
        />
        <div className="relative w-full max-w-md text-center">
          <div
            role="alert"
            className="rounded-3xl border border-rose-400/25 bg-rose-400/15 p-6 text-sm text-rose-200"
          >
            {t('error')}
          </div>
          <Link
            href="/"
            className="mt-6 inline-flex min-h-[48px] items-center justify-center rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
          >
            {t('back')}
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="relative isolate flex h-[calc(100dvh-4rem)] flex-col overflow-hidden bg-[linear-gradient(160deg,#0b1220_0%,#111c33_100%)] text-white">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_20%_-10%,rgba(37,99,235,0.28),transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-32 right-[-15%] h-[380px] w-[380px] rounded-full bg-blue-500/10 blur-3xl"
      />

      <div className="relative mx-auto flex h-full w-full max-w-3xl flex-col px-4">
        <header className="-mx-4 border-b border-white/10 bg-[#0b1425]/80 px-4 backdrop-blur">
          <div className="flex items-center gap-3 py-3">
            <Link
              href="/"
              aria-label={t('back')}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/5 text-slate-300 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
            >
              <BackIcon />
            </Link>
            {character ? (
              <>
                <Avatar character={character} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">{character.name}</p>
                  <p className="truncate text-xs text-slate-400">
                    {character.tagline ?? t('subtitle')}
                  </p>
                </div>
              </>
            ) : (
              <p className="text-sm font-semibold text-white">{t('title')}</p>
            )}
          </div>
        </header>

        <div
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          className="flex-1 space-y-4 overflow-y-auto py-6"
        >
          {messages.map((message) =>
            message.role === 'user' ? (
              <div key={message.id} className="flex flex-col items-end">
                <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-blue-600 px-4 py-2.5 text-sm text-white shadow-lg shadow-blue-950/40">
                  {message.text}
                </div>
                {message.correctedText ? (
                  <div className="mt-1 max-w-[80%] rounded-2xl rounded-br-md border border-emerald-400/25 bg-emerald-400/15 px-4 py-2 text-xs text-emerald-300">
                    <p className="font-semibold">{t('correction')}</p>
                    <p className="mt-0.5">{message.correctedText}</p>
                    {message.issues && message.issues.length > 0 ? (
                      <ul className="mt-1 space-y-0.5 text-emerald-200/80">
                        {message.issues.map((issue, idx) => (
                          <li key={idx}>
                            · {issue.note || issue.category || ''}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : (
              <div key={message.id} className="flex items-start gap-2">
                {character ? <Avatar character={character} size="sm" /> : null}
                <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-bl-md border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-slate-200 backdrop-blur">
                  {message.text}
                </div>
              </div>
            ),
          )}

          {sending ? (
            <div className="flex items-start gap-2">
              {character ? <Avatar character={character} size="sm" /> : null}
              <div className="flex items-center gap-1 rounded-2xl rounded-bl-md border border-white/10 bg-white/5 px-4 py-3 backdrop-blur">
                <span className="sr-only">{t('typing')}</span>
                <span className="h-2 w-2 animate-bounce rounded-full bg-blue-300/70 motion-reduce:animate-none [animation-delay:-0.3s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-blue-300/70 motion-reduce:animate-none [animation-delay:-0.15s]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-blue-300/70 motion-reduce:animate-none" />
              </div>
            </div>
          ) : null}

          <div ref={bottomRef} />
        </div>

        <div className="-mx-4 border-t border-white/10 bg-[#0b1425]/80 px-4 pb-5 pt-3 backdrop-blur">
          {banner ? (
            <div className="mb-3 rounded-2xl border border-amber-300/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
              {banner}
            </div>
          ) : null}

          {voiceOff ? (
            <p className="mb-2 text-xs text-blue-200/50">{t('voiceOff')}</p>
          ) : null}

          {characters.length > 0 ? (
            <>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-200/60">
                {t('switch')}
              </p>
              <div className="flex flex-wrap gap-2">
                {characters.map((item) => {
                  const active = item.id === character?.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => selectMentor(item)}
                      className={
                        active
                          ? 'inline-flex min-h-[36px] items-center gap-1.5 rounded-full border border-blue-400/40 bg-blue-500/20 px-3.5 text-xs font-medium text-blue-50'
                          : 'inline-flex min-h-[36px] items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3.5 text-xs font-medium text-slate-300 transition hover:border-white/20 hover:bg-white/10 hover:text-white'
                      }
                    >
                      <span>{item.emoji}</span>
                      {item.name}
                    </button>
                  );
                })}
              </div>
            </>
          ) : null}

          <form onSubmit={handleSubmit} className="mt-3 flex items-center gap-2">
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={t('placeholder')}
              className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-blue-400/60 focus:ring-2 focus:ring-blue-400/40"
            />
            <button
              type="button"
              onClick={handleVoice}
              disabled={recorder.busy}
              aria-label={t('mic')}
              title={t('mic')}
              aria-pressed={recorder.recording}
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40 disabled:cursor-not-allowed disabled:opacity-60 ${
                recorder.recording
                  ? 'border-rose-400/50 bg-rose-400/15 text-rose-300'
                  : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white'
              }`}
            >
              <MicIcon />
            </button>
            <button
              type="submit"
              disabled={sending || input.trim().length === 0}
              className="shrink-0 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t('send')}
            </button>
          </form>
        </div>
      </div>

      {toast ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900/95 px-4 py-3 text-sm text-white shadow-xl ring-1 ring-white/10">
          {toast}
        </div>
      ) : null}
    </main>
  );
}
