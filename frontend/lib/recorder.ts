'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Кроссбраузерная запись звука с микрофона.
 *
 * Особенности:
 *  * Safari/iOS не умеет ``audio/webm`` — перебираем кодеки и берём тот,
 *    который поддерживает браузер (``audio/mp4`` на iOS);
 *  * микрофон всегда гасится (в том числе при ошибке и размонтировании);
 *  * запись автоматически останавливается по таймауту;
 *  * отдаём готовый Blob — на сервер он уходит multipart-файлом, без base64.
 */

export const MAX_RECORDING_SEC = 30;

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
  'audio/mpeg',
];

export function pickMimeType(): string | null {
  if (typeof window === 'undefined' || typeof MediaRecorder === 'undefined') {
    return null;
  }
  for (const candidate of MIME_CANDIDATES) {
    try {
      if (MediaRecorder.isTypeSupported(candidate)) {
        return candidate;
      }
    } catch {
      // старые браузеры без isTypeSupported
    }
  }
  return '';
}

export type RecorderState = {
  recording: boolean;
  busy: boolean;
  error: string | null;
  /** Возвращает true, если запись запустилась. */
  start: () => Promise<boolean>;
  stop: () => Promise<Blob | null>;
  cancel: () => void;
};

export function useRecorder(maxSeconds = MAX_RECORDING_SEC): RecorderState {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const resolverRef = useRef<((blob: Blob | null) => void) | null>(null);

  const cleanupStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopTimer();
      if (recorderRef.current && recorderRef.current.state !== 'inactive') {
        try {
          recorderRef.current.stop();
        } catch {
          // уже остановлен
        }
      }
      cleanupStream();
    };
  }, [cleanupStream, stopTimer]);

  const start = useCallback(async () => {
    setError(null);
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setError('unsupported');
      return false;
    }
    if (typeof MediaRecorder === 'undefined') {
      setError('unsupported');
      return false;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const mimeType = pickMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      chunksRef.current = [];
      streamRef.current = stream;
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const chunks = chunksRef.current;
        chunksRef.current = [];
        cleanupStream();
        stopTimer();
        setRecording(false);
        const resolver = resolverRef.current;
        resolverRef.current = null;
        if (resolver) {
          const type = recorder.mimeType || chunks[0]?.type || 'audio/webm';
          resolver(chunks.length > 0 ? new Blob(chunks, { type }) : null);
        }
      };
      recorder.onerror = () => {
        cleanupStream();
        stopTimer();
        setRecording(false);
        setError('failed');
        const resolver = resolverRef.current;
        resolverRef.current = null;
        resolver?.(null);
      };

      recorder.start();
      setRecording(true);
      return true;
      timerRef.current = window.setTimeout(() => {
        if (recorderRef.current && recorderRef.current.state !== 'inactive') {
          recorderRef.current.stop();
        }
      }, maxSeconds * 1000);
    } catch (err) {
      cleanupStream();
      setError('failed');
      return false;
    }
  }, [cleanupStream, maxSeconds, stopTimer]);

  const stop = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') {
      return null;
    }
    setBusy(true);
    const blob = await new Promise<Blob | null>((resolve) => {
      resolverRef.current = resolve;
      recorder.stop();
    });
    setBusy(false);
    return blob;
  }, []);

  const cancel = useCallback(() => {
    stopTimer();
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        // уже остановлен
      }
    }
    cleanupStream();
    chunksRef.current = [];
    resolverRef.current = null;
    setRecording(false);
  }, [cleanupStream, stopTimer]);

  return { recording, busy, error, start, stop, cancel };
}
