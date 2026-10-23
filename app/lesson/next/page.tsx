import TutorSession from '@/components/TutorSession';

/**
 * Обычный урок: диалог с наставником в режиме `lesson`.
 *
 * Бэкенд начинает с повтора прошлой ошибки и объявления темы; `?topic=`
 * необязателен — без него тему выбирает наставник.
 */
export default async function LessonNextPage({
  searchParams,
}: {
  searchParams: Promise<{ topic?: string | string[] }>;
}) {
  const params = await searchParams;
  const raw = Array.isArray(params.topic) ? params.topic[0] : params.topic;
  const topic = raw?.trim() || undefined;

  return <TutorSession mode="lesson" topic={topic} />;
}
