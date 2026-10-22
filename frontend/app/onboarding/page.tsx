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
    return `rounded-2xl border px-4 py-3 text-sm font-semibold transition ${
      active
        ? 'border-blue-400 bg-blue-50 text-blue-700 shadow-sm'
        : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
    }`;
  }

  function primaryButton(disabled = false) {
    return `inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-blue-500 to-sky-500 px-6 py-3 text-sm font-semibold text-white shadow-sm transition disabled:cursor-not-allowed disabled:opacity-40`;
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-16">
        <p className="text-slate-600">...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-500">
          {t('step', { current: stepNumber, total: STAGES.length })}
        </p>
        <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-sky-500 transition-all"
            style={{ width: `${(stepNumber / STAGES.length) * 100}%` }}
          />
        </div>
      </div>

      {error ? (
        <p className="mt-6 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      {stage === 'q1' && (
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">{t('goalTitle')}</h1>
          <p className="mt-2 text-sm text-slate-600">{t('goalHint')}</p>
          <div className="mt-5 grid gap-2 sm:grid-cols-2">
            {GOALS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setGoal(item.id)}
                className={chip(goal === item.id)}
              >
                {pick(item)}
              </button>
            ))}
            <button
              type="button"
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
              className="mt-3 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-400"
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
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">{t('hoursTitle')}</h1>
          <p className="mt-2 text-sm text-slate-600">{t('hoursHint')}</p>
          <div className="mt-5 grid gap-2 sm:grid-cols-2">
            {HOURS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setHours(item.id)}
                className={chip(hours === item.id)}
              >
                {pick(item)}
              </button>
            ))}
          </div>
          <div className="mt-6 flex justify-between">
            <button type="button" onClick={() => setStage('q1')} className="text-sm font-semibold text-slate-500">
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
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">{t('levelTitle')}</h1>
          <p className="mt-2 text-sm text-slate-600">{t('levelHint')}</p>
          <div className="mt-5 grid grid-cols-3 gap-2">
            {LEVELS.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setLevel(item)}
                className={`${chip(level === item)} flex flex-col items-center gap-1`}
              >
                <span className="text-base font-bold">{item}</span>
                <span className="text-xs font-normal text-slate-500">
                  {ru ? LEVEL_LABEL[item] : item}
                </span>
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setStage('test-intro')}
            className="mt-3 w-full rounded-2xl border border-dashed border-blue-300 bg-blue-50/50 px-4 py-3 text-sm font-semibold text-blue-700"
          >
            {t('levelTest')}
          </button>
          <div className="mt-6 flex justify-between">
            <button type="button" onClick={() => setStage('q2')} className="text-sm font-semibold text-slate-500">
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
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">{t('testTitle')}</h1>
          <p className="mt-2 text-sm text-slate-600">{t('testIntro')}</p>
          <ul className="mt-4 space-y-2 text-sm text-slate-600">
            <li>· {t('testPoint1')}</li>
            <li>· {t('testPoint2')}</li>
            <li>· {t('testPoint3')}</li>
          </ul>
          <div className="mt-6 flex justify-between">
            <button type="button" onClick={() => setStage('q3')} className="text-sm font-semibold text-slate-500">
              {t('back')}
            </button>
            <button type="button" disabled={testBusy} onClick={runTest} className={primaryButton(testBusy)}>
              {testBusy ? t('testPreparing') : t('testStart')}
            </button>
          </div>
        </section>
      )}

      {stage === 'test-answer' && (
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-500">
            {t('taskOf', { current: taskIndex + 1, total: tasks.length })}
          </p>
          <h1 className="mt-3 text-xl font-bold text-slate-900">{tasks[taskIndex]?.text}</h1>
          <textarea
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            rows={4}
            placeholder={t('answerPlaceholder')}
            className="mt-4 w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-400"
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
        <section className="mt-6 rounded-3xl border border-emerald-200 bg-emerald-50/60 p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">{t('resultTitle')}</p>
          <h1 className="mt-2 text-4xl font-bold text-slate-900">{result.level}</h1>
          <p className="mt-3 text-sm text-slate-700">{result.explanation_ru}</p>
          {result.recommendation ? (
            <p className="mt-2 text-sm font-semibold text-slate-700">{result.recommendation}</p>
          ) : null}
          {result.weaknesses.length > 0 ? (
            <p className="mt-2 text-xs text-slate-500">
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
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">{t('interestsTitle')}</h1>
          <p className="mt-2 text-sm text-slate-600">{t('interestsHint')}</p>
          <div className="mt-5 flex flex-wrap gap-2">
            {INTERESTS.map((item) => (
              <button
                key={item.id}
                type="button"
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
          <div className="mt-6 flex justify-between">
            <button type="button" onClick={() => setStage('q3')} className="text-sm font-semibold text-slate-500">
              {t('back')}
            </button>
            <button type="button" onClick={() => setStage('q5')} className={primaryButton()}>
              {t('next')}
            </button>
          </div>
        </section>
      )}

      {stage === 'q5' && (
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">{t('formatTitle')}</h1>
          <p className="mt-2 text-sm text-slate-600">{t('formatHint')}</p>
          <div className="mt-5 grid gap-2 sm:grid-cols-2">
            {FORMATS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setFormat(item.id)}
                className={chip(format === item.id)}
              >
                {pick(item)}
              </button>
            ))}
          </div>
          <div className="mt-6 flex justify-between">
            <button type="button" onClick={() => setStage('q4')} className="text-sm font-semibold text-slate-500">
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
        <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-bold text-slate-900">{t('summaryTitle')}</h1>
          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex justify-between gap-4 border-b border-slate-100 pb-3">
              <dt className="text-slate-500">{t('goalTitle')}</dt>
              <dd className="text-right font-semibold text-slate-900">{goalText || '—'}</dd>
            </div>
            <div className="flex justify-between gap-4 border-b border-slate-100 pb-3">
              <dt className="text-slate-500">{t('hoursTitle')}</dt>
              <dd className="text-right font-semibold text-slate-900">{hoursText || '—'}</dd>
            </div>
            <div className="flex justify-between gap-4 border-b border-slate-100 pb-3">
              <dt className="text-slate-500">{t('levelTitle')}</dt>
              <dd className="text-right font-semibold text-slate-900">{level ?? '—'}</dd>
            </div>
            <div className="flex justify-between gap-4 border-b border-slate-100 pb-3">
              <dt className="text-slate-500">{t('interestsTitle')}</dt>
              <dd className="text-right font-semibold text-slate-900">
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
              <dt className="text-slate-500">{t('formatTitle')}</dt>
              <dd className="text-right font-semibold text-slate-900">
                {FORMATS.find((item) => item.id === format) ? pick(FORMATS.find((item) => item.id === format)!) : '—'}
              </dd>
            </div>
          </dl>
          <div className="mt-6 flex justify-between">
            <button type="button" onClick={() => setStage('q5')} className="text-sm font-semibold text-slate-500">
              {t('back')}
            </button>
            <button type="button" disabled={saving} onClick={save} className={primaryButton(saving)}>
              {saving ? t('saving') : t('save')}
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
