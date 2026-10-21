'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useSession } from '@/lib/session';
import { sampleCharacters } from '@/lib/characters';
import type { Character, Locale } from '@/lib/characters';
import { ApiError, apiBlob, apiFetch, errorMessage, transcribeAudio } from '@/lib/api';
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

const FALLBACK_PALETTE = ['#6366f1', '#8b5cf6'];


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
      setBanner(t('voice.unavailable'));
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
      <main className="mx-auto max-w-md px-4 py-24 text-center">
        <div className="rounded-3xl border border-red-200 bg-red-50 p-6 text-red-700">
          {t('error')}
        </div>
        <Link
          href="/"
          className="mt-6 inline-block rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white"
        >
          {t('back')}
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto flex h-[calc(100dvh-4rem)] max-w-3xl flex-col overflow-hidden px-4">
      <header className="-mx-4 border-b border-slate-200/70 bg-white/85 px-4 backdrop-blur">
        <div className="flex items-center gap-3 py-3">
          <Link
            href="/"
            aria-label={t('back')}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-100"
          >
            <BackIcon />
          </Link>
          {character ? (
            <>
              <Avatar character={character} />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">{character.name}</p>
                <p className="truncate text-xs text-slate-500">
                  {character.tagline ?? t('subtitle')}
                </p>
              </div>
            </>
          ) : (
            <p className="text-sm font-semibold text-slate-900">{t('title')}</p>
          )}
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto py-6">

        {messages.map((message) =>
          message.role === 'user' ? (
            <div key={message.id} className="flex flex-col items-end">
              <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-slate-900 px-4 py-2.5 text-sm text-white">
                {message.text}
              </div>
              {message.correctedText ? (
                <div className="mt-1 max-w-[80%] rounded-2xl rounded-br-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs text-emerald-800">
                  <p className="font-semibold">{t('correction')}</p>
                  <p className="mt-0.5">{message.correctedText}</p>
                  {message.issues && message.issues.length > 0 ? (
                    <ul className="mt-1 space-y-0.5 text-emerald-700">
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
              <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700 shadow-sm">
                {message.text}
              </div>
            </div>
          ),
        )}

        {sending ? (
          <div className="flex items-start gap-2">
            {character ? <Avatar character={character} size="sm" /> : null}
            <div className="flex items-center gap-1 rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 shadow-sm">
              <span className="sr-only">{t('typing')}</span>
              <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400" />
            </div>
          </div>
        ) : null}

        <div ref={bottomRef} />
      </div>

      <div className="-mx-4 border-t border-slate-200/70 bg-white/90 px-4 pb-5 pt-3 backdrop-blur">
        {banner ? (
          <div className="mb-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {banner}
          </div>
        ) : null}

        {voiceOff ? (
          <p className="mb-2 text-xs text-slate-500">{t('voiceOff')}</p>
        ) : null}

        {characters.length > 0 ? (
          <>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
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
? 'inline-flex min-h-[36px] items-center gap-1.5 rounded-full border border-slate-900 bg-slate-900 px-3.5 text-xs font-medium text-white'
                    : 'inline-flex min-h-[36px] items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50'
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
            className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
          />
          <button
            type="button"
            onClick={handleVoice}
            disabled={recorder.busy}
            aria-label={t('mic')}
            title={t('mic')}
            aria-pressed={recorder.recording}
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border transition disabled:opacity-60 ${
              recorder.recording
                ? 'border-red-200 bg-red-50 text-red-600'
                : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
            }`}
          >
            <MicIcon />
          </button>
          <button
            type="submit"
            disabled={sending || input.trim().length === 0}
            className="shrink-0 rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t('send')}
          </button>
        </form>
      </div>

      {toast ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-xl">
          {toast}
        </div>
      ) : null}
    </main>
  );
}
