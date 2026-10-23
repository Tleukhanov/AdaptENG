'use client';

import { useTranslations } from 'next-intl';
import type { PronunciationAssessment, PronunciationPhoneme } from '@/lib/api';

type Props = {
  assessment?: PronunciationAssessment | null;
  /** Мягкий текст вместо оценки: сервис недоступен, звук не разобрали и т.п. */
  notice?: string | null;
  className?: string;
};

/** 0–100, безопасно к undefined/NaN из внешнего API. */
function clampScore(value: number | undefined | null): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

/** Цвет оценки: зелёный — уверенно, синий — нормально, янтарный — слабое место. */
function scoreTone(score: number): string {
  if (score >= 80) return 'text-emerald-300';
  if (score >= 60) return 'text-sky-300';
  return 'text-amber-300';
}

/** Подсветка слова: ниже 60 — янтарный, ниже 40 — красный. */
function wordTone(score: number): string {
  if (score >= 60) return 'border-white/10 bg-white/[0.06] text-slate-200';
  if (score >= 40) return 'border-amber-300/40 bg-amber-400/15 text-amber-100';
  return 'border-red-400/40 bg-red-500/20 text-red-100';
}

function phonemeLabel(item: PronunciationPhoneme): string {
  return (item.phoneme ?? item.symbol ?? '').trim();
}

/** Точность фонемы, если провайдер её прислал (иначе показываем без числа). */
function phonemeAccuracy(item: PronunciationPhoneme): number | null {
  const raw = typeof item.accuracy === 'number' ? item.accuracy : item.score;
  if (typeof raw !== 'number' || !Number.isFinite(raw)) {
    return null;
  }
  return clampScore(raw);
}

/** Топ-5 самых проблемных фонем: по возрастанию точности, без известной — в конце. */
function worstPhonemes(phonemes: PronunciationPhoneme[]): PronunciationPhoneme[] {
  const usable = phonemes.filter((item) => phonemeLabel(item) !== '');
  return [...usable]
    .sort((left, right) => {
      const leftScore = phonemeAccuracy(left);
      const rightScore = phonemeAccuracy(right);
      if (leftScore === null && rightScore === null) return 0;
      if (leftScore === null) return 1;
      if (rightScore === null) return -1;
      return leftScore - rightScore;
    })
    .slice(0, 5);
}

/**
 * Оценка произношения после голосового ответа: крупная точность, мелкие
 * беглость/полнота, слова с подсветкой ошибок и топ проблемных фонем.
 * Всё мягкое: при недоступности сервиса карточка показывает текст, а урок
 * продолжается как обычно.
 */
export default function PronunciationCard({ assessment, notice, className }: Props) {
  const t = useTranslations('pronunciation');

  if (!assessment) {
    if (!notice) {
      return null;
    }
    return (
      <section
        aria-label={t('title')}
        className={`rounded-2xl border border-white/10 bg-white/[0.04] px-3.5 py-3 ${className ?? ''}`}
      >
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-blue-200/70">
          {t('title')}
        </h3>
        <p role="status" className="mt-1.5 text-xs leading-relaxed text-slate-300">
          {notice}
        </p>
      </section>
    );
  }

  const accuracy = clampScore(assessment.accuracy);
  const fluency = clampScore(assessment.fluency);
  const completeness = clampScore(assessment.completeness);
  const words = Array.isArray(assessment.words) ? assessment.words : [];
  const phonemes = Array.isArray(assessment.phonemes) ? assessment.phonemes : [];
  const problems = worstPhonemes(phonemes);
  const rough = assessment.provider === 'words';

  return (
    <section
      aria-label={t('title')}
      className={`rounded-2xl border border-white/10 bg-white/[0.04] px-3.5 py-3.5 ${className ?? ''}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-blue-200/70">
          {t('title')}
        </h3>
        {rough ? (
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-slate-300">
            {t('rough')}
          </span>
        ) : null}
      </div>

      <div className="mt-2 flex items-end justify-between gap-4">
        <p className="flex items-baseline gap-1" aria-live="polite">
          <span className={`text-4xl font-bold leading-none ${scoreTone(accuracy)}`}>
            {accuracy}
          </span>
          <span className="text-xs text-slate-400">/ 100</span>
          <span className="sr-only">{t('accuracy')}</span>
        </p>
        <dl className="flex shrink-0 gap-3 text-right">
          <div>
            <dt className="text-[10px] uppercase tracking-wide text-slate-400">
              {t('fluency')}
            </dt>
            <dd className={`text-sm font-semibold ${scoreTone(fluency)}`}>{fluency}</dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-wide text-slate-400">
              {t('completeness')}
            </dt>
            <dd className={`text-sm font-semibold ${scoreTone(completeness)}`}>
              {completeness}
            </dd>
          </div>
        </dl>
      </div>

      {assessment.transcript ? (
        <p className="mt-2 text-xs leading-relaxed text-slate-300">
          <span className="text-slate-400">{t('transcript')}: </span>
          {assessment.transcript}
        </p>
      ) : null}

      {words.length > 0 ? (
        <div className="mt-3">
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            {t('words')}
          </h4>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {words.map((item, index) => {
              const score = clampScore(item.accuracy);
              return (
                <li
                  key={`${item.word}-${index}`}
                  className={`inline-flex items-baseline gap-1.5 rounded-lg border px-2 py-1 text-xs ${wordTone(score)}`}
                >
                  <span className="font-medium">{item.word}</span>
                  <span className="text-[10px] opacity-80">{score}</span>
                  <span className="sr-only">
                    {t('wordScore', { word: item.word, score })}
                    {item.error_type ? `, ${item.error_type}` : ''}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {problems.length > 0 ? (
        <div className="mt-3">
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            {t('phonemes')}
          </h4>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {problems.map((item, index) => {
              const score = phonemeAccuracy(item);
              return (
                <li
                  key={`${phonemeLabel(item)}-${index}`}
                  className="inline-flex items-baseline gap-1.5 rounded-lg border border-amber-300/25 bg-amber-400/10 px-2 py-1 text-xs text-amber-100"
                >
                  <span className="font-mono font-medium">{phonemeLabel(item)}</span>
                  {score !== null ? (
                    <span className="text-[10px] opacity-80">{score}%</span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {notice ? (
        <p role="status" className="mt-2 text-[11px] leading-relaxed text-slate-400">
          {notice}
        </p>
      ) : null}
    </section>
  );
}
