import { getTranslations } from 'next-intl/server';
import Link from 'next/link';
import { getLocale } from '@/lib/i18n';
import { sampleCharacters } from '@/lib/characters';
import type { Character, Locale } from '@/lib/characters';
import CharacterCard from '@/components/CharacterCard';

async function loadCharacters(locale: Locale): Promise<Character[]> {
  try {
    const response = await fetch(`/api/characters?lang=${locale}`, {
      cache: 'no-store',
    });
    if (!response.ok) {
      return sampleCharacters(locale);
    }
    const data = (await response.json()) as Character[];
    return Array.isArray(data) && data.length > 0 ? data : sampleCharacters(locale);
  } catch {
    return sampleCharacters(locale);
  }
}

export default async function LandingPage() {
  const locale = await getLocale();
  const t = await getTranslations();
  const characters = await loadCharacters(locale);
  const preview = characters[0] ?? sampleCharacters(locale)[0];

  return (
    <main className="min-h-screen bg-paper-100">
      {/* Masthead */}
      <section className="border-b border-ink-900/10">
        <div className="mx-auto max-w-6xl px-4 py-6">
          <div className="flex items-center justify-between text-xs font-medium uppercase tracking-[0.22em] text-ink-500">
            <span>Vol. 01 · {t('hero.badge')}</span>
            <span className="hidden sm:inline">AdaptENG · AI English Tutor</span>
          </div>
        </div>
      </section>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-4 py-16 md:py-24">
        <div className="grid items-end gap-12 md:grid-cols-12">
          <div className="md:col-span-7">
            <p className="reveal reveal-1 font-display text-sm italic text-accent-600">
              — a personal tutor that adapts to you
            </p>
            <h1 className="reveal reveal-2 mt-4 font-display text-5xl font-semibold leading-[0.95] tracking-tight text-ink-900 md:text-7xl">
              {t('hero.title')}
            </h1>
            <p className="reveal reveal-3 mt-6 max-w-xl text-lg leading-relaxed text-ink-700">
              {t('hero.subtitle')}
            </p>
            <div className="reveal reveal-4 mt-10 flex flex-col gap-4 sm:flex-row sm:items-center">
              <Link
                href="/welcome"
                className="inline-flex min-h-[52px] items-center justify-center rounded-full bg-ink-900 px-8 py-3 text-sm font-semibold text-paper-50 transition hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-600/60 focus-visible:ring-offset-2 focus-visible:ring-offset-paper-100"
              >
                {t('welcome.landingCta')}
              </Link>
              <p className="max-w-xs text-xs leading-relaxed text-ink-500">
                {t('welcome.landingHint')}
              </p>
            </div>
          </div>

          <aside className="md:col-span-5">
            <div className="relative">
              <div className="absolute -inset-3 -z-10 rotate-1 rounded-3xl bg-accent-100" />
              <div className="rounded-3xl border border-ink-900/10 bg-paper-50 p-6 shadow-[0_30px_80px_-40px_rgba(26,22,18,0.35)]">
                <div className="flex items-center gap-4">
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-600 text-2xl text-paper-50">
                    {preview.emoji}
                  </div>
                  <div>
                    <p className="font-display text-xl font-semibold text-ink-900">
                      {preview.name}
                    </p>
                    <p className="text-sm text-ink-500">{preview.tagline}</p>
                  </div>
                </div>
                <p className="mt-5 text-sm leading-relaxed text-ink-700">
                  {preview.description}
                </p>
                <div className="mt-6 border-t border-ink-900/10 pt-5">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-500">
                    {t('hero.howTitle')}
                  </p>
                  <ol className="mt-3 space-y-3 text-sm text-ink-700">
                    <li className="flex gap-3">
                      <span className="font-display text-lg font-semibold text-accent-600">01</span>
                      <span>{t('hero.how1')}</span>
                    </li>
                    <li className="flex gap-3">
                      <span className="font-display text-lg font-semibold text-accent-600">02</span>
                      <span>{t('hero.how2')}</span>
                    </li>
                    <li className="flex gap-3">
                      <span className="font-display text-lg font-semibold text-accent-600">03</span>
                      <span>{t('hero.how3')}</span>
                    </li>
                  </ol>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </section>

      {/* Character strip */}
      <section className="border-t border-ink-900/10 bg-paper-200/40">
        <div className="mx-auto max-w-6xl px-4 py-12">
          <div className="flex items-end justify-between gap-6">
            <h2 className="font-display text-3xl font-semibold text-ink-900">
              {t('hero.charactersTitle')}
            </h2>
            <p className="hidden max-w-sm text-sm text-ink-500 sm:block">
              {t('hero.charactersSubtitle')}
            </p>
          </div>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {characters.slice(0, 4).map((c) => (
              <CharacterCard key={c.id} character={c} />
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
