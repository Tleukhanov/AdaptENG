'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  API,
  ApiError,
  apiBlob,
  errorMessage,
  finishLesson,
  getToken,
  startLesson,
  voiceAnswer,
} from '@/lib/api';
import { apiDeckToLocal, sampleDeck } from '@/lib/deck';
import type { ApiDeck, Deck, DeckStep, DialogueChoice, QuizItem, VocabCard } from '@/lib/deck';
import type { Locale } from '@/lib/i18n';

type Step = DeckStep;

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
  const [recording, setRecording] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [voiceResult, setVoiceResult] = useState<{ transcript?: string; rating?: number; tip?: string } | null>(null);
  const [finish, setFinish] = useState<FinishResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<'quota' | 'retry' | null>(null);
  const [sessionId, setSessionId] = useState<number | undefined>();
  const [demo, setDemo] = useState(true);
  const [starting, setStarting] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

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

  const hasToken = () => {
    if (typeof window === 'undefined') {
      return false;
    }
    return !!getToken();
  };

  // Демо-режим = нет токена. Определяем после монтирования, чтобы SSR и
  // клиент рендерили одинаково (без расхождения гидрации).
  useEffect(() => {
    setDemo(!getToken());
  }, []);

  async function start() {
    if (starting) {
      return;
    }
    setStarting(true);
    setError(null);
    setStatus('loading');
    try {
      if (demo || !hasToken()) {
        const d = sampleDeck(locale);
        setDeck(d);
        setSessionId(undefined);
        resetSteps();
        setStatus('cover');
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
    setRecording(false);
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

    if (demo || !hasToken()) {
      setFinish({
        score,
        xp: Math.max(5, correctCount * 10),
        next_topic: deck.title,
        repeat_words: deck.vocab.map((v) => v.word),
      });
      setStatus('finish');
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
    try {
      if (!navigator.mediaDevices || !window.MediaRecorder) {
        setMicError(t('dialogue.micUnavailable'));
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      chunksRef.current = [];
      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) {
          chunksRef.current.push(ev.data);
        }
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        const buf = await blob.arrayBuffer();
        const base64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
        try {
          const res = await voiceAnswer({
            audio_base64: base64,
            expected_line: lastPartnerLine || undefined,
          });
          setVoiceResult({
            transcript: res.transcript,
            rating: res.rating,
            tip: res.tip,
          });
        } catch (e) {
          setMicError(t('error.generic'));
        }
        stream.getTracks().forEach((tr) => tr.stop());
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setMicError(t('dialogue.micUnavailable'));
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setRecording(false);
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
            <button onClick={start} className="mt-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
              {t('error.retry')}
            </button>
          )}
        </div>
      )}

      {status === 'loading' && (
        <div className="rounded-3xl border border-slate-200 bg-white p-10 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl text-white">
            {deck?.cover.emoji ?? '🌟'}
          </div>
          <h1 className="text-2xl font-bold text-slate-900">{deck?.cover.title ?? t('start')}</h1>
          <p className="mt-2 text-slate-600">{deck?.cover.subtitle}</p>
          <button onClick={start} className="mt-6 inline-flex items-center rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-6 py-3 text-sm font-semibold text-white shadow-sm">
            {t('presentation.start')}
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
                {!recording ? (
                  <button onClick={startRecording} className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 shadow-sm">
                    {t('dialogue.record')}
                  </button>
                ) : (
                  <button onClick={stopRecording} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 shadow-sm">
                    {t('dialogue.stop')}
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