'use client';

/**
 * Распознавание речи средствами браузера (Web Speech API) — запасной путь,
 * когда серверный STT недоступен (нет ключа облачного провайдера или он перегружен).
 *
 * Поддержка: Chrome/Edge/Safari (префикс webkit). В Firefox API нет — тогда
 * используется серверное распознавание.
 *
 * Как работает: браузер сам стримит аудио в свою речевую службу и отдаёт
 * распознанный текст. Для учебного приложения это нормально, но стоит
 * учитывать, что аудио уходит на сторону браузера (Google/Apple).
 */

export type SpeechCallbacks = {
  onPartial?: (text: string) => void;
  onFinal: (text: string) => void;
  onError?: (message: string) => void;
};

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
};

type SpeechWindow = Window & {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
};

export function isSpeechSupported(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  const w = window as SpeechWindow;
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
}

export function createSpeechRecognizer(
  lang: string,
  callbacks: SpeechCallbacks,
): SpeechRecognitionLike | null {
  if (!isSpeechSupported()) {
    return null;
  }
  const w = window as SpeechWindow;
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) {
    return null;
  }

  const recognition = new Ctor();
  recognition.lang = lang;
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  let finalText = '';

  recognition.onresult = (event: any) => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const chunk = event.results[i];
      const text = chunk?.[0]?.transcript ?? '';
      if (chunk?.isFinal) {
        finalText += text;
      } else {
        interim += text;
      }
    }
    if (interim) {
      callbacks.onPartial?.(interim);
    }
    if (finalText) {
      callbacks.onFinal(finalText.trim());
    }
  };

  recognition.onerror = (event: any) => {
    const code = event?.error ?? 'unknown';
    const messages: Record<string, string> = {
      'not-allowed': 'Доступ к микрофону запрещён',
      'service-not-allowed': 'Браузер запретил распознавание речи',
      'no-speech': 'Не удалось распознать речь',
      'audio-capture': 'Микрофон недоступен',
      network: 'Сервис распознавания в браузере недоступен',
    };
    callbacks.onError?.(messages[code] ?? `Ошибка распознавания: ${code}`);
  };

  recognition.onend = () => {
    if (!finalText) {
      callbacks.onError?.('Не удалось распознать речь');
    }
  };

  return recognition;
}
