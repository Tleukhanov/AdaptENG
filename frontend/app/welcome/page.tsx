'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import {
  errorMessage,
  getGuestProfile,
  saveGuestProfile,
  type GuestGoal,
  type GuestLevel,
  type GuestMinutes,
} from '@/lib/api';
import { useSession } from '@/lib/session';

const STEP_COUNT = 3;

const GOALS: GuestGoal[] = ['exam', 'communication', 'work', 'general'];
const MINUTES: GuestMinutes[] = [10, 20, 30, 60];
const LEVELS: GuestLevel[] = ['A1', 'A2', 'B1', 'B2', 'C1'];

/**
 * Гостевой онбординг до регистрации: три вопроса (цель, минуты в день,
 * уровень). Ответы уходят в `POST /api/guest/profile` и живут в HttpOnly-cookie,
 * поэтому при повторном заходе профиль читается только через GET. При
 * регистрации сервер переносит их в аккаунт — здесь про это знать не нужно.
 */
export default function WelcomePage() {
  const router = useRouter();
  const t = useTranslations('welcome');
  const { user, loading: sessionLoading } = useSession();

  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState<GuestGoal | null>(null);
  const [minutes, setMinutes] = useState<GuestMinutes | null>(null);
  const [level, setLevel] = useState<GuestLevel | null>(null);
  const [hasProfile, setHasProfile] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedRef = useRef(false);

  const goalLabels: Record<GuestGoal, string> = {
    exam: t('goalExam'),
    communication: t('goalCommunication'),
    work: t('goalWork'),
    general: t('goalGeneral'),
  };

  const minutesLabels: Record<GuestMinutes, string> = {
    10: t('minutes10'),
    20: t('minutes20'),
    30: t('minutes30'),
    60: t('minutes60'),
  };

  const levelLabels: Record<GuestLevel, string> = {
    A1: t('levelA1'),
    A2: t('levelA2'),
    B1: t('levelB1'),
    B2: t('levelB2'),
    C1: t('levelC1'),
  };

  // Залогиненному пользователю онбординг не нужен.
  useEffect(() => {
    if (sessionLoading) {
      return;
    }
    if (user) {
      router.replace('/lesson/0');
      return;
    }
    if (fetchedRef.current) {
      return;
    }
    fetchedRef.current = true;

    let active = true;
    (async () => {
      try {
        const profile = await getGuestProfile();
        if (active && profile) {
          setGoal(profile.goal);
          setMinutes(profile.minutes);
          setLevel(profile.level);
          setHasProfile(true);
        }
      } catch {
        // Cookie недоступна — не мешаем пройти онбординг с чистого листа.
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [sessionLoading, user, router]);

  const currentValue = step === 0 ? goal : step === 1 ? minutes : level;

  function chooseGoal(value: GuestGoal) {
    setGoal(value);
    setError(null);
    setStep(1);
  }

  function chooseMinutes(value: GuestMinutes) {
    setMinutes(value);
    setError(null);
    setStep(2);
  }

  function chooseLevel(value: GuestLevel) {
    setLevel(value);
    setError(null);
  }

  function goBack() {
    setError(null);
    setStep((current) => Math.max(0, current - 1));
  }

  function goNext() {
    setError(null);
    setStep((current) => Math.min(STEP_COUNT - 1, current + 1));
  }

  async function start() {
    if (!goal || !minutes || !level || saving) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await saveGuestProfile({ goal, minutes, level });
      router.push('/lesson/0');
    } catch (e) {
      setError(errorMessage(e, t('saveError')));
      setSaving(false);
    }
  }

  if (loading || sessionLoading) {
    return (
      <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-[#0b1220] px-4">
        <p role="status" className="text-sm font-medium text-blue-200/80">
          {t('loading')}
        </p>
      </main>
    );
  }

  return (
    <main className="relative isolate min-h-[calc(100vh-4rem)] overflow-hidden bg-[#0b1220] px-4 py-10 text-slate-900 sm:py-16">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_50%_-12%,#17386b_0%,transparent_72%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 right-[-10%] h-[380px] w-[380px] rounded-full bg-blue-500/10 blur-3xl"
      />

      <div className="relative mx-auto w-full max-w-2xl">
        <header className="text-center">
          <span className="inline-flex items-center rounded-full border border-blue-400/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold tracking-wide text-blue-200">
            {t('badge')}
          </span>
          <h1 className="mt-5 text-3xl font-bold leading-tight text-white sm:text-4xl">
            {t('title')}
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-blue-100/70 sm:text-base">
            {t('subtitle')}
          </p>
        </header>

        <div className="mt-8 rounded-[28px] bg-white p-5 shadow-[0_40px_90px_-30px_rgba(37,99,235,0.55)] ring-1 ring-white/20 sm:p-8">
          {hasProfile ? (
            <div className="mb-5 flex flex-col gap-3 rounded-2xl border border-blue-200 bg-blue-50/80 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-blue-950">{t('resumeTitle')}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-blue-900/70">
                  {t('resumeHint')}
                </p>
              </div>
              <button
                type="button"
                onClick={() => router.push('/lesson/0')}
                className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-xl border border-blue-300 bg-white px-4 py-2 text-sm font-semibold text-blue-700 transition hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
              >
                {t('continue')}
              </button>
            </div>
          ) : null}

          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">
              {t('progress', { current: step + 1, total: STEP_COUNT })}
            </p>
            <div
              role="progressbar"
              aria-label={t('progressLabel')}
              aria-valuemin={1}
              aria-valuemax={STEP_COUNT}
              aria-valuenow={step + 1}
              aria-valuetext={t('progress', { current: step + 1, total: STEP_COUNT })}
              className="flex w-28 gap-1.5 sm:w-36"
            >
              {Array.from({ length: STEP_COUNT }).map((_, index) => (
                <span
                  key={index}
                  className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${
                    index <= step ? 'bg-blue-500' : 'bg-slate-200'
                  }`}
                />
              ))}
            </div>
          </div>

          <section aria-labelledby="welcome-step-title" className="mt-6">
            <h2
              id="welcome-step-title"
              className="text-xl font-bold leading-snug text-slate-900 sm:text-2xl"
            >
              {step === 0 ? t('goalTitle') : step === 1 ? t('minutesTitle') : t('levelTitle')}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-500">
              {step === 0 ? t('goalHint') : step === 1 ? t('minutesHint') : t('levelHint')}
            </p>

            {step === 0 ? (
              <div className="mt-5 grid gap-2.5 sm:grid-cols-2">
                {GOALS.map((item) => {
                  const selected = goal === item;
                  return (
                    <button
                      key={item}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => chooseGoal(item)}
                      className={optionClass(selected)}
                    >
                      <span>{goalLabels[item]}</span>
                      <Check selected={selected} />
                    </button>
                  );
                })}
              </div>
            ) : null}

            {step === 1 ? (
              <div className="mt-5 grid gap-2.5 sm:grid-cols-2">
                {MINUTES.map((item) => {
                  const selected = minutes === item;
                  return (
                    <button
                      key={item}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => chooseMinutes(item)}
                      className={optionClass(selected)}
                    >
                      <span>{minutesLabels[item]}</span>
                      <Check selected={selected} />
                    </button>
                  );
                })}
              </div>
            ) : null}

            {step === 2 ? (
              <div className="mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                {LEVELS.map((item) => {
                  const selected = level === item;
                  return (
                    <button
                      key={item}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => chooseLevel(item)}
                      className={`flex min-h-[72px] w-full flex-col items-start justify-center gap-0.5 rounded-2xl border px-4 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 ${
                        selected
                          ? 'border-blue-500 bg-blue-50 text-blue-950 shadow-[0_0_0_1px_rgba(59,130,246,0.35),0_18px_35px_-20px_rgba(37,99,235,0.85)]'
                          : 'border-slate-200 bg-white text-slate-700 hover:border-blue-300 hover:bg-slate-50'
                      }`}
                    >
                      <span className="text-base font-bold">{item}</span>
                      <span
                        className={`text-xs font-medium ${
                          selected ? 'text-blue-700' : 'text-slate-500'
                        }`}
                      >
                        {levelLabels[item]}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </section>

          {error ? (
            <p
              role="alert"
              className="mt-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              {error}
            </p>
          ) : null}

          <div
            className={`mt-7 flex items-center gap-3 ${
              step === 0 ? 'justify-end' : 'justify-between'
            }`}
          >
            {step > 0 ? (
              <button
                type="button"
                onClick={goBack}
                className="inline-flex min-h-[48px] items-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
              >
                <span aria-hidden="true">←</span>
                {t('back')}
              </button>
            ) : null}

            {step < STEP_COUNT - 1 ? (
              <button
                type="button"
                disabled={!currentValue}
                onClick={goNext}
                className={primaryClass(!currentValue)}
              >
                {t('next')}
                <span aria-hidden="true">→</span>
              </button>
            ) : (
              <button
                type="button"
                disabled={!currentValue || saving}
                onClick={() => void start()}
                className={primaryClass(!currentValue || saving)}
              >
                {saving ? t('saving') : t('start')}
              </button>
            )}
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-blue-200/50">AdaptENG</p>
      </div>
    </main>
  );
}

function optionClass(selected: boolean): string {
  return `flex min-h-[56px] w-full items-center justify-between gap-3 rounded-2xl border px-4 py-3.5 text-left text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 ${
    selected
      ? 'border-blue-500 bg-blue-50 text-blue-950 shadow-[0_0_0_1px_rgba(59,130,246,0.35),0_18px_35px_-20px_rgba(37,99,235,0.85)]'
      : 'border-slate-200 bg-white text-slate-700 hover:border-blue-300 hover:bg-slate-50'
  }`;
}

function primaryClass(disabled: boolean): string {
  return `inline-flex min-h-[48px] items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:from-blue-500 hover:to-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:from-slate-200 disabled:to-slate-200 disabled:text-slate-400 disabled:shadow-none ${
    disabled ? '' : 'hover:-translate-y-0.5'
  }`;
}

function Check({ selected }: { selected: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] transition ${
        selected
          ? 'border-blue-500 bg-blue-500 text-white'
          : 'border-slate-300 text-transparent'
      }`}
    >
      ✓
    </span>
  );
}
