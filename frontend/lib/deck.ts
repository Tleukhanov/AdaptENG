export type Locale = 'ru' | 'en';

export type Slide = {
  emoji?: string;
  headline: string;
  body: string;
};

export type VocabCard = {
  word: string;
  translation: string;
  transcription?: string;
  example: string;
};

export type QuizOption = {
  text: string;
  isCorrect: boolean;
};

export type QuizItem = {
  question: string;
  question_ru?: string;
  options: string[];
  correctIndex: number;
  explanation: string;
  explanation_ru?: string;
};

export type DialogueChoice = {
  line: string;
  next: number | string;
};

export type DialogueLine = {
  speaker: 'teacher' | 'student' | string;
  line: string;
  line_ru?: string;
};

export type DialogueScene = {
  title?: string;
  scene: string;
  scene_ru?: string;
  lines: DialogueLine[];
  choices?: DialogueChoice[];
};

export type DeckStep = 'cover' | 'slides' | 'cards' | 'quiz' | 'dialogue' | 'finish';

export type Deck = {
  title: string;
  title_ru?: string;
  subtitle: string;
  subtitle_ru?: string;
  emoji?: string;
  cover: {
    title: string;
    title_ru?: string;
    subtitle: string;
    subtitle_ru?: string;
    emoji: string;
  };
  slides: Slide[];
  vocab: VocabCard[];
  quiz: QuizItem[];
  dialogue: DialogueScene;
};

type BilingualSlide = {
  emoji?: string;
  headline_ru: string;
  headline_en: string;
  body_ru: string;
  body_en: string;
};

type BilingualVocab = {
  word: string;
  translation_ru: string;
  translation_en: string;
  transcription?: string;
  example_ru: string;
  example_en: string;
};

type BilingualQuiz = {
  question_ru: string;
  question_en: string;
  options_ru: string[];
  options_en: string[];
  correctIndex: number;
  explanation_ru: string;
  explanation_en: string;
};

type BilingualDialogueChoice = {
  line_ru: string;
  line_en: string;
  next: number | string;
};

type BilingualDialogueLine = {
  speaker: 'teacher' | 'student' | string;
  line_ru: string;
  line_en: string;
};

type BilingualDialogue = {
  title_ru?: string;
  title_en?: string;
  scene_ru: string;
  scene_en: string;
  lines: BilingualDialogueLine[];
  choices?: BilingualDialogueChoice[];
};

type BilingualDeck = {
  title_ru: string;
  title_en: string;
  subtitle_ru: string;
  subtitle_en: string;
  emoji?: string;
  cover: {
    title_ru: string;
    title_en: string;
    subtitle_ru: string;
    subtitle_en: string;
    emoji: string;
  };
  slides: BilingualSlide[];
  vocab: BilingualVocab[];
  quiz: BilingualQuiz[];
  dialogue: BilingualDialogue;
};

const BILINGUAL_DECK: BilingualDeck = {
  title_ru: 'Урок по путешествиям',
  title_en: 'Travel Basics Lesson',
  subtitle_ru: 'Практикуем базовую лексику и диалог',
  subtitle_en: 'Practice essential travel vocabulary and dialogue',
  emoji: '✈️',
  cover: {
    title_ru: 'Путешествия: базовый урок',
    title_en: 'Travel: Essential Lesson',
    subtitle_ru: 'Разберём ключевые слова, потренируемся в квизе и разыграем диалог',
    subtitle_en: 'Learn key phrases, practice with a quiz, and role-play a dialogue',
    emoji: '🌍',
  },
  slides: [
    {
      emoji: '🧭',
      headline_ru: 'Цель урока',
      headline_en: 'Lesson Goal',
      body_ru: 'Научимся говорить о путешествиях: спрашивать дорогу, бронировать и общаться в аэропорту.',
      body_en: 'Learn to talk about travel: ask for directions, book basics, and handle airport conversations.',
    },
    {
      emoji: '🗺️',
      headline_ru: 'Полезные фразы',
      headline_en: 'Useful Phrases',
      body_ru: 'Сосредоточимся на практических выражениях, которые реально пригодятся в поездке.',
      body_en: 'Focus on practical expressions you can actually use on your trip.',
    },
    {
      emoji: '💬',
      headline_ru: 'Практика в диалоге',
      headline_en: 'Dialogue Practice',
      body_ru: 'Применим новые слова в живом диалоге и проверим понимание.',
      body_en: 'Apply new vocabulary in a real dialogue and test your understanding.',
    },
  ],
  vocab: [
    {
      word: 'destination',
      translation_ru: 'пункт назначения',
      translation_en: 'destination',
      transcription: '/ˌdɛstɪˈneɪʃən/',
      example_ru: 'Наш пункт назначения — Лондон.',
      example_en: 'Our destination is London.',
    },
    {
      word: 'boarding pass',
      translation_ru: 'посадочный талон',
      translation_en: 'boarding pass',
      transcription: '/ˈbɔːrdɪŋ pæs/',
      example_ru: 'Не забудьте взять посадочный талон.',
      example_en: 'Don’t forget your boarding pass.',
    },
    {
      word: 'departure',
      translation_ru: 'отправление',
      translation_en: 'departure',
      transcription: '/dɪˈpɑːrtʃər/',
      example_ru: 'Время отправления изменилось.',
      example_en: 'The departure time has changed.',
    },
  ],
  quiz: [
    {
      question_ru: 'Что такое boarding pass?',
      question_en: 'What is a boarding pass?',
      options_ru: ['Багажная квитанция', 'Посадочный талон', 'Виза', 'Страховка'],
      options_en: ['Baggage claim ticket', 'Boarding pass', 'Visa', 'Travel insurance'],
      correctIndex: 1,
      explanation_ru: 'Boarding pass — это посадочный талон, который нужен для посадки в самолёт.',
      explanation_en: 'A boarding pass is a document you need to board the plane.',
    },
    {
      question_ru: 'Как перевести слово "departure" в контексте аэропорта?',
      question_en: 'What does "departure" mean at the airport?',
      options_ru: ['Прилёт', 'Отправление', 'Транзит', 'Регистрация'],
      options_en: ['Arrival', 'Departure', 'Transit', 'Check-in'],
      correctIndex: 1,
      explanation_ru: 'Departure — это время или рейс отправления.',
      explanation_en: 'Departure refers to the time/flight when a plane leaves.',
    },
    {
      question_ru: 'Выберите подходящее слово: "Our ___ is Paris."',
      question_en: 'Choose the correct word: "Our ___ is Paris."',
      options_ru: ['departure', 'destination', 'boarding', 'terminal'],
      options_en: ['departure', 'destination', 'boarding', 'terminal'],
      correctIndex: 1,
      explanation_ru: 'Destination — пункт назначения.',
      explanation_en: 'Destination means the place you’re going to.',
    },
  ],
  dialogue: {
    title_ru: 'В аэропорту',
    title_en: 'At the Airport',
    scene_ru: 'Вы подходите к стойке регистрации перед вылетом.',
    scene_en: 'You approach the check-in desk before your flight.',
    lines: [
      { speaker: 'teacher', line_ru: 'Добрый день! У вас есть билет на рейс?', line_en: 'Good morning! Do you have your ticket for this flight?' },
      { speaker: 'student', line_ru: 'Да, вот мой билет.', line_en: 'Yes, here is my ticket.' },
      { speaker: 'teacher', line_ru: 'Отлично. Можете показать посадочный талон и паспорт, пожалуйста?', line_en: 'Great. Could you please show me your boarding pass and passport?' },
      { speaker: 'student', line_ru: 'Конечно, держите.', line_en: 'Sure, here you go.' },
      { speaker: 'teacher', line_ru: 'Всё в порядке. Ваш выход на посадку — gate 12. Удачного полёта!', line_en: 'All set. Your boarding gate is Gate 12. Have a nice flight!' },
    ],
    choices: [
      { line_ru: 'Спасибо большое!', line_en: 'Thank you very much!', next: 4 },
      { line_ru: 'А во сколько посадка?', line_en: 'What time is boarding?', next: 4 },
    ],
  },
};

function localizeDeck(item: BilingualDeck, locale: Locale): Deck {
  const ru = locale !== 'en';
  return {
    title: ru ? item.title_ru : item.title_en,
    title_ru: item.title_ru,
    subtitle: ru ? item.subtitle_ru : item.subtitle_en,
    subtitle_ru: item.subtitle_ru,
    emoji: item.emoji,
    cover: {
      title: ru ? item.cover.title_ru : item.cover.title_en,
      title_ru: item.cover.title_ru,
      subtitle: ru ? item.cover.subtitle_ru : item.cover.subtitle_en,
      subtitle_ru: item.cover.subtitle_ru,
      emoji: item.cover.emoji,
    },
    slides: item.slides.map((s) => ({
      emoji: s.emoji,
      headline: ru ? s.headline_ru : s.headline_en,
      body: ru ? s.body_ru : s.body_en,
    })),
    vocab: item.vocab.map((v) => ({
      word: v.word,
      translation: ru ? v.translation_ru : v.translation_en,
      transcription: v.transcription,
      example: ru ? v.example_ru : v.example_en,
    })),
    quiz: item.quiz.map((q) => ({
      question: ru ? q.question_ru : q.question_en,
      question_ru: q.question_ru,
      options: ru ? q.options_ru : q.options_en,
      correctIndex: q.correctIndex,
      explanation: ru ? q.explanation_ru : q.explanation_en,
      explanation_ru: q.explanation_ru,
    })),
    dialogue: {
      title: ru ? item.dialogue.title_ru : item.dialogue.title_en,
      scene: ru ? item.dialogue.scene_ru : item.dialogue.scene_en,
      scene_ru: item.dialogue.scene_ru,
      lines: item.dialogue.lines.map((l) => ({
        speaker: l.speaker,
        line: ru ? l.line_ru : l.line_en,
        line_ru: l.line_ru,
      })),
      choices: item.dialogue.choices?.map((c) => ({
        line: ru ? c.line_ru : c.line_en,
        next: c.next,
      })),
    },
  };
}

export function sampleDeck(locale: Locale): Deck {
  return localizeDeck(BILINGUAL_DECK, locale);
}

export type ApiDeck = {
  title: string;
  subtitle_ru?: string;
  preset?: string;
  emoji?: string;
  slides: { headline: string; body: string; emoji?: string }[];
  vocabulary: { word: string; translation: string; example: string; transcription?: string }[];
  quiz: {
    question: string;
    options: string[];
    answer_index: number;
    explanation_ru?: string;
  }[];
  dialogue: {
    scene_ru?: string;
    lines: { character?: string; line: string }[];
    choices?: { line: string; next: number }[];
  } | null;
};

export function apiDeckToLocal(d: ApiDeck | undefined | null): Deck {
  if (!d) {
    return sampleDeck('ru');
  }
  return {
    title: d.title || 'English lesson',
    title_ru: d.subtitle_ru ?? '',
    subtitle: d.subtitle_ru ?? '',
    subtitle_ru: d.subtitle_ru ?? '',
    emoji: d.emoji ?? '📚',
    cover: {
      title: d.title || 'English lesson',
      subtitle: d.subtitle_ru ?? '',
      emoji: d.emoji ?? '📚',
    },
    slides: Array.isArray(d.slides) ? d.slides : [],
    vocab: Array.isArray(d.vocabulary) ? d.vocabulary : [],
    quiz: Array.isArray(d.quiz)
      ? d.quiz.map((q) => ({
          question: q.question,
          explanation: q.explanation_ru ?? '',
          explanation_ru: q.explanation_ru ?? '',
          options: Array.isArray(q.options) ? q.options : [],
          correctIndex: q.answer_index,
        }))
      : [],
    dialogue: d.dialogue
      ? {
          title: '',
          scene: d.dialogue.scene_ru ?? '',
          scene_ru: d.dialogue.scene_ru ?? '',
          lines: Array.isArray(d.dialogue.lines)
            ? d.dialogue.lines.map((l) => ({ speaker: l.character ?? 'teacher', line: l.line }))
            : [],
          choices: Array.isArray(d.dialogue.choices)
            ? d.dialogue.choices.map((c) => ({ line: c.line, next: c.next }))
            : [],
        }
      : { title: '', scene: '', scene_ru: '', lines: [], choices: [] },
  };
}