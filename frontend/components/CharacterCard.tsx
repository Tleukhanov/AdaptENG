'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import { useTranslations } from 'next-intl';
import type { Character } from '@/lib/characters';
import { apiFetch } from '@/lib/api';
import { useSession } from '@/lib/session';

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
  const palette =
    character.palette.length >= 2 ? character.palette : ['#6366f1', '#8b5cf6'];

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
    <article className="group relative flex flex-col rounded-3xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg">
      {selected ? (
        <span
          className="absolute right-4 top-4 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-xs font-bold text-white shadow"
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
            className="h-14 w-14 rounded-2xl object-cover"
          />
        ) : (
          <div
            className="flex h-14 w-14 items-center justify-center rounded-2xl text-2xl text-white"
            style={{
              backgroundImage: `linear-gradient(135deg, ${palette[0]}, ${palette[1]})`,
            }}
          >
            {character.emoji}
          </div>
        )}
        <div>
          <h3 className="font-semibold text-slate-900">{name}</h3>
          <p className="text-sm text-slate-500">{tagline}</p>
        </div>
      </div>

      <p className="mt-4 line-clamp-3 flex-1 text-sm text-slate-600">{description}</p>

      <Link
        href="/chat"
        onClick={handleSelect}
        aria-busy={busy}
        className="mt-5 inline-flex items-center justify-center rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700"
      >
        {t('select')}
      </Link>

      {toast ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-xl">
          {toast}
        </div>
      ) : null}
    </article>
  );
}
