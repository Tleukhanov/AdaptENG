import { getTranslations } from 'next-intl/server';
import Link from 'next/link';
import { getLocale } from '@/lib/i18n';
import { sampleCharacters } from '@/lib/characters';
import type { Character, Locale } from '@/lib/characters';
import CharacterCard from '@/components/CharacterCard';

async function loadCharacters(locale: Locale): Promise<Character[]> {
  // Персонажи идут через тот же домен (/api/* проксирует Next.js).
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
    <main className="min-h-screen bg-[linear-gradient(160deg,#0b1220_0%,#111c33_100%)]">
      <div className="mx-auto max-w-6xl px-4">
        <section className="grid items-center gap-10 py-16 md:grid-cols-2 md:py-24">
          <div>
            <span className="inline-flex items-center rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-semibold text-sky-300 backdrop-blur">
              {t('hero.badge')}
            </span>
            <h1 className="mt-5 text-4xl font-extrabold leading-tight text-white md:text-5xl">
              {t('hero.title')}
            </h1>
            <p className="mt-5 max-w-xl text-lg text-slate-300">{t('hero.subtitle')}</p>
            <div className="mt-8 flex max-w-sm flex-col gap-3">
              <Link
                href="/welcome"
                className="inline-flex min-h-[48px] items-center justify-center rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-900/40 transition hover:from-blue-500 hover:to-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
              >
                {t('welcome.landingCta')}
              </Link>
              <p className="text-xs leading-relaxed text-slate-400">{t('welcome.landingHint')}</p>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 shadow-2xl shadow-blue-950/40 backdrop-blur">
            <div className="flex items-center gap-3">
              <div className="adapteng-gradient flex h-12 w-12 items-center justify-center rounded-2xl text-2xl">
                {preview.emoji}
              </div>
              <div>
                <p className="font-semibold text-white">{preview.name}</p>
                <p className="text-sm text-slate-400">{preview.tagline}</p>
              </div>
            </div>
            <p className="mt-4 text-sm text-slate-300">{preview.description}</p>
            <div className="mt-6 space-y-2 rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-sm font-semibold text-white">{t('hero.howTitle')}</p>
              <ol className="space-y-2 text-sm text-slate-300">
                <li className="flex gap-2">
                  <span className="font-semibold text-sky-300">1</span>
                  <span>{t('hero.how1')}</span>
                </li>
                <li className="flex gap-2">
                  <span className="font-semibold text-sky-300">2</span>
                  <span>{t('hero.how2')}</span>
                </li>
                <li className="flex gap-2">
                  <span className="font-semibold text-sky-300">3</span>
                  <span>{t('hero.how3')}</span>
                </li>
              </ol>
            </div>
          </div>
        </section>

        <section id="characters" className="scroll-mt-20 py-12">
          <h2 className="text-3xl font-bold text-white">{t('characters.title')}</h2>
          <p className="mt-2 max-w-2xl text-slate-300">{t('characters.subtitle')}</p>
          <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {characters.map((character) => (
              <CharacterCard key={character.id} character={character} />
            ))}
          </div>
        </section>

        <footer className="border-t border-white/10 py-10 text-center text-sm text-slate-400">
          <p>{t('footer.tagline')}</p>
          <p className="mt-3">
            <Link
              href="/login"
              className="text-xs text-slate-500 underline-offset-2 transition hover:text-slate-300 hover:underline"
            >
              {t('footer.existingAccount')}
            </Link>
          </p>
        </footer>
      </div>
    </main>
  );
}
