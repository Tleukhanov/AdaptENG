import { cookies } from 'next/headers';
import type { AbstractIntlMessages } from 'next-intl';
import en from '@/messages/en.json';
import ru from '@/messages/ru.json';

export type Locale = 'ru' | 'en';

export const locales: Locale[] = ['ru', 'en'];
export const defaultLocale: Locale = 'ru';
export const LOCALE_COOKIE = 'locale';

type FlatMessages = Record<string, string>;

const flatMessages: Record<Locale, FlatMessages> = {
  ru: ru as FlatMessages,
  en: en as FlatMessages,
};

export function isLocale(value: unknown): value is Locale {
  return value === 'ru' || value === 'en';
}

function unflatten(flat: FlatMessages): AbstractIntlMessages {
  const messages: AbstractIntlMessages = {};
  for (const [key, value] of Object.entries(flat)) {
    const parts = key.split('.');
    let node = messages;
    for (let index = 0; index < parts.length - 1; index += 1) {
      const part = parts[index];
      const existing = node[part];
      if (existing === undefined || typeof existing === 'string') {
        node[part] = {};
      }
      node = node[part] as AbstractIntlMessages;
    }
    node[parts[parts.length - 1]] = value;
  }
  return messages;
}

export function getMessages(locale: Locale): AbstractIntlMessages {
  return unflatten(flatMessages[locale]);
}

export async function getLocale(): Promise<Locale> {
  const store = await cookies();
  const value = store.get(LOCALE_COOKIE)?.value;
  return isLocale(value) ? value : defaultLocale;
}
