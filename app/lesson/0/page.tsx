import TutorSession from '@/components/TutorSession';

/**
 * «Урок 0» — знакомство с наставником-аватаром.
 *
 * Тонкая обёртка над общим экраном диалога: режим `intro`. Гость проходит
 * его сразу после онбординга, поэтому авторизация не требуется.
 */
export default function LessonZeroPage() {
  return <TutorSession mode="intro" />;
}
