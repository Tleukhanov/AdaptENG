'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import { useTranslations } from 'next-intl';
import type { Character } from '@/lib/characters';
import { apiFetch } from '@/lib/api';
import { useSession } from '@/lib/session';

const FALLBACK_PALETTE = ['#9a3412', '#c2410c'];

export default function CharacterCard({
  character,
  selected = false,
}: {
  character: Character;
  selected?: boolean;
}) {
  const t = useTranslations('character');
  const tRoot = useTranslations();
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { user, loading: sessionLoading } = useSession();

  const name = character.name;
  const tagline = character.tagline;
  const description = character.description;
  const palette = character.palette.length >= 2 ? character.palette : FALLBACK_PALETTE;

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function handleSelect(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    if (busy) {
      return;
    }
    if (sessionLoading) {
      return;
    }
    if (!user) {
      window.location.href = '/login';
      return;
    }
    setBusy(true);
    try {
      await apiFetch('/api/me/character', {
        method: 'PUT',
        body: { character_id: character.id },
      });
      setToast(tRoot('chat.selected'));
      window.setTimeout(() => {
        window.location.href = '/chat';
      }, 600);
    } catch (error) {
      setToast(error instanceof Error ? error.message : tRoot('chat.error'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="group relative flex flex-col rounded-2xl border border-ink-900/10 bg-paper-50 p-5 shadow-[0_24px_60px_-40px_rgba(26,22,18,0.3)] transition hover:-translate-y-1 hover:border-accent-600/40 hover:shadow-[0_30px_70px_-35px_rgba(194,65,12,0.25)]">
      {selected ? (
        <span
          className="absolute right-4 top-4 flex h-6 w-6 items-center justify-center rounded-full bg-accent-600 text-xs font-bold text-paper-50"
          aria-hidden="true"
        >
          ✓
        </span>
      ) : null}

      <div className="flex items-center gap-4">
        {character.avatar ? (
          <img
            src={character.avatar}
            alt={name}
            className="h-14 w-14 rounded-xl object-cover ring-1 ring-ink-900/10"
          />
        ) : (
          <div
            className="flex h-14 w-14 items-center justify-center rounded-xl text-2xl text-paper-50 ring-1 ring-ink-900/10"
            style={{
              backgroundImage: `linear-gradient(135deg, ${palette[0]}, ${palette[1]})`,
            }}
          >
            {character.emoji}
          </div>
        )}
        <div>
          <h3 className="font-display text-lg font-semibold text-ink-900">{name}</h3>
          <p className="text-sm text-ink-500">{tagline}</p>
        </div>
      </div>

      <p className="mt-4 line-clamp-3 flex-1 text-sm leading-relaxed text-ink-700">
        {description}
      </p>

      <Link
        href="/chat"
        onClick={handleSelect}
        aria-busy={busy}
        className="mt-5 inline-flex min-h-[44px] items-center justify-center rounded-full bg-ink-900 px-4 py-2.5 text-sm font-semibold text-paper-50 transition hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-600/60 focus-visible:ring-offset-2 focus-visible:ring-offset-paper-100"
      >
        {t('select')}
      </Link>

      {toast ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl border border-ink-900/10 bg-paper-50 px-4 py-3 text-sm text-ink-900 shadow-xl">
          {toast}
        </div>
      ) : null}
    </article>
  );
}
