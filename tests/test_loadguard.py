"""Тесты защиты api от перегрузки: очередь LLM, троттлинг, лимит запросов."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from api.loadguard import (
    ActionThrottle,
    AsyncQueueGuard,
    ClientWindowLimiter,
    QueueFull,
)
from api.main import create_app
from core.config import Settings
from core.practice import PracticeService
from providers.base import LLMProvider

SECRET = "test-secret-0123456789abcdef0123456789"

TASKS_JSON = '{"tasks": [{"text": "Intro yourself", "level_hint": "A1"}]}'


class SlowLLM(LLMProvider):
    """LLM, который думает заданное время и считает пиковую параллельность."""

    def __init__(self, delay: float = 0.15) -> None:
        self.delay = delay
        self.calls = 0
        self.in_flight = 0
        self.peak = 0

    async def chat(self, messages, temperature=None, json_mode=False):
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return TASKS_JSON
        finally:
            self.in_flight -= 1


def _app(tmp_path, llm, **overrides):
    options = {
        "database_path": str(tmp_path / "loadguard_test.db"),
        "jwt_secret": SECRET,
        "api_insecure_auth": 1,
        "llm_daily_limit": 0,
        "api_rate_limit_per_min": 0,
        "api_llm_actions_per_min": 0,
        "api_llm_min_interval_sec": 0,
    }
    options.update(overrides)
    return create_app(Settings(**options))


async def _token(client: httpx.AsyncClient, tg_id: int) -> str:
    response = await client.post(
        "/api/auth/tg",
        json={
            "id": tg_id,
            "first_name": "T",
            "auth_date": int(time.time()),
            "hash": "",
        },
    )
    return response.json()["token"]


# ---------- AsyncQueueGuard ----------


def test_guard_respects_concurrency() -> None:
    async def scenario() -> int:
        guard = AsyncQueueGuard(concurrency=3, queue_max=50, queue_timeout=5)
        peak = 0
        current = 0

        async def worker() -> None:
            nonlocal peak, current
            async with guard.slot():
                current += 1
                peak = max(peak, current)
                await asyncio.sleep(0.05)
                current -= 1

        await asyncio.gather(*(worker() for _ in range(12)))
        return peak

    assert asyncio.run(scenario()) == 3


def test_guard_rejects_when_queue_full() -> None:
    async def scenario() -> tuple[int, int]:
        guard = AsyncQueueGuard(concurrency=1, queue_max=1, queue_timeout=5)
        done = 0
        rejected = 0

        async def worker() -> None:
            nonlocal done, rejected
            try:
                async with guard.slot():
                    await asyncio.sleep(0.05)
                    done += 1
            except QueueFull:
                rejected += 1

        await asyncio.gather(*(worker() for _ in range(10)))
        return done, rejected

    done, rejected = asyncio.run(scenario())
    assert rejected > 0, "при переполненной очереди часть запросов должна отклоняться"
    assert done >= 1
    assert guard_stats_ok(done, rejected)


def guard_stats_ok(done: int, rejected: int) -> bool:
    return done + rejected == 10


def test_guard_timeout_rejects() -> None:
    async def scenario() -> None:
        guard = AsyncQueueGuard(concurrency=1, queue_max=10, queue_timeout=0.05)
        holder_entered = asyncio.Event()
        release = asyncio.Event()

        async def holder() -> None:
            async with guard.slot():
                holder_entered.set()
                await release.wait()

        task = asyncio.create_task(holder())
        await holder_entered.wait()
        with pytest.raises(QueueFull):
            async with guard.slot():
                await asyncio.sleep(0.3)
        release.set()
        await task

    asyncio.run(scenario())


def test_guard_snapshot_counts() -> None:
    async def scenario() -> dict[str, int]:
        guard = AsyncQueueGuard(concurrency=2, queue_max=10, queue_timeout=2)
        async with guard.slot():
            pass
        return guard.snapshot()

    snapshot = asyncio.run(scenario())
    assert snapshot["started"] == 1
    assert snapshot["finished"] == 1
    assert snapshot["in_flight"] == 0
    assert snapshot["peak_in_flight"] == 1


# ---------- ActionThrottle ----------


def test_action_throttle_min_interval() -> None:
    throttle = ActionThrottle(window_sec=60, limit=10, min_interval=5)
    assert throttle.allow("u1") is True
    assert throttle.allow("u1") is False
    assert throttle.allow("u2") is True


def test_action_throttle_limit_per_window() -> None:
    throttle = ActionThrottle(window_sec=60, limit=3, min_interval=0)
    assert [throttle.allow("u1") for _ in range(5)] == [True, True, True, False, False]


def test_action_throttle_disabled() -> None:
    throttle = ActionThrottle(window_sec=60, limit=0, min_interval=0)
    assert all(throttle.allow("u1") for _ in range(10))


def test_action_throttle_sweeps_memory() -> None:
    throttle = ActionThrottle(window_sec=60, limit=5, min_interval=0)
    for i in range(100):
        throttle.allow(f"u{i}")
    assert len(throttle._actions) == 100
    # Симулируем, что прошло вдвое больше окна: записи вне окна вычищаются.
    throttle._sweep(time.monotonic() + 120)
    assert len(throttle._actions) == 0


# ---------- ClientWindowLimiter ----------


def test_client_limiter() -> None:
    limiter = ClientWindowLimiter(window_sec=60, limit=3)
    assert [limiter.allow("1.2.3.4") for _ in range(5)] == [True, True, True, False, False]
    assert limiter.allow("5.6.7.8") is True


def test_client_limiter_disabled() -> None:
    limiter = ClientWindowLimiter(window_sec=60, limit=0)
    assert all(limiter.allow("x") for _ in range(100))


# ---------- Уровень API ----------


async def test_api_concurrency_limit_returns_429(tmp_path) -> None:
    llm = SlowLLM(delay=0.2)
    app = _app(tmp_path, llm, llm_max_concurrency=2, llm_queue_max=0)
    async with app.router.lifespan_context(app):
        app.state.llm = llm
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            tokens = await asyncio.gather(*(_token(client, 1000 + i) for i in range(8)))

            async def start(tg_id: int, token: str) -> int:
                response = await client.post(
                    "/api/diagnostic/start",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return response.status_code

            codes = await asyncio.gather(*(start(1000 + i, t) for i, t in enumerate(tokens)))

    assert all(code in (200, 429) for code in codes), f"неожиданные коды: {codes}"
    assert codes.count(200) == 2, f"ровно 2 должны пройти очередь: {codes}"
    assert codes.count(429) == 6
    assert llm.peak <= 2


async def test_api_queue_absorbs_burst(tmp_path) -> None:
    """С очередью 10 запросы не отбрасываются: 8 параллельных проходят все."""
    llm = SlowLLM(delay=0.05)
    app = _app(tmp_path, llm, llm_max_concurrency=2, llm_queue_max=16)
    async with app.router.lifespan_context(app):
        app.state.llm = llm
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            tokens = await asyncio.gather(*(_token(client, 2000 + i) for i in range(8)))

            async def start(token: str) -> int:
                response = await client.post(
                    "/api/diagnostic/start",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return response.status_code

            codes = await asyncio.gather(*(start(t) for t in tokens))

    assert codes.count(200) == 8, f"очередь должна была всех пропустить: {codes}"
    assert llm.peak <= 2


async def test_api_chat_throttles_same_user(tmp_path) -> None:
    llm = SlowLLM(delay=0.01)
    app = _app(tmp_path, llm, llm_max_concurrency=4, llm_queue_max=16, api_llm_min_interval_sec=5)
    async with app.router.lifespan_context(app):
        app.state.llm = llm
        app.state.practice = PracticeService(llm=llm, max_history=6)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            token = await _token(client, 3000)
            headers = {"Authorization": f"Bearer {token}"}
            codes = []
            for _ in range(4):
                response = await client.post("/api/chat", headers=headers, json={"text": "hello"})
                codes.append(response.status_code)
    # первый запрос уходит в LLM (не 429), дальше — троттлинг срабатывает
    assert codes[0] != 429
    assert codes.count(429) == 3


async def test_api_rate_limit_middleware(tmp_path) -> None:
    llm = SlowLLM(delay=0.01)
    app = _app(tmp_path, llm, api_rate_limit_per_min=5)
    async with app.router.lifespan_context(app):
        app.state.llm = llm
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            codes = []
            for _ in range(8):
                response = await client.get("/api/characters?lang=ru")
                codes.append(response.status_code)

    assert codes.count(200) == 5
    assert codes.count(429) == 3