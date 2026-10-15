"""Очередь и троттлинг для web-api: защита от перегрузки LLM/STT.

Смысл: LLM-вызов стоит денег и ждёт сеть, поэтому при большом числе
одновременных пользователей мы не гоним в провайдера 100 запросов сразу.
Вместо этого держим семафор ``concurrency`` активных вызовов, остальные ждут
в ограниченной очереди. Кто не влез в очередь или не дождался слота за
``queue_timeout`` — получает HTTP 429, а не висит и не упирается в провайдера.

Дополнительно — троттлинг LLM-действий на пользователя (окно + минимальный
интервал между действиями), аналог ``bot.rate_limit.LLMThrottle``.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


class QueueFull(Exception):
    """Очередь LLM заполнена (или слот не освободился за timeout)."""


class TooManyActions(Exception):
    """Пользователь слишком часто жмёт LLM-кнопки."""


@dataclass
class GuardStats:
    """Счётчики для наблюдаемости (видно в логах и тестах)."""

    started: int = 0
    finished: int = 0
    rejected: int = 0
    timed_out: int = 0
    peak_in_flight: int = 0
    in_flight: int = 0
    waiting: int = 0


class AsyncQueueGuard:
    """Семафор + ограниченная очередь ожидания."""

    def __init__(self, concurrency: int, queue_max: int, queue_timeout: float) -> None:
        self._concurrency = max(1, int(concurrency))
        self._queue_max = max(0, int(queue_max))
        self._queue_timeout = max(0.0, float(queue_timeout))
        self._sem = asyncio.Semaphore(self._concurrency)
        self._waiting = 0
        self.stats = GuardStats()

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def waiting(self) -> int:
        return self._waiting

    @asynccontextmanager
    async def slot(self):
        """Асинхронный контекст: держит слот на время LLM-вызова.

        ``QueueFull`` — все слоты заняты, очередь переполнена или слот
        не дождались за timeout.
        """
        # Отклоняем только когда действительно нет свободных слотов И очередь полна.
        # Иначе (слот свободен) запрос проходит сразу, даже при queue_max=0.
        if self._sem.locked() and self._waiting >= self._queue_max:
            self.stats.rejected += 1
            raise QueueFull("очередь LLM переполнена")

        self._waiting += 1
        try:
            try:
                await asyncio.wait_for(self._sem.acquire(), timeout=self._queue_timeout)
            except asyncio.TimeoutError as exc:
                self.stats.timed_out += 1
                self.stats.rejected += 1
                raise QueueFull("не дождались слота LLM") from exc
        finally:
            self._waiting -= 1

        self.stats.started += 1
        self.stats.in_flight += 1
        self.stats.peak_in_flight = max(self.stats.peak_in_flight, self.stats.in_flight)
        try:
            yield
        finally:
            self.stats.in_flight -= 1
            self.stats.finished += 1
            self._sem.release()

    def snapshot(self) -> dict[str, int]:
        return {
            "concurrency": self._concurrency,
            "queue_max": self._queue_max,
            "waiting": self._waiting,
            "in_flight": self.stats.in_flight,
            "started": self.stats.started,
            "finished": self.stats.finished,
            "rejected": self.stats.rejected,
            "timed_out": self.stats.timed_out,
            "peak_in_flight": self.stats.peak_in_flight,
        }


class ActionThrottle:
    """Скользящее окно + минимальный интервал между LLM-действиями пользователя.

    Повторяет поведение ``bot.rate_limit.LLMThrottle``: за окно ``window_sec``
    разрешено не больше ``limit`` действий, между соседними — пауза
    ``min_interval`` сек. Старые записи вычищаются, чтобы словарь не рос.
    """

    def __init__(self, window_sec: float = 60.0, limit: int = 12, min_interval: float = 2.0) -> None:
        self.window_sec = max(1.0, float(window_sec))
        self.limit = max(0, int(limit))
        self.min_interval = max(0.0, float(min_interval))
        self._actions: dict[str, list[float]] = {}
        self._last_sweep = time.monotonic()

    def _sweep(self, now: float) -> None:
        cutoff = now - self.window_sec
        for key in list(self._actions):
            stamps = [s for s in self._actions[key] if s > cutoff]
            if stamps:
                self._actions[key] = stamps
            else:
                del self._actions[key]
        self._last_sweep = now

    def allow(self, key: str) -> bool:
        if self.limit <= 0 and self.min_interval <= 0:
            return True
        now = time.monotonic()
        if now - self._last_sweep >= self.window_sec:
            self._sweep(now)

        stamps = self._actions.setdefault(key, [])
        cutoff = now - self.window_sec
        stamps[:] = [s for s in stamps if s > cutoff]

        if self.min_interval > 0 and stamps and now - stamps[-1] < self.min_interval:
            return False
        if self.limit > 0 and len(stamps) >= self.limit:
            return False

        stamps.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._actions.clear()
        else:
            self._actions.pop(key, None)


@dataclass
class ClientWindowLimiter:
    """Простой лимит запросов на клиента (IP) в скользящем окне."""

    window_sec: float = 60.0
    limit: int = 240
    _hits: dict[str, list[float]] = field(default_factory=dict)

    def allow(self, client: str, now: float | None = None) -> bool:
        if self.limit <= 0:
            return True
        stamp = time.monotonic() if now is None else now
        cutoff = stamp - self.window_sec
        hits = self._hits.setdefault(client, [])
        hits[:] = [t for t in hits if t > cutoff]
        if len(hits) >= self.limit:
            return False
        hits.append(stamp)
        if len(self._hits) > 4096:  # страховка от роста памяти
            self._hits = {
                key: value
                for key, value in self._hits.items()
                if any(t > cutoff for t in value)
            }
        return True