'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  errorMessage,
  finishDiagnostic,
  getProfile,
  startDiagnostic,
  updateProfile,
  type DiagnosticResult,
  type DiagnosticTask,
} from '@/lib/api';
import type { Locale } from '@/lib/i18n';
import { useSession } from '@/lib/session';

type Stage =
  | 'q1'
  | 'q2'
  | 'q3'
  | 'q4'
  | 'q5'
  | 'test-intro'
  | 'test-answer'
  | 'test-result'
  | 'summary';

const STAGES: Stage[] = ['q1', 'q2', 'q3', 'q4', 'q5', 'summary'];

type Option = { id: string; ru: string; en: string };

const GOALS: Option[] = [
  { id: 'work', ru: 'Работа и карьера', en: 'Work and career' },
  { id: 'travel', ru: 'Путешествия', en: 'Travel' },
  { id: 'exam', ru: 'Экзамен IELTS/TOEFL', en: 'IELTS/TOEFL exam' },
  { id: 'media', ru: 'Сериалы, музыка, игры', en: 'Shows, music, games' },
  { id: 'move', ru: 'Переезд за границу', en: 'Moving abroad' },
];

const HOURS: Option[] = [
  { id: '1-2', ru: '1–2 часа', en: '1–2 hours' },
  { id: '3-5', ru: '3–5 часов', en: '3–5 hours' },
  { id: '5-10', ru: '5–10 часов', en: '5–10 hours' },
  { id: '10+', ru: 'Больше 10', en: 'More than 10' },
];

const INTERESTS: Option[] = [
  { id: 'music', ru: 'Музыка', en: 'Music' },
  { id: 'travel', ru: 'Путешествия', en: 'Travel' },
  { id: 'technology', ru: 'Технологии', en: 'Technology' },
  { id: 'sport', ru: 'Спорт', en: 'Sport' },
  { id: 'cooking', ru: 'Кулинария', en: 'Cooking' },
  { id: 'cinema', ru: 'Кино', en: 'Cinema' },
  { id: 'business', ru: 'Бизнес', en: 'Business' },
  { id: 'science', ru: 'Наука', en: 'Science' },
];

const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1'];

const FORMATS: Option[] = [
  { id: 'voice', ru: 'Говорить голосом', en: 'Speak out loud' },
  { id: 'text', ru: 'Писать текстом', en: 'Write text' },
];

const LEVEL_LABEL: Record<string, string> = {
  A1: 'Новичок',
  A2: 'Элементарный',
  B1: 'Средний',
  B2: 'Выше среднего',
  C1: 'Продвинутый',
};

const FOCUS_RING =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]';

export default function OnboardingPage() {
  const router = useRouter();
  const locale = useLocale() as Locale;
  const t = useTranslations('onboarding');
  const ru = locale !== 'en';
  const pick = (option: Option) => (ru ? option.ru : option.en);

  const [stage, setStage] = useState<Stage>('q1');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [goal, setGoal] = useState<string | null>(null);
  const [customGoal, setCustomGoal] = useState('');
  const [hours, setHours] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [interests, setInterests] = useState<string[]>([]);
  const [format, setFormat] = useState<string | null>(null);

  const [tasks, setTasks] = useState<DiagnosticTask[]>([]);
  const [taskIndex, setTaskIndex] = useState(0);
  const [answers, setAnswers] = useState<string[]>([]);
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [testBusy, setTestBusy] = useState(false);
  const { user, loading: sessionLoading } = useSession();

  const stepNumber = useMemo(() => {
    const index = STAGES.indexOf(stage as Stage);
    return index >= 0 ? index + 1 : 1;
  }, [stage]);

  useEffect(() => {
    if (sessionLoading) {
      return;
    }
    if (!user) {
      router.replace('/login');
      return;
    }
    let active = true;
    const force =
      typeof window !== 'undefined' &&
      new URLSearchParams(window.location.search).get('force') === '1';
    (async () => {
      try {
        const profile = await getProfile();
        if (!active) return;
        if (profile.has_profile && !force) {
          router.replace('/menu');
          return;
        }
        if (force && profile) {
          // предзаполнение: онбординг работает как редактор профиля
          if (profile.level) {
            setLevel(profile.level);
          }
          if (profile.interests) {
            setInterests(
              profile.interests.filter((id) => INTERESTS.some((item) => item.id === id)),
            );
          }
          if (profile.preferred_format) {
            setFormat(profile.preferred_format);
          }
          if (profile.goal) {
            setGoal('other');
            setCustomGoal(profile.goal);
          }
          const hoursMatch = profile.notes.match(/1.2|3.5|5.10|10\+|\d+[-+]\d*\+?/);
          if (hoursMatch) {
            const found = HOURS.find((item) => item.id === hoursMatch[0]);
            if (found) {
              setHours(found.id);
            }
          }
        }
      } catch {
        // профиль недоступен — идём по онбордингу дальше
      }
      if (active) {
        setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const goalText = useMemo(() => {
    if (goal === 'other') {
      return customGoal.trim();
    }
    const found = GOALS.find((item) => item.id === goal);
    return found ? pick(found) : '';
  }, [goal, customGoal, ru]);

  const hoursText = useMemo(() => {
    const found = HOURS.find((item) => item.id === hours);
    return found ? pick(found) : '';
  }, [hours, ru]);

  async function runTest() {
    setTestBusy(true);
    setError(null);
    try {
      const res = await startDiagnostic();
      if (!res.tasks || res.tasks.length === 0) {
        setError(t('testEmpty'));
        return;
      }
      setTasks(res.tasks);
      setAnswers([]);
      setTaskIndex(0);
      setAnswer('');
      setStage('test-answer');
    } catch {
      setError(t('testError'));
    } finally {
      setTestBusy(false);
    }
  }

  async function submitAnswer() {
    const filled = answer.trim();
    if (!filled) {
      return;
    }
    const nextAnswers = [...answers, filled];
    setAnswers(nextAnswers);
    setAnswer('');
    if (taskIndex + 1 >= tasks.length) {
      setTestBusy(true);
      try {
        const res = await finishDiagnostic(nextAnswers, tasks);
        setResult(res);
        setLevel(res.level);
        setStage('test-result');
      } catch (e) {
        setError(errorMessage(e, t('testError')));
      } finally {
        setTestBusy(false);
      }
      return;
    }
    setTaskIndex((i) => i + 1);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await updateProfile({
        goal: goalText,
        level: level ?? undefined,
        interests,
        preferred_format: format ?? undefined,
        notes: hoursText ? `${t('hoursNote')}: ${hoursText}` : undefined,
      });
      router.replace('/menu');
    } catch (e) {
      setError(errorMessage(e, t('saveError')));
      setSaving(false);
    }
  }

  function chip(active: boolean) {
    return `flex min-h-[52px] items-center justify-center rounded-2xl border px-4 py-3 text-sm font-semibold transition ${FOCUS_RING} ${
      active
        ? 'border-blue-400/60 bg-blue-500/15 text-sky-100 shadow-[0_0_0_1px_rgba(96,165,250,0.3),0_18px_40px_-24px_rgba(37,99,235,0.9)]'
        : 'border-white/10 bg-white/[0.04] text-slate-200 hover:border-white/25 hover:bg-white/[0.08] hover:text-white'
    }`;
  }

  function primaryButton(disabled = false) {
    return `inline-flex min-h-[48px] items-center justify-center rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 ${FOCUS_RING} disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-slate-400 disabled:shadow-none`;
  }

  function backButtonClass() {
    return `inline-flex min-h-[44px] items-center rounded-xl px-3 text-sm font-semibold text-slate-300 transition hover:bg-white/5 hover:text-white ${FOCUS_RING}`;
  }

  if (loading) {
    return (
      <main className="page-dark flex min-h-[calc(100vh-4rem)] items-center justify-center px-4">
        <p role="status" className="text-sm font-medium text-slate-400">
          ...
        </p>
      </main>
    );
  }

  return (
    <main className="page-dark relative isolate min-h-[calc(100vh-4rem)] overflow-hidden px-4 py-10">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_50%_-12%,#17386b_0%,transparent_72%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 right-[-10%] h-[380px] w-[380px] rounded-full bg-blue-500/10 blur-3xl"
      />

      <div className="relative mx-auto w-full max-w-2xl">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">
            {t('step', { current: stepNumber, total: STAGES.length })}
          </p>
          <div
            role="progressbar"
            aria-valuemin={1}
            aria-valuemax={STAGES.length}
            aria-valuenow={stepNumber}
            className="h-1.5 w-32 overflow-hidden rounded-full bg-white/10"
          >
            <div
              className="h-full rounded-full bg-gradient-to-r from-blue-500 to-sky-400 transition-all"
              style={{ width: `${(stepNumber / STAGES.length) * 100}%` }}
            />
          </div>
        </div>

        {error ? (
          <p
            role="alert"
            className="mt-6 rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
          >
            {error}
          </p>
        ) : null}

        {stage === 'q1' && (
          <section className="panel mt-6 p-6">
            <h1 className="text-2xl font-bold text-white">{t('goalTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('goalHint')}</p>
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              {GOALS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={goal === item.id}
                  onClick={() => setGoal(item.id)}
                  className={chip(goal === item.id)}
                >
                  {pick(item)}
                </button>
              ))}
              <button
                type="button"
                aria-pressed={goal === 'other'}
                onClick={() => setGoal('other')}
                className={chip(goal === 'other')}
              >
                {t('goalOther')}
              </button>
            </div>
            {goal === 'other' ? (
              <input
                value={customGoal}
                onChange={(event) => setCustomGoal(event.target.value)}
                placeholder={t('goalOtherPlaceholder')}
                className="field mt-3"
              />
            ) : null}
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                disabled={!goalText}
                onClick={() => setStage('q2')}
                className={primaryButton(!goalText)}
              >
                {t('next')}
              </button>
            </div>
          </section>
        )}

        {stage === 'q2' && (
          <section className="panel mt-6 p-6">
            <h1 className="text-2xl font-bold text-white">{t('hoursTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('hoursHint')}</p>
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              {HOURS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={hours === item.id}
                  onClick={() => setHours(item.id)}
                  className={chip(hours === item.id)}
                >
                  {pick(item)}
                </button>
              ))}
            </div>
            <div className="mt-6 flex items-center justify-between gap-3">
              <button type="button" onClick={() => setStage('q1')} className={backButtonClass()}>
                {t('back')}
              </button>
              <button
                type="button"
                disabled={!hours}
                onClick={() => setStage('q3')}
                className={primaryButton(!hours)}
              >
                {t('next')}
              </button>
            </div>
          </section>
        )}

        {stage === 'q3' && (
          <section className="panel mt-6 p-6">
            <h1 className="text-2xl font-bold text-white">{t('levelTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('levelHint')}</p>
            <div className="mt-5 grid grid-cols-3 gap-2">
              {LEVELS.map((item) => (
                <button
                  key={item}
                  type="button"
                  aria-pressed={level === item}
                  onClick={() => setLevel(item)}
                  className={`${chip(level === item)} flex-col gap-1`}
                >
                  <span className="text-base font-bold">{item}</span>
                  <span
                    className={`text-xs font-normal ${
                      level === item ? 'text-sky-200' : 'text-slate-400'
                    }`}
                  >
                    {ru ? LEVEL_LABEL[item] : item}
                  </span>
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setStage('test-intro')}
              className={`mt-3 inline-flex min-h-[48px] w-full items-center justify-center rounded-2xl border border-dashed border-blue-400/40 bg-blue-500/10 px-4 py-3 text-sm font-semibold text-sky-200 transition hover:border-blue-300/60 hover:bg-blue-500/15 hover:text-white ${FOCUS_RING}`}
            >
              {t('levelTest')}
            </button>
            <div className="mt-6 flex items-center justify-between gap-3">
              <button type="button" onClick={() => setStage('q2')} className={backButtonClass()}>
                {t('back')}
              </button>
              <button
                type="button"
                disabled={!level}
                onClick={() => setStage('q4')}
                className={primaryButton(!level)}
              >
                {t('next')}
              </button>
            </div>
          </section>
        )}

        {stage === 'test-intro' && (
          <section className="panel mt-6 p-6">
            <h1 className="text-2xl font-bold text-white">{t('testTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('testIntro')}</p>
            <ul className="mt-4 space-y-2 text-sm text-slate-300">
              <li>· {t('testPoint1')}</li>
              <li>· {t('testPoint2')}</li>
              <li>· {t('testPoint3')}</li>
            </ul>
            <div className="mt-6 flex items-center justify-between gap-3">
              <button type="button" onClick={() => setStage('q3')} className={backButtonClass()}>
                {t('back')}
              </button>
              <button
                type="button"
                disabled={testBusy}
                onClick={runTest}
                className={primaryButton(testBusy)}
              >
                {testBusy ? t('testPreparing') : t('testStart')}
              </button>
            </div>
          </section>
        )}

        {stage === 'test-answer' && (
          <section className="panel mt-6 p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">
              {t('taskOf', { current: taskIndex + 1, total: tasks.length })}
            </p>
            <h1 className="mt-3 text-xl font-bold text-white">{tasks[taskIndex]?.text}</h1>
            <textarea
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              rows={4}
              placeholder={t('answerPlaceholder')}
              className="field mt-4"
            />
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                disabled={!answer.trim() || testBusy}
                onClick={submitAnswer}
                className={primaryButton(!answer.trim() || testBusy)}
              >
                {taskIndex + 1 >= tasks.length ? t('testFinish') : t('next')}
              </button>
            </div>
          </section>
        )}

        {stage === 'test-result' && result && (
          <section className="panel mt-6 border-emerald-400/25 bg-emerald-500/[0.07] p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">
              {t('resultTitle')}
            </p>
            <h1 className="mt-2 text-4xl font-bold text-white">{result.level}</h1>
            <p className="mt-3 text-sm text-slate-200">{result.explanation_ru}</p>
            {result.recommendation ? (
              <p className="mt-2 text-sm font-semibold text-slate-100">{result.recommendation}</p>
            ) : null}
            {result.weaknesses.length > 0 ? (
              <p className="mt-2 text-xs text-slate-400">
                {t('resultWeak')}: {result.weaknesses.join(', ')}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end">
              <button type="button" onClick={() => setStage('q4')} className={primaryButton()}>
                {t('next')}
              </button>
            </div>
          </section>
        )}

        {stage === 'q4' && (
          <section className="panel mt-6 p-6">
            <h1 className="text-2xl font-bold text-white">{t('interestsTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('interestsHint')}</p>
            <div className="mt-5 flex flex-wrap gap-2">
              {INTERESTS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={interests.includes(item.id)}
                  onClick={() =>
                    setInterests((current) =>
                      current.includes(item.id)
                        ? current.filter((value) => value !== item.id)
                        : [...current, item.id],
                    )
                  }
                  className={chip(interests.includes(item.id))}
                >
                  {pick(item)}
                </button>
              ))}
            </div>
            <div className="mt-6 flex items-center justify-between gap-3">
              <button type="button" onClick={() => setStage('q3')} className={backButtonClass()}>
                {t('back')}
              </button>
              <button type="button" onClick={() => setStage('q5')} className={primaryButton()}>
                {t('next')}
              </button>
            </div>
          </section>
        )}

        {stage === 'q5' && (
          <section className="panel mt-6 p-6">
            <h1 className="text-2xl font-bold text-white">{t('formatTitle')}</h1>
            <p className="mt-2 text-sm text-slate-300">{t('formatHint')}</p>
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              {FORMATS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={format === item.id}
                  onClick={() => setFormat(item.id)}
                  className={chip(format === item.id)}
                >
                  {pick(item)}
                </button>
              ))}
            </div>
            <div className="mt-6 flex items-center justify-between gap-3">
              <button type="button" onClick={() => setStage('q4')} className={backButtonClass()}>
                {t('back')}
              </button>
              <button
                type="button"
                disabled={!format}
                onClick={() => setStage('summary')}
                className={primaryButton(!format)}
              >
                {t('next')}
              </button>
            </div>
          </section>
        )}

        {stage === 'summary' && (
          <section className="panel mt-6 p-6">
            <h1 className="text-2xl font-bold text-white">{t('summaryTitle')}</h1>
            <dl className="mt-5 space-y-3 text-sm">
              <div className="flex justify-between gap-4 border-b border-white/10 pb-3">
                <dt className="text-slate-400">{t('goalTitle')}</dt>
                <dd className="text-right font-semibold text-white">{goalText || '—'}</dd>
              </div>
              <div className="flex justify-between gap-4 border-b border-white/10 pb-3">
                <dt className="text-slate-400">{t('hoursTitle')}</dt>
                <dd className="text-right font-semibold text-white">{hoursText || '—'}</dd>
              </div>
              <div className="flex justify-between gap-4 border-b border-white/10 pb-3">
                <dt className="text-slate-400">{t('levelTitle')}</dt>
                <dd className="text-right font-semibold text-white">{level ?? '—'}</dd>
              </div>
              <div className="flex justify-between gap-4 border-b border-white/10 pb-3">
                <dt className="text-slate-400">{t('interestsTitle')}</dt>
                <dd className="text-right font-semibold text-white">
                  {interests.length > 0
                    ? interests
                        .map((id) => INTERESTS.find((item) => item.id === id))
                        .filter((item): item is Option => Boolean(item))
                        .map(pick)
                        .join(', ')
                    : '—'}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-400">{t('formatTitle')}</dt>
                <dd className="text-right font-semibold text-white">
                  {FORMATS.find((item) => item.id === format)
                    ? pick(FORMATS.find((item) => item.id === format)!)
                    : '—'}
                </dd>
              </div>
            </dl>
            <div className="mt-6 flex items-center justify-between gap-3">
              <button type="button" onClick={() => setStage('q5')} className={backButtonClass()}>
                {t('back')}
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={save}
                className={primaryButton(saving)}
              >
                {saving ? t('saving') : t('save')}
              </button>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
