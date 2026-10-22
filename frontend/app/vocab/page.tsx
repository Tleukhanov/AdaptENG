'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useSession } from '@/lib/session';
import {
  checkVocabWord,
  deleteVocabWord,
  errorMessage,
  getVocab,
  reviewWord,
  type VocabCheckResponse,
  type VocabWord,
} from '@/lib/api';

type View = 'list' | 'setup' | 'train' | 'result';
type PageStatus = 'loading' | 'ready' | 'error';

type ScoreItem = {
  id: number;
  word: string;
  score: number;
  translationOk: boolean;
  sentenceOk: boolean;
};

type TrainResult = {
  reason: 'time' | 'done';
  items: ScoreItem[];
};

const PRIMARY =
  'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220] disabled:cursor-not-allowed disabled:opacity-50';

const SECONDARY =
  'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-white/15 px-5 text-sm font-semibold text-blue-100 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]';

function formatTime(totalSeconds: number): string {
  const safe = Math.max(0, totalSeconds);
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function clampScore(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

/** Качество для SRS по баллу проверки: чем выше балл, тем увереннее повторение. */
function reviewQuality(score: number): number {
  if (score >= 85) return 5;
  if (score >= 65) return 4;
  if (score >= 45) return 3;
  if (score >= 25) return 2;
  return 1;
}

function scoreBadge(score: number): string {
  if (score >= 80) {
    return 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300';
  }
  if (score >= 50) {
    return 'border-amber-400/25 bg-amber-400/10 text-amber-200';
  }
  return 'border-rose-400/25 bg-rose-400/10 text-rose-300';
}

function TrashIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden="true"
    >
      <path d="M4 7h16" />
      <path d="M10 11v6M14 11v6" />
      <path d="M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  );
}

export default function VocabPage() {
  const t = useTranslations('vocab');
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();

  const [pageStatus, setPageStatus] = useState<PageStatus>('loading');
  const [words, setWords] = useState<VocabWord[]>([]);
  const [total, setTotal] = useState(0);
  const [due, setDue] = useState(0);
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [listError, setListError] = useState<string | null>(null);

  const [view, setView] = useState<View>('list');
  const [queue, setQueue] = useState<VocabWord[]>([]);
  const [step, setStep] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [translation, setTranslation] = useState('');
  const [sentence, setSentence] = useState('');
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<VocabCheckResponse | null>(null);
  const [scores, setScores] = useState<ScoreItem[]>([]);
  const [result, setResult] = useState<TrainResult | null>(null);
  const [trainError, setTrainError] = useState<string | null>(null);

  async function load() {
    setPageStatus('loading');
    setListError(null);
    try {
      const data = await getVocab(200, 0);
      setWords(Array.isArray(data.words) ? data.words : []);
      setTotal(data.total ?? 0);
      setDue(data.due ?? 0);
      setPageStatus('ready');
    } catch {
      setPageStatus('error');
    }
  }

  useEffect(() => {
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
        const data = await getVocab(200, 0);
        if (!active) return;
        setWords(Array.isArray(data.words) ? data.words : []);
        setTotal(data.total ?? 0);
        setDue(data.due ?? 0);
        setPageStatus('ready');
      } catch {
        if (active) {
          setPageStatus('error');
        }
      }
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionLoading, user]);

  // Таймер тренировки идёт, пока показывается вопрос, и замирает на разборе ответа.
  useEffect(() => {
    if (view !== 'train' || check) {
      return;
    }
    const timer = window.setInterval(() => {
      setRemaining((value) => (value > 0 ? value - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [view, check]);

  useEffect(() => {
    if (view === 'train' && remaining === 0) {
      setResult({ reason: 'time', items: scores });
      setView('result');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining, view]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) {
      return words;
    }
    return words.filter(
      (item) =>
        item.word.toLowerCase().includes(needle) ||
        (item.translation ?? '').toLowerCase().includes(needle),
    );
  }, [query, words]);

  const allSeconds = Math.max(120, words.length * 30);
  const current = queue[step];

  function toggleExpanded(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleDelete(item: VocabWord) {
    setListError(null);
    setWords((prev) => prev.filter((row) => row.id !== item.id));
    setTotal((prev) => Math.max(0, prev - 1));
    try {
      await deleteVocabWord(item.id);
    } catch (error) {
      setWords((prev) => [...prev, item].sort((a, b) => a.id - b.id));
      setTotal((prev) => prev + 1);
      setListError(errorMessage(error, t('deleteError')));
    }
  }

  function startTraining(limit: '10' | 'all') {
    if (words.length === 0) {
      return;
    }
    setQueue(words);
    setStep(0);
    setRemaining(limit === '10' ? 600 : allSeconds);
    setTranslation('');
    setSentence('');
    setCheck(null);
    setChecking(false);
    setScores([]);
    setResult(null);
    setTrainError(null);
    setView('train');
  }

  async function handleCheck() {
    if (!current || check || checking || !translation.trim()) {
      return;
    }
    setChecking(true);
    setTrainError(null);
    try {
      const response = await checkVocabWord({
        word_id: current.id,
        translation: translation.trim(),
        sentence: sentence.trim(),
      });
      const score = clampScore(response.score);
      setCheck(response);
      setScores((prev) => [
        ...prev,
        {
          id: current.id,
          word: current.word,
          score,
          translationOk: Boolean(response.translation_ok),
          sentenceOk: Boolean(response.sentence_ok),
        },
      ]);
      // Тренировка тоже двигает SRS: балл → качество повторения.
      void reviewWord(current.id, reviewQuality(score)).catch(() => {});
    } catch (error) {
      setTrainError(errorMessage(error, t('checkError')));
    } finally {
      setChecking(false);
    }
  }

  function handleNext() {
    setCheck(null);
    setTrainError(null);
    setTranslation('');
    setSentence('');
    if (step + 1 < queue.length) {
      setStep((value) => value + 1);
      return;
    }
    setResult({ reason: 'done', items: scores });
    setView('result');
  }

  function resetTraining() {
    setView('setup');
    setCheck(null);
    setTrainError(null);
  }

  const averageScore =
    result && result.items.length > 0
      ? Math.round(result.items.reduce((sum, item) => sum + item.score, 0) / result.items.length)
      : 0;

  return (
    <main className="page-dark relative isolate min-h-[calc(100dvh-4rem)] overflow-hidden px-4 py-8 text-slate-100 sm:py-10">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_20%_-10%,rgba(37,99,235,0.28),transparent_70%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 right-[-10%] h-[380px] w-[380px] rounded-full bg-sky-500/10 blur-3xl"
      />

      <div className="relative mx-auto w-full max-w-3xl">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-sky-300">AdaptENG</p>
            <h1 className="mt-1 text-3xl font-bold text-white">{t('title')}</h1>
            <p className="mt-2 text-sm text-slate-400">{t('subtitle')}</p>
          </div>
          <Link
            href="/menu"
            className="inline-flex min-h-[36px] items-center rounded-lg px-2 py-2 text-sm font-semibold text-blue-300 transition hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40"
          >
            {t('toMenu')}
          </Link>
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-300 backdrop-blur">
            📚 {t('total')}: <span className="text-sky-300">{total}</span>
          </span>
          <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-300 backdrop-blur">
            🔁 {t('due')}: <span className="text-amber-200">{due}</span>
          </span>
        </div>

        {view === 'list' ? (
          <>
            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1">
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t('searchPlaceholder')}
                  aria-label={t('searchPlaceholder')}
                  className="field"
                />
              </div>
              <button
                type="button"
                onClick={() => setView('setup')}
                disabled={words.length === 0}
                className={`${PRIMARY} shrink-0`}
              >
                🎯 {t('train')}
              </button>
            </div>

            {listError ? (
              <div
                role="alert"
                className="mt-4 rounded-2xl border border-rose-400/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200"
              >
                {listError}
              </div>
            ) : null}

            {pageStatus === 'loading' ? (
              <div className="mt-6 space-y-3" aria-hidden="true">
                {[0, 1, 2].map((index) => (
                  <div key={index} className="h-20 animate-pulse rounded-3xl border border-white/10 bg-white/5" />
                ))}
              </div>
            ) : null}

            {pageStatus === 'error' ? (
              <div
                role="alert"
                className="mt-6 rounded-3xl border border-rose-400/30 bg-rose-400/10 p-6 text-rose-100"
              >
                <p className="text-sm">{t('loadError')}</p>
                <button
                  type="button"
                  onClick={() => void load()}
                  className="mt-4 inline-flex min-h-[40px] items-center justify-center rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-500"
                >
                  {t('retry')}
                </button>
              </div>
            ) : null}

            {pageStatus === 'ready' && words.length === 0 ? (
              <div className="panel mt-6 p-8 text-center">
                <div
                  aria-hidden="true"
                  className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-sky-400 text-2xl text-white"
                >
                  📖
                </div>
                <h2 className="text-xl font-bold text-white">{t('emptyTitle')}</h2>
                <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-400">
                  {t('emptyHint')}
                </p>
                <Link href="/lesson" className={`mt-6 ${PRIMARY}`}>
                  {t('toLesson')}
                </Link>
              </div>
            ) : null}

            {pageStatus === 'ready' && words.length > 0 && filtered.length === 0 ? (
              <p className="mt-6 rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm text-slate-400">
                {t('noResults')}
              </p>
            ) : null}

            {pageStatus === 'ready' && filtered.length > 0 ? (
              <ul className="mt-6 space-y-3">
                {filtered.map((item) => {
                  const isOpen = expanded.has(item.id);
                  return (
                    <li key={item.id} className="panel px-4 py-4 sm:px-5">
                      <div className="flex items-start gap-2">
                        <button
                          type="button"
                          onClick={() => toggleExpanded(item.id)}
                          aria-expanded={isOpen}
                          className="min-w-0 flex-1 rounded-2xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
                        >
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="text-lg font-semibold text-white">{item.word}</span>
                            {item.status === 'known' ? (
                              <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                                {t('status.known')}
                              </span>
                            ) : item.status === 'learning' ? (
                              <span className="rounded-full border border-sky-400/25 bg-sky-400/10 px-2 py-0.5 text-[11px] font-semibold text-sky-300">
                                {t('status.learning')}
                              </span>
                            ) : null}
                          </span>
                          {/*
                            Раскрытие через grid-rows 0fr → 1fr: высота анимируется
                            без рывков и без измерения DOM.
                          */}
                          <span
                            aria-hidden={!isOpen}
                            className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${
                              isOpen
                                ? 'mt-2 grid-rows-[1fr] opacity-100'
                                : 'grid-rows-[0fr] opacity-0'
                            }`}
                          >
                            <span className="min-h-0 overflow-hidden">
                              <span className="block text-sm font-medium text-slate-200">
                                {item.translation}
                              </span>
                              {item.example ? (
                                <span className="mt-1 block text-xs italic leading-relaxed text-slate-400">
                                  {item.example}
                                </span>
                              ) : null}
                            </span>
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDelete(item)}
                          aria-label={`${t('delete')}: ${item.word}`}
                          title={t('delete')}
                          className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-400 transition hover:border-rose-400/40 hover:bg-rose-400/10 hover:text-rose-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/60"
                        >
                          <TrashIcon />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </>
        ) : null}

        {view === 'setup' ? (
          <div className="panel mt-6 p-6 sm:p-8">
            <h2 className="text-2xl font-bold text-white">{t('setupTitle')}</h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">{t('setupHint')}</p>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => startTraining('10')}
                className="rounded-2xl border border-white/10 bg-white/5 p-5 text-left transition hover:-translate-y-0.5 hover:border-blue-400/40 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
              >
                <span className="block text-2xl font-bold text-white">10:00</span>
                <span className="mt-1 block text-sm font-semibold text-blue-200">{t('minutes10')}</span>
              </button>
              <button
                type="button"
                onClick={() => startTraining('all')}
                className="rounded-2xl border border-white/10 bg-white/5 p-5 text-left transition hover:-translate-y-0.5 hover:border-blue-400/40 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
              >
                <span className="block text-2xl font-bold text-white">
                  {formatTime(allSeconds)}
                </span>
                <span className="mt-1 block text-sm font-semibold text-blue-200">
                  {t('allWords')} · {t('estimated', { minutes: Math.ceil(allSeconds / 60) })}
                </span>
              </button>
            </div>
            <button type="button" onClick={() => setView('list')} className={`mt-5 ${SECONDARY}`}>
              {t('cancel')}
            </button>
          </div>
        ) : null}

        {view === 'train' && current ? (
          <div className="panel mt-6 overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-3 sm:px-6">
              <div className="flex items-center gap-3">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-blue-200/60">
                  {t('progressLabel')}
                </span>
                <span className="text-sm font-semibold text-white">
                  {step + 1} / {queue.length}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  role="timer"
                  aria-live="off"
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-semibold tabular-nums ${
                    remaining <= 60
                      ? 'border-amber-400/40 bg-amber-400/10 text-amber-200'
                      : 'border-white/10 bg-white/5 text-slate-200'
                  }`}
                >
                  <span aria-hidden="true">⏱</span>
                  {formatTime(remaining)}
                </span>
                <button
                  type="button"
                  onClick={() => setView('list')}
                  className="inline-flex min-h-[36px] items-center rounded-lg px-2 text-sm font-semibold text-blue-200 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                >
                  {t('exit')}
                </button>
              </div>
            </div>

            <div className="p-5 sm:p-6">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-200/60">
                {t('question')}
              </p>
              <h2 className="mt-1 break-words text-3xl font-bold text-white">{current.word}</h2>

              <div className="mt-5 space-y-3">
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {t('translation')}
                  </span>
                  <input
                    value={translation}
                    onChange={(event) => setTranslation(event.target.value)}
                    placeholder={t('translationPlaceholder')}
                    disabled={Boolean(check)}
                    className="field mt-1.5"
                    autoComplete="off"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {t('sentence')}
                  </span>
                  <textarea
                    value={sentence}
                    onChange={(event) => setSentence(event.target.value)}
                    placeholder={t('sentencePlaceholder')}
                    disabled={Boolean(check)}
                    rows={3}
                    className="field mt-1.5 min-h-[92px] resize-y py-3"
                  />
                </label>
              </div>

              {trainError ? (
                <p role="alert" className="mt-3 text-sm text-rose-300">
                  {trainError}
                </p>
              ) : null}

              {!check ? (
                <button
                  type="button"
                  onClick={() => void handleCheck()}
                  disabled={checking || !translation.trim()}
                  className={`mt-5 ${PRIMARY}`}
                >
                  {checking ? t('checking') : t('check')}
                </button>
              ) : (
                <div className="mt-5 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      {t('score')}
                    </span>
                    <span
                      className={`inline-flex items-center rounded-full border px-3 py-1 text-lg font-bold tabular-nums ${scoreBadge(
                        clampScore(check.score),
                      )}`}
                    >
                      {clampScore(check.score)}
                    </span>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    <span
                      className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                        check.translation_ok
                          ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300'
                          : 'border-amber-400/25 bg-amber-400/10 text-amber-200'
                      }`}
                    >
                      {check.translation_ok ? t('translationOk') : t('translationWrong')}
                    </span>
                    <span
                      className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                        check.sentence_ok
                          ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300'
                          : 'border-amber-400/25 bg-amber-400/10 text-amber-200'
                      }`}
                    >
                      {check.sentence_ok ? t('sentenceOk') : t('sentenceWrong')}
                    </span>
                  </div>

                  {check.feedback ? (
                    <p role="status" className="mt-3 text-sm leading-relaxed text-slate-200">
                      {check.feedback}
                    </p>
                  ) : null}

                  {check.improved ? (
                    <div className="mt-3 rounded-xl border border-emerald-400/25 bg-emerald-400/10 p-3">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-200/80">
                        {t('improved')}
                      </p>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-emerald-100">
                        {check.improved}
                      </p>
                    </div>
                  ) : null}

                  <p className="mt-3 text-xs leading-relaxed text-slate-400">
                    {t('correctTranslation')}:{' '}
                    <span className="font-semibold text-emerald-300">{current.translation}</span>
                  </p>

                  <button type="button" onClick={handleNext} className={`mt-4 ${PRIMARY}`}>
                    {step + 1 < queue.length ? t('next') : t('finish')}
                  </button>
                </div>
              )}
            </div>
          </div>
        ) : null}

        {view === 'result' && result ? (
          <div className="panel mt-6 p-6 sm:p-8">
            <div
              aria-hidden="true"
              className={`mb-4 flex h-14 w-14 items-center justify-center rounded-2xl text-2xl text-white ${
                result.reason === 'time'
                  ? 'bg-gradient-to-br from-amber-500 to-rose-500'
                  : 'bg-gradient-to-br from-blue-500 to-sky-400'
              }`}
            >
              {result.reason === 'time' ? '⏰' : '🎉'}
            </div>
            <h2 className="text-2xl font-bold text-white">
              {result.reason === 'time' ? t('timeUp') : t('resultTitle')}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              {result.reason === 'time' ? t('timeUpHint') : t('resultHint')}
            </p>

            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="panel-muted p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  {t('resultWords')}
                </p>
                <p className="mt-1 text-2xl font-bold text-white">{result.items.length}</p>
              </div>
              <div className="panel-muted p-4">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  {t('resultAvg')}
                </p>
                <p className="mt-1 text-2xl font-bold text-sky-300">{averageScore}</p>
              </div>
            </div>

            {result.items.length > 0 ? (
              <ul className="mt-5 space-y-2">
                {result.items.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5"
                  >
                    <span className="min-w-0 truncate text-sm font-medium text-slate-200">
                      {item.word}
                    </span>
                    <span
                      className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold tabular-nums ${scoreBadge(
                        item.score,
                      )}`}
                    >
                      {item.score}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="mt-6 flex flex-wrap gap-3">
              <button type="button" onClick={resetTraining} className={PRIMARY}>
                {t('repeat')}
              </button>
              <button type="button" onClick={() => setView('list')} className={SECONDARY}>
                {t('toList')}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}
