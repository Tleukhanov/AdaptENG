'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import { useTranslations } from 'next-intl';
import type { Character } from '@/lib/characters';

const API = process.env.NEXT_PUBLIC_API_URL ?? '';

export default function CharacterCard({ character }: { character: Character }) {
  const t = useTranslations('character');
  const tRoot = useTranslations();
  const [toast, setToast] = useState<string | null>(null);

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

  function handleSelect(event: MouseEvent<HTMLAnchorElement>) {
    if (API) {
      return;
    }
    event.preventDefault();
    setToast(tRoot('demo.toast'));
  }

  return (
    <article className="group flex flex-col rounded-3xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg">
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
        href="/dashboard"
        onClick={handleSelect}
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
