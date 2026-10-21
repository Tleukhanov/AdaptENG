'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  ApiError,
  apiBlob,
  errorMessage,
  finishLesson,
  startLesson,
  transcribeAudio,
} from '@/lib/api';
import { useRecorder } from '@/lib/recorder';
import { useRouter } from 'next/navigation';
import { useSession } from '@/lib/session';
import { apiDeckToLocal, sampleDeck } from '@/lib/deck';
import type { ApiDeck, Deck, DeckStep, DialogueChoice, QuizItem, VocabCard } from '@/lib/deck';
import type { Locale } from '@/lib/i18n';

type Step = DeckStep;

/** Что происходит во время генерации урока (показывается по кругу). */
const GENERATION_TIPS = ['generating.pickTopic', 'generating.words', 'generating.quiz', 'generating.ready'];

type Status = 'loading' | 'cover' | 'slides' | 'cards' | 'quiz' | 'dialogue' | 'finish';

type Flashcards = Record<string, boolean>;

type QuizAnswer = {
  quiz_index: number;
  chosen: number;
  correct: boolean;
};

type DialogueTurn = {
  speaker: 'teacher' | 'student' | string;
  line: string;
};

type FinishResult = {
  score: number;
  xp?: number;
  next_topic?: string | null;
  repeat_words?: string[];
  preset?: string;
};

export default function LessonPage() {
  const locale = useLocale() as Locale;
  const t = useTranslations('lesson');
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();
  const recorder = useRecorder();

  const [status, setStatus] = useState<Status>('loading');
  const [deck, setDeck] = useState<Deck | null>(null);
  const [slideIndex, setSlideIndex] = useState(0);
  const [cardIndex, setCardIndex] = useState(0);
  const [cardFlipped, setCardFlipped] = useState(false);
  const [flashcards, setFlashcards] = useState<Flashcards>({});
  const [quizIndex, setQuizIndex] = useState(0);
  const [quizAnswered, setQuizAnswered] = useState(false);
  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [quizAnswers, setQuizAnswers] = useState<QuizAnswer[]>([]);
  const [dialogueBubbles, setDialogueBubbles] = useState<DialogueTurn[]>([]);
  const [dialogueLine, setDialogueLine] = useState(0);
  const [dialogueTurns, setDialogueTurns] = useState(0);
  const [micError, setMicError] = useState<string | null>(null);
  const [voiceResult, setVoiceResult] = useState<{ transcript?: string; rating?: number; tip?: string } | null>(null);
  const [finish, setFinish] = useState<FinishResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [tipIndex, setTipIndex] = useState(0);
  const [errorKind, setErrorKind] = useState<'quota' | 'retry' | null>(null);
  const [sessionId, setSessionId] = useState<number | undefined>();
  const [demo, setDemo] = useState(false);
  const [starting, setStarting] = useState(false);


  useEffect(() => {
    if (status === 'dialogue' && deck) {
      const lines = deck.dialogue.lines;
      setDialogueTurns(0);
      if (lines.length > 0) {
        setDialogueBubbles([{ speaker: lines[0].speaker, line: lines[0].line }]);
        setDialogueLine(0);
      } else {
        setDialogueBubbles([]);
        setDialogueLine(0);
      }
    }
  }, [deck, status]);

  // Сессия определяется запросом /api/me (токен в HttpOnly-cookie).
  // Экран генерации: показываем, сколько идёт, и подсказываем, что происходит.
  useEffect(() => {
    if (status !== 'loading') {
      setElapsed(0);
      setTipIndex(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    const tips = window.setInterval(() => setTipIndex((i) => (i + 1) % GENERATION_TIPS.length), 3500);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(tips);
    };
  }, [status]);

  useEffect(() => {
    if (sessionLoading) {
      return;
    }
    if (!user) {
      router.replace('/login');
      return;
    }
    setDemo(false);
  }, [sessionLoading, user]);

  async function start() {
    if (starting) {
      return;
    }
    setStarting(true);
    setError(null);
    setStatus('loading');
    try {
      if (!user) {
        router.replace('/login');
        return;
      }
      const topicFromUrl = new URLSearchParams(window.location.search).get('topic') ?? undefined;
      const res = await startLesson(topicFromUrl || undefined);
      const d = res.deck ? apiDeckToLocal(res.deck as ApiDeck) : sampleDeck(locale);
      setDeck(d);
      setSessionId(res.session_id ?? undefined);
      resetSteps();
      setStatus('cover');
    } catch (e) {
      const text = errorMessage(e, t('error.generic'));
      // Дневной лимит → предложить прогресс; очередь/троттлинг → повторить.
      setError(text);
      setErrorKind(/лимит исчерпан|дневной лимит/i.test(text) ? 'quota' : 'retry');
      setStatus('cover');
    } finally {
      setStarting(false);
    }
  }

  function resetSteps() {
    setSlideIndex(0);
    setCardIndex(0);
    setCardFlipped(false);
    setFlashcards({});
    setQuizIndex(0);
    setQuizAnswered(false);
    setSelectedOption(null);
    setQuizAnswers([]);
    setDialogueBubbles([]);
    setDialogueLine(0);
    setDialogueTurns(0);
    setVoiceResult(null);
    recorder.cancel();
    setMicError(null);
    setFinish(null);
  }

  const progressSteps = ['cover', 'slides', 'cards', 'quiz', 'dialogue', 'finish'] as const;
  const currentStepIdx = progressSteps.indexOf(status as (typeof progressSteps)[number]);
  const progress = Math.max(0, currentStepIdx >= 0 ? (currentStepIdx / (progressSteps.length - 1)) * 100 : 0);

  function goNextSlide() {
    if (!deck) {
      return;
    }
    if (slideIndex < deck.slides.length - 1) {
      setSlideIndex((s) => s + 1);
    } else {
      setStatus('cards');
      setCardIndex(0);
      setCardFlipped(false);
    }
  }

  function flipCard() {
    setCardFlipped((f) => !f);
  }

  function markCard(know: boolean) {
    if (!deck) {
      return;
    }
    const word = deck.vocab[cardIndex]?.word;
    if (word) {
      setFlashcards((f) => ({ ...f, [word]: know }));
    }
    setCardFlipped(false);
    if (cardIndex < deck.vocab.length - 1) {
      setCardIndex((i) => i + 1);
    } else {
      setStatus('quiz');
      setQuizIndex(0);
      setQuizAnswered(false);
      setSelectedOption(null);
      setQuizAnswers([]);
    }
  }

  function skipCards() {
    setStatus('quiz');
    setQuizIndex(0);
    setQuizAnswered(false);
    setSelectedOption(null);
    setQuizAnswers([]);
  }

  function selectQuizOption(idx: number) {
    if (!deck || quizAnswered) {
      return;
    }
    const q = deck.quiz[quizIndex];
    const correct = idx === q.correctIndex;
    setSelectedOption(idx);
    setQuizAnswered(true);
    setQuizAnswers((a) => [
      ...a,
      { quiz_index: quizIndex, chosen: idx, correct },
    ]);
  }

  function nextQuiz() {
    if (!deck) {
      return;
    }
    if (quizIndex < deck.quiz.length - 1) {
      setQuizIndex((i) => i + 1);
      setQuizAnswered(false);
      setSelectedOption(null);
    } else {
      setStatus('dialogue');
      setVoiceResult(null);
    }
  }

  function skipQuiz() {
    setStatus('dialogue');
    setVoiceResult(null);
  }

  const MAX_STUDENT_TURNS = 2;

  function pickChoice(choice: DialogueChoice) {
    if (!deck) {
      return;
    }
    const bubbles: DialogueTurn[] = [
      ...dialogueBubbles,
      { speaker: 'student', line: choice.line },
    ];
    const turn = dialogueTurns + 1;
    const n = typeof choice.next === 'number' ? choice.next : -1;
    setDialogueTurns(turn);
    if (n >= 0 && n < deck.dialogue.lines.length) {
      const reply = deck.dialogue.lines[n];
      bubbles.push({ speaker: reply.speaker, line: reply.line });
      setDialogueLine(n);
    } else {
      setDialogueLine(deck.dialogue.lines.length);
    }
    setDialogueBubbles(bubbles);
    setVoiceResult(null);
  }

  const dialogueChoicesVisible =
    dialogueTurns < MAX_STUDENT_TURNS && dialogueLine < (deck?.dialogue.lines.length ?? 0) - 1;
  const dialogueFinished =
    dialogueTurns >= MAX_STUDENT_TURNS || dialogueLine >= (deck?.dialogue.lines.length ?? 0) - 1;
  const lastPartnerLine =
    [...dialogueBubbles].reverse().find((turn) => turn.speaker !== 'student')?.line ?? '';

  function proceedToFinish() {
    finishLessonFlow();
  }

  async function finishLessonFlow() {
    if (!deck) {
      return;
    }
    const total = deck.quiz.length;
    const correctCount = quizAnswers.filter((a) => a.correct).length;
    const score = total === 0 ? 0 : Math.round((correctCount / total) * 100);

    if (!user) {
      router.replace('/login');
      return;
    }

    try {
      const res = await finishLesson({
        score,
        quiz_answers: quizAnswers,
        flashcards,
        session_id: sessionId,
      });
      setFinish({
        score: res.score ?? score,
        xp: res.xp,
        next_topic: res.next_topic,
        repeat_words: res.repeat_words,
        preset: res.preset,
      });
      setStatus('finish');
    } catch (e) {
      const text = errorMessage(e, t('error.generic'));
      setError(text);
      setErrorKind(/лимит исчерпан|дневной лимит/i.test(text) ? 'quota' : 'retry');
      setStatus('cover');
    }
  }

  async function startRecording() {
    setMicError(null);
    setVoiceResult(null);
    const started = await recorder.start();
    if (!started) {
      setMicError(t('dialogue.micUnavailable'));
    }
  }

  async function stopRecording() {
    const blob = await recorder.stop();
    if (!blob) {
      setMicError(t('dialogue.micUnavailable'));
      return;
    }
    try {
      const res = await transcribeAudio(blob, {
        expectedLine: lastPartnerLine || undefined,
        mode: 'lesson',
      });
      setVoiceResult({
        transcript: res.transcript,
        rating: res.rating,
        tip: res.tip,
      });
    } catch (e) {
      setMicError(
        e instanceof ApiError && e.status === 503
          ? t('voice.unavailable')
          : errorMessage(e, t('error.generic')),
      );
    }
  }

  async function speakLine(text: string) {
    try {
      const blob = await apiBlob('/api/chat/tts', {
        method: 'POST',
        body: { text },
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play().catch(() => {});
    } catch {
      // ignore
    }
  }

  const currentCard: VocabCard | null = deck ? deck.vocab[cardIndex] ?? null : null;
  const currentQuiz: QuizItem | null = deck ? deck.quiz[quizIndex] ?? null : null;

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className="flex-1">
          <div className="h-2 rounded-full bg-slate-200">
            <div className="h-2 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500" style={{ width: `${progress}%` }} />
          </div>
          <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{t(`step.${status}`)}</p>
        </div>
        <Link href="/dashboard" className="text-sm font-semibold text-slate-600 hover:text-slate-900">
          {t('exit')}
        </Link>
      </div>

      {error && (
        <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p>{error}</p>
          {errorKind === 'quota' ? (
            <div className="mt-2 flex gap-2">
              <Link href="/progress" className="rounded-lg bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
                {t('error.toProgress')}
              </Link>
            </div>
          ) : (
            <button
              onClick={start}
              disabled={starting}
              className="mt-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm disabled:cursor-not-allowed disabled:opacity-60"
            >
              {starting ? t('generating.working') : t('error.retry')}
            </button>
          )}
        </div>
      )}

      {status === 'loading' && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm sm:p-10">
          <div
            aria-hidden
            className="mx-auto mb-5 flex h-14 w-14 animate-pulse items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl text-white"
          >
            ✨
          </div>
          <h1 className="text-2xl font-bold text-slate-900">{t('generating.title')}</h1>
          <p className="mt-2 text-slate-600" role="status" aria-live="polite">
            {t(GENERATION_TIPS[tipIndex % GENERATION_TIPS.length])}
          </p>

          <div className="mx-auto mt-6 h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-1/3 animate-[loading_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-indigo-500 to-violet-500" />
          </div>

          <p className="mt-4 text-sm text-slate-500">
            {t('generating.elapsed', { seconds: elapsed })}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {elapsed > 20 ? t('generating.slow') : t('generating.hint')}
          </p>

          <button
            onClick={start}
            disabled={starting}
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-6 py-3 text-sm font-semibold text-white shadow-sm disabled:cursor-not-allowed disabled:opacity-60"
          >
            {starting ? t('generating.working') : t('presentation.start')}
          </button>
        </div>
      )}

      {status === 'cover' && !deck && (
        <div className="rounded-3xl border border-slate-200 bg-white p-10 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl text-white">
            🌟
          </div>
          <h1 className="text-2xl font-bold text-slate-900">{t('start')}</h1>
          <p className="mt-2 text-slate-600">{t('generating.hint')}</p>
          <button
            onClick={start}
            disabled={starting}
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-6 py-3 text-sm font-semibold text-white shadow-sm disabled:cursor-not-allowed disabled:opacity-60"
          >
            {starting ? t('generating.working') : t('presentation.start')}
          </button>
        </div>
      )}

      {status === 'cover' && deck && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <div className="mb-6 flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl text-white">
              {deck.cover.emoji}
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">{deck.cover.title}</h1>
              <p className="text-slate-600">{deck.cover.subtitle}</p>
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={() => setStatus('slides')} className="rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
              {t('presentation.start')}
            </button>
            <Link href="/dashboard" className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-700 shadow-sm">
              {t('exit')}
            </Link>
          </div>
        </div>
      )}

      {status === 'slides' && deck && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <div className="mb-6 flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl text-white">
              {deck.slides[slideIndex]?.emoji ?? deck.cover.emoji}
            </div>
            <div>
              <h2 className="text-xl font-bold text-slate-900">{deck.slides[slideIndex]?.headline ?? deck.cover.title}</h2>
              <p className="text-slate-600">{deck.slides[slideIndex]?.body ?? deck.cover.subtitle}</p>
            </div>
          </div>
          <button onClick={goNextSlide} className="rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
            {slideIndex < deck.slides.length - 1 ? t('presentation.next') : t('presentation.start')}
          </button>
        </div>
      )}

      {status === 'cards' && deck && currentCard && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <div className="mb-6 text-center">
            <h2 className="text-2xl font-bold text-slate-900">{currentCard.word}</h2>
            {currentCard.transcription && <p className="text-slate-500">{currentCard.transcription}</p>}
          </div>
          <button onClick={flipCard} className="w-full rounded-2xl border border-slate-200 p-8 text-center shadow-sm transition hover:shadow-md">
            <p className="text-lg text-slate-700">{cardFlipped ? currentCard.translation : currentCard.example}</p>
          </button>
          <div className="mt-6 flex gap-3">
            <button onClick={() => markCard(true)} className="flex-1 rounded-xl bg-emerald-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
              {t('cards.know')}
            </button>
            <button onClick={() => markCard(false)} className="flex-1 rounded-xl bg-amber-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
              {t('cards.repeat')}
            </button>
          </div>
        </div>
      )}

      {status === 'cards' && deck && !currentCard && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <h2 className="text-xl font-bold text-slate-900">{t('step.cards')}</h2>
          <button onClick={skipCards} className="mt-6 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
            {t('presentation.next')}
          </button>
        </div>
      )}

      {status === 'quiz' && deck && currentQuiz && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <h2 className="mb-4 text-xl font-bold text-slate-900">{currentQuiz.question}</h2>
          <div className="space-y-2">
            {currentQuiz.options.map((opt, idx) => {
              const isCorrect = idx === currentQuiz.correctIndex;
              const isSelected = selectedOption === idx;
              let cls = 'w-full rounded-xl border border-slate-200 px-4 py-3 text-left text-sm text-slate-700 shadow-sm';
              if (quizAnswered) {
                if (isCorrect) {
                  cls = 'w-full rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-left text-sm font-semibold text-emerald-700';
                } else if (isSelected) {
                  cls = 'w-full rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-left text-sm font-semibold text-red-700';
                }
              }
              return (
                <button key={idx} onClick={() => selectQuizOption(idx)} disabled={quizAnswered} className={cls}>
                  {opt}
                </button>
              );
            })}
          </div>
          {quizAnswered && (
            <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
              <p>{currentQuiz.explanation_ru ?? currentQuiz.explanation}</p>
            </div>
          )}
          {quizAnswered && (
            <button onClick={nextQuiz} className="mt-4 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
              {t('quiz.next')}
            </button>
          )}
        </div>
      )}

      {status === 'quiz' && deck && !currentQuiz && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <h2 className="text-xl font-bold text-slate-900">{t('step.quiz')}</h2>
          <button onClick={skipQuiz} className="mt-6 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
            {t('presentation.next')}
          </button>
        </div>
      )}

      {status === 'dialogue' && deck && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <h2 className="mb-2 text-xl font-bold text-slate-900">{deck.dialogue.title ?? t('step.dialogue')}</h2>
          <p className="mb-4 text-sm text-slate-600">{deck.dialogue.scene_ru ?? deck.dialogue.scene}</p>
          <div className="space-y-3">
            {dialogueBubbles.map((turn, idx) => (
              <div key={idx} className={`flex ${turn.speaker === 'student' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm shadow-sm ${turn.speaker === 'student' ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white' : 'border border-slate-200 bg-white text-slate-700'}`}>
                  {turn.line}
                </div>
              </div>
            ))}
          </div>
          {(deck.dialogue.choices?.length ?? 0) > 0 && dialogueChoicesVisible && (
            <div className="mt-4 flex flex-wrap gap-2">
              {(deck.dialogue.choices ?? []).map((ch, idx) => (
                <button key={idx} onClick={() => pickChoice(ch)} className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-sm hover:shadow-md">
                  {ch.line}
                </button>
              ))}
            </div>
          )}
          {dialogueFinished && (
            <button onClick={proceedToFinish} className="mt-4 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
              {t('dialogue.finish')}
            </button>
          )}
          <div className="mt-6 rounded-2xl border border-slate-200 p-4">
            {!demo && (
              <div className="flex flex-wrap gap-2">
                <button onClick={() => speakLine(lastPartnerLine)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 shadow-sm">
                  {t('dialogue.speak')}
                </button>
                {!recorder.recording ? (
                  <button
                    onClick={startRecording}
                    disabled={recorder.busy}
                    className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 shadow-sm disabled:opacity-60"
                  >
                    {t('dialogue.record')}
                  </button>
                ) : (
                  <button
                    onClick={stopRecording}
                    disabled={recorder.busy}
                    className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 shadow-sm disabled:opacity-60"
                  >
                    {recorder.busy ? t('lesson.step.loading') : t('dialogue.stop')}
                  </button>
                )}
              </div>
            )}
            {micError && <p className="mt-2 text-xs text-red-600">{micError}</p>}
            {voiceResult && (
              <div className="mt-3 text-xs text-slate-600">
                <p>{t('dialogue.transcript') ?? 'Transcript'}: {voiceResult.transcript ?? '-'}</p>
                <p>{t('dialogue.rating')}: {voiceResult.rating ?? '-'}</p>
                {voiceResult.tip && <p>{t('dialogue.tip')}: {voiceResult.tip}</p>}
              </div>
            )}
          </div>
        </div>
      )}

      {status === 'finish' && finish && (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl text-white">
            🎉
          </div>
          <h1 className="text-2xl font-bold text-slate-900">{t('finish.title')}</h1>
          <p className="mt-2 text-slate-600">{t('finish.score')}: {finish.score}%</p>
          {finish.xp !== undefined && <p className="text-slate-600">{t('finish.xp')}: +{finish.xp}</p>}
          {finish.next_topic && <p className="text-slate-600">{t('finish.nextTopic')}: {finish.next_topic}</p>}
          {finish.repeat_words && finish.repeat_words.length > 0 && (
            <p className="mt-2 text-slate-600">{t('finish.repeat')}: {finish.repeat_words.join(', ')}</p>
          )}
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <button onClick={start} className="rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-3 text-sm font-semibold text-white shadow-sm">
              {t('finish.nextLesson')}
            </button>
            <Link href="/progress" className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-700 shadow-sm">
              {t('finish.toProgress')}
            </Link>
          </div>
        </div>
      )}
    </main>
  );
}