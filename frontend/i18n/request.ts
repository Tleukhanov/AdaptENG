import { getRequestConfig } from 'next-intl/server';
import { getLocale, getMessages } from '@/lib/i18n';

export default getRequestConfig(async () => {
  const locale = await getLocale();
  return {
    locale,
    messages: getMessages(locale),
  };
});
