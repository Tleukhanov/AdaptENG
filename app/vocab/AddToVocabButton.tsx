'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslations } from 'next-intl';
import { addVocabWord, errorMessage } from '@/lib/api';

const FLY_MS = 420;

const INPUT =
  'mt-1 w-full rounded-xl border border-white/12 bg-white/5 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-blue-400/80 focus:bg-white/[0.07] focus:ring-2 focus:ring-blue-500/25';

const BUTTON =
  'inline-flex min-h-[34px] items-center gap-1.5 rounded-full border border-blue-400/30 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-100 transition hover:border-blue-300/60 hover:bg-blue-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:cursor-not-allowed disabled:opacity-60';

const BUTTON_ADDED =
  'inline-flex min-h-[34px] items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1.5 text-xs font-semibold text-emerald-300';

/**
 * Иконка словаря в шапке урока. Слово «улетает» именно в неё.
 * Рендерится один раз на страницу; id ищет `flyWord`.
 */
export function VocabFlyTarget({ className = '' }: { className?: string }) {
  const t = useTranslations('vocab');
  return (
    <Link
      id="vocab-fly-target"
      href="/vocab"
      aria-label={t('title')}
      title={t('title')}
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-base text-blue-100 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] ${className}`}
    >
      <span aria-hidden="true">📖</span>
    </Link>
  );
}

/** Выделенный пользователем английский токен — подсказка для ручного добавления. */
function selectedToken(): string {
  if (typeof window === 'undefined') {
    return '';
  }
  const raw = window.getSelection()?.toString().trim() ?? '';
  const match = raw.match(/[A-Za-z][A-Za-z'-]*/);
  return match ? match[0] : '';
}

/**
 * Летящая копия слова: fixed-элемент, CSS-transition к иконке словаря.
 * Без библиотек; при `prefers-reduced-motion` анимация пропускается.
 */
function flyWord(source: HTMLElement | null, text: string): void {
  if (!source || !text || typeof window === 'undefined') {
    return;
  }
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    return;
  }
  const target = document.getElementById('vocab-fly-target') ?? source;
  const from = source.getBoundingClientRect();
  const to = target.getBoundingClientRect();

  const ghost = document.createElement('span');
  ghost.textContent = text;
  ghost.setAttribute('aria-hidden', 'true');
  ghost.className =
    'pointer-events-none fixed z-[70] whitespace-nowrap rounded-full border border-blue-300/40 bg-blue-600 px-3 py-1 text-xs font-semibold text-white shadow-lg shadow-blue-950/60';
  ghost.style.left = `${from.left}px`;
  ghost.style.top = `${from.top}px`;
  document.body.appendChild(ghost);

  const dx = to.left + to.width / 2 - (from.left + from.width / 2);
  const dy = to.top + to.height / 2 - (from.top + from.height / 2);

  window.requestAnimationFrame(() => {
    ghost.style.transition = `transform ${FLY_MS}ms cubic-bezier(0.22, 0.61, 0.36, 1), opacity ${FLY_MS}ms ease-in`;
    ghost.style.transform = `translate(${dx}px, ${dy}px) scale(0.3)`;
    ghost.style.opacity = '0';
  });
  window.setTimeout(() => ghost.remove(), FLY_MS + 120);
}

type Props = {
  /** Слово из карточки урока. В ручном режиме не используется. */
  word?: string;
  translation?: string;
  example?: string;
  /** Ручной режим: мини-форма «слово + перевод» (реплики наставника). */
  manual?: boolean;
  className?: string;
};

/**
 * Кнопка «+ в словарь»: POST /api/vocab, затем слово улетает в иконку
 * словаря и показывается тост. После успеха кнопка блокируется.
 */
export default function AddToVocabButton({
  word,
  translation,
  example,
  manual = false,
  className = '',
}: Props) {
  const t = useTranslations('vocab');
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const toastTimer = useRef<number | null>(null);
  const [added, setAdded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [formWord, setFormWord] = useState('');
  const [formTranslation, setFormTranslation] = useState('');
  const [toast, setToast] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  // Слово на карточке сменилось — сбрасываем состояние кнопки.
  useEffect(() => {
    setAdded(false);
    setOpen(false);
    setBusy(false);
    setFormWord('');
    setFormTranslation('');
  }, [word]);

  useEffect(
    () => () => {
      if (toastTimer.current) {
        window.clearTimeout(toastTimer.current);
      }
    },
    [],
  );

  function showToast(kind: 'ok' | 'error', text: string) {
    if (toastTimer.current) {
      window.clearTimeout(toastTimer.current);
    }
    setToast({ kind, text });
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }

  async function save(payload: { word: string; translation: string; example?: string }) {
    setBusy(true);
    try {
      await addVocabWord(payload);
      setAdded(true);
      setOpen(false);
      flyWord(buttonRef.current, payload.word);
      showToast('ok', t('added'));
    } catch (error) {
      showToast('error', errorMessage(error, t('addError')));
    } finally {
      setBusy(false);
    }
  }

  function handleClick() {
    if (added || busy) {
      return;
    }
    if (!manual) {
      void save({ word: word ?? '', translation: translation ?? '', example });
      return;
    }
    if (open) {
      setOpen(false);
      return;
    }
    setFormWord(selectedToken());
    setFormTranslation('');
    setOpen(true);
  }

  function handleManualSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextWord = formWord.trim();
    const nextTranslation = formTranslation.trim();
    if (!nextWord || !nextTranslation || busy) {
      return;
    }
    void save({ word: nextWord, translation: nextTranslation });
  }

  return (
    <div className={`relative inline-flex ${className}`}>
      <button
        ref={buttonRef}
        type="button"
        onClick={handleClick}
        disabled={busy || added}
        aria-expanded={manual ? open : undefined}
        className={added ? BUTTON_ADDED : BUTTON}
      >
        <span aria-hidden="true">{added ? '✓' : '＋'}</span>
        {added ? t('inDictionary') : busy ? t('adding') : t('addToVocab')}
      </button>

      {manual && open && !added ? (
        <form
          onSubmit={handleManualSubmit}
          className="absolute left-0 top-full z-30 mt-2 w-64 rounded-2xl border border-white/10 bg-[#0f1b2e]/95 p-3 text-left shadow-xl shadow-blue-950/50 backdrop-blur"
        >
          <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('word')}
            <input
              value={formWord}
              onChange={(event) => setFormWord(event.target.value)}
              className={INPUT}
              placeholder="word"
              autoFocus
              required
            />
          </label>
          <label className="mt-2 block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t('translation')}
            <input
              value={formTranslation}
              onChange={(event) => setFormTranslation(event.target.value)}
              className={INPUT}
              placeholder={t('translation')}
              required
            />
          </label>
          <div className="mt-3 flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className="inline-flex min-h-[34px] flex-1 items-center justify-center rounded-xl bg-blue-600 px-3 text-xs font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? t('adding') : t('save')}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="inline-flex min-h-[34px] items-center justify-center rounded-xl border border-white/15 px-3 text-xs font-semibold text-slate-200 transition hover:bg-white/10"
            >
              {t('cancel')}
            </button>
          </div>
        </form>
      ) : null}

      {toast ? (
        <span
          role="status"
          className={`fixed bottom-24 left-1/2 z-[70] -translate-x-1/2 whitespace-nowrap rounded-xl px-4 py-2.5 text-sm shadow-xl ring-1 backdrop-blur ${
            toast.kind === 'ok'
              ? 'bg-[#0f1b2e]/95 text-emerald-200 ring-emerald-400/30'
              : 'bg-[#0f1b2e]/95 text-rose-200 ring-rose-400/30'
          }`}
        >
          {toast.text}
        </span>
      ) : null}
    </div>
  );
}
