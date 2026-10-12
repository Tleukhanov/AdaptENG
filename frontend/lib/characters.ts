export type Locale = 'ru' | 'en';

export type Character = {
  id: string;
  emoji: string;
  voice?: string;
  avatar: string;
  palette: string[];
  name: string;
  description: string;
  tagline: string;
  backstory: string;
};

type BilingualCharacter = {
  id: string;
  emoji: string;
  voice: string;
  name_ru: string;
  name_en: string;
  tagline_ru: string;
  tagline_en: string;
  description_ru: string;
  description_en: string;
  backstory_ru: string;
  backstory_en: string;
  avatar: string;
  palette: string[];
};

const BILINGUAL: BilingualCharacter[] = [
  {
    id: 'default',
    emoji: '📚',
    voice: 'en-US-AriaNeural',
    name_ru: 'Обычный учитель',
    name_en: 'Standard Tutor',
    tagline_ru: 'Адаптируется под любого — без сюрпризов',
    tagline_en: 'Adapts to anyone — no surprises',
    description_ru: 'Дружелюбный и профессиональный преподаватель',
    description_en: 'Friendly, professional tutor — a calm start for any level',
    backstory_ru: 'Опытный преподаватель, за плечами которого сотни учеников.',
    backstory_en: 'An experienced teacher with hundreds of students behind them.',
    avatar: '',
    palette: ['#6366f1', '#22d3ee'],
  },
  {
    id: 'chill',
    emoji: '😎',
    voice: 'en-US-GuyNeural',
    name_ru: 'Chill Teacher',
    name_en: 'Chill Teacher',
    tagline_ru: 'Учимся легко и без стресса',
    tagline_en: 'Learn easy, stress-free',
    description_ru: 'Спокойный, дружелюбный, как друг. Объясняет просто, без давления.',
    description_en: 'Calm and friendly, like a friend. Explains simply, zero pressure.',
    backstory_ru: 'Считает, что английский нельзя учить со страхом.',
    backstory_en: 'Believes English can\'t be learned out of fear.',
    avatar: '',
    palette: ['#10b981', '#a7f3d0'],
  },
  {
    id: 'toxic',
    emoji: '🔥',
    voice: 'en-US-BrianNeural',
    name_ru: 'Toxic Teacher',
    name_en: 'Toxic Teacher',
    tagline_ru: 'Сарказм не щадит, но учит намертво',
    tagline_en: 'Sarcasm knows no mercy, but you\'ll never forget',
    description_ru: 'Грубоватый, подкалывает, но учит. Сарказм как мотивация.',
    description_en: 'Mean, sarcastic, but he teaches. Roasting is his motivation.',
    backstory_ru: 'Уверен: пока тебе не стыдно — ты не учишься.',
    backstory_en: 'He\'s sure: until it\'s embarrassing, you\'re not learning.',
    avatar: '',
    palette: ['#ef4444', '#f97316'],
  },
  {
    id: 'strict',
    emoji: '🎩',
    voice: 'en-US-BrianNeural',
    name_ru: 'Strict Teacher',
    name_en: 'Strict Teacher',
    tagline_ru: 'Точность — единственный комплимент, который он даёт',
    tagline_en: 'Precision is the only compliment he gives',
    description_ru: 'Серьёзный, требовательный, акцент на грамматику и точность.',
    description_en: 'Serious and demanding — grammar first, precision always.',
    backstory_ru: 'Видит ошибку в каждом предложении и считает это знаком уважения.',
    backstory_en: 'Finds a mistake in every sentence and calls it a sign of respect.',
    avatar: '',
    palette: ['#1e293b', '#475569'],
  },
  {
    id: 'british',
    emoji: '🇬🇧',
    voice: 'en-GB-SoniaNeural',
    name_ru: 'British Teacher',
    name_en: 'British Teacher',
    tagline_ru: 'Brilliant английский с британским характером',
    tagline_en: 'Brilliant English with a British personality',
    description_ru: 'Британский английский, вежливый, с британским юмором и культурой.',
    description_en: 'Proper British English, dry humour and impeccable manners.',
    backstory_ru: 'Образование — Оксфорд, чай — 5 вечера.',
    backstory_en: 'Educated at Oxford, tea promptly at five.',
    avatar: '',
    palette: ['#3b82f6', '#a5b4fc'],
  },
  {
    id: 'toxic_friend',
    emoji: '💀',
    voice: 'en-US-JennyNeural',
    name_ru: 'Toxic Friend',
    name_en: 'Toxic Friend',
    tagline_ru: 'Друг, который просто говорит на английском',
    tagline_en: 'Just a friend who happens to speak English',
    description_ru: 'Общается как друг из мемов. Смешно, современно, без снисходительности.',
    description_en: 'A meme-literate bestie. Funny, modern, zero condescension.',
    backstory_ru: 'Знает все мемы до того, как они стали мейнстримом.',
    backstory_en: 'Knows every meme before it goes mainstream.',
    avatar: '',
    palette: ['#8b5cf6', '#ec4899'],
  },
];

function localize(item: BilingualCharacter, locale: Locale): Character {
  const ru = locale !== 'en';
  return {
    id: item.id,
    emoji: item.emoji,
    voice: item.voice,
    avatar: item.avatar,
    palette: item.palette,
    name: ru ? item.name_ru : item.name_en,
    description: ru ? item.description_ru : item.description_en,
    tagline: ru ? item.tagline_ru : item.tagline_en,
    backstory: ru ? item.backstory_ru : item.backstory_en,
  };
}

export function sampleCharacters(locale: Locale): Character[] {
  return BILINGUAL.map((item) => localize(item, locale));
}