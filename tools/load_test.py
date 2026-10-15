"""Нагрузочный тест api AdaptENG: N виртуальных пользователей одновременно.

Зачем: проверить, что при 50–100 параллельных клиентах сервис не падает, а
лишние запросы аккуратно отсекаются (429), очередь LLM работает и p95 в норме.

LLM здесь подменён медленной заглушкой (без реальных денег и сети) — мы
измеряем поведение нашего api: очередь, троттлинг, БД, лимиты.

Запуск:
    python tools/load_test.py                 # 50 юзеров, дефолтные лимиты
    python tools/load_test.py --users 100 --mix burst
    python tools/load_test.py --users 100 --llm-delay 1.5 --llm-concurrency 8
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from api.main import create_app  # noqa: E402
from core.config import Settings  # noqa: E402
from providers.base import LLMProvider  # noqa: E402

DECK_JSON = """
{
  "title": "Coffee and food",
  "subtitle_ru": "Кофе и еда",
  "preset": "mixed",
  "emoji": "☕",
  "slides": [{"headline": "Types of coffee", "body": "Espresso is small and strong.", "emoji": "☕"}],
  "vocabulary": [{"word": "espresso", "translation": "эспрессо", "example": "I drink espresso daily.", "transcription": "/ɪˈsprɛsoʊ/"}],
  "quiz": [{"question": "What is espresso?", "options": ["Coffee", "Tea"], "answer_index": 0, "explanation_ru": "Эспрессо — это кофе."}],
  "dialogue": {
    "scene_ru": "В кофейне",
    "lines": [{"character": "Barista", "line": "What do you like?"}],
    "choices": [{"line": "A latte, please.", "next": -1}]
  }
}
"""

PRACTICE_JSON = """
{
  "corrected_text": "Hello! How are you?",
  "is_correct": true,
  "spoken_reply": "Hi! Great to see you. How can I help?",
  "next_question": "",
  "issues": [],
  "tone": "friendly"
}
"""


class FakeLLM(LLMProvider):
    """Заглушка LLM: реалистичная задержка, счётчики параллельности."""

    def __init__(self, delay: float = 0.4) -> None:
        self.delay = delay
        self.calls = 0
        self.in_flight = 0
        self.peak = 0
        self.total_time = 0.0

    async def chat(self, messages, temperature=None, json_mode=False):
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        started = time.perf_counter()
        try:
            await asyncio.sleep(self.delay * random.uniform(0.8, 1.2))
            prompt = messages[0]["content"] if messages else ""
            if "teaching" in prompt.lower() and "deck" in prompt.lower():
                return DECK_JSON
            if "placement" in prompt.lower():
                return '{"tasks": [{"text": "Introduce yourself", "level_hint": "A1"}]}'
            if "assessing" in prompt.lower():
                return '{"level": "B1", "confidence": 0.7, "explanation_ru": "Средний уровень", "strengths": [], "weaknesses": [], "recommendation": ""}'
            return PRACTICE_JSON
        finally:
            self.total_time += time.perf_counter() - started
            self.in_flight -= 1


@dataclass
class Results:
    latencies: dict[str, list[float]] = field(default_factory=dict)
    codes: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def add(self, name: str, code: int, elapsed: float) -> None:
        self.latencies.setdefault(name, []).append(elapsed)
        self.codes[code] += 1

    def pct(self, name: str, p: float) -> float:
        values = sorted(self.latencies.get(name, []))
        if not values:
            return 0.0
        index = min(len(values) - 1, int(round((p / 100) * len(values) - 1)))
        return values[index]


async def _login(client: httpx.AsyncClient, tg_id: int) -> str:
    response = await client.post(
        "/api/auth/tg",
        json={
            "id": tg_id,
            "first_name": f"User{tg_id}",
            "auth_date": int(time.time()),
            "hash": "",
        },
    )
    response.raise_for_status()
    return response.json()["token"]


async def _timed(client: httpx.AsyncClient, results: Results, name: str, method: str, path: str, **kwargs) -> int:
    started = time.perf_counter()
    try:
        response = await client.request(method, path, **kwargs)
        code = response.status_code
    except Exception as exc:  # noqa: BLE001 - в нагрузке важно не уронить прогон
        results.add(name, 599, time.perf_counter() - started)
        results.errors.append(f"{name}: {type(exc).__name__}: {exc}")
        return 599
    results.add(name, code, time.perf_counter() - started)
    return code


async def _user(client: httpx.AsyncClient, results: Results, tg_id: int, mix: str, rng: random.Random) -> None:
    token = await _login(client, tg_id)
    headers = {"Authorization": f"Bearer {token}"}

    await _timed(client, results, "GET /api/me", "GET", "/api/me", headers=headers)
    await _timed(client, results, "GET /api/progress", "GET", "/api/progress", headers=headers)

    if mix == "read":
        for _ in range(3):
            await _timed(client, results, "GET /api/progress", "GET", "/api/progress", headers=headers)
            await _timed(client, results, "GET /api/review/due", "GET", "/api/review/due", headers=headers)
        return

    # главное действие — генерация урока (самый дорогой эндпоинт)
    code = await _timed(
        client,
        results,
        "POST /api/lesson/new",
        "POST",
        "/api/lesson/new",
        headers=headers,
        json={"topic": "Coffee", "preset": rng.choice(["cards", "quiz", "mixed"])},
    )
    if code != 200:
        return

    await _timed(
        client,
        results,
        "POST /api/lesson/finish",
        "POST",
        "/api/lesson/finish",
        headers=headers,
        json={"score": 100, "preset": "mixed", "quiz_answers": [], "flashcards": {"espresso": True}},
    )
    await _timed(client, results, "POST /api/chat", "POST", "/api/chat", headers=headers, json={"text": "Hello there"})
    await _timed(
        client,
        results,
        "POST /api/diagnostic/start",
        "POST",
        "/api/diagnostic/start",
        headers=headers,
    )


async def run(users: int, mix: str, llm_delay: float, concurrency: int, queue_max: int, db_path: str) -> int:
    settings = Settings(
        database_path=db_path,
        jwt_secret="load-test-secret-0123456789abcdef",
        api_insecure_auth=1,
        llm_daily_limit=0,
        api_rate_limit_per_min=0,
        api_llm_actions_per_min=0,
        api_llm_min_interval_sec=0,
        llm_max_concurrency=concurrency,
        llm_queue_max=queue_max,
        llm_queue_timeout_sec=30.0,
        stt_max_concurrency=2,
    )
    app = create_app(settings)
    llm = FakeLLM(delay=llm_delay)
    results = Results()
    rng = random.Random(42)

    print(f"--> users={users} mix={mix} llm_delay={llm_delay}s concurrency={concurrency} queue_max={queue_max}")

    async with app.router.lifespan_context(app):
        app.state.llm = llm
        from core.practice import PracticeService

        app.state.practice = PracticeService(llm=llm, max_history=6)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://loadtest") as client:
            started = time.perf_counter()
            await asyncio.gather(*(_user(client, results, 500000 + i, mix, rng) for i in range(users)))
            elapsed = time.perf_counter() - started

    total = sum(results.codes.values())
    print(f"\n=== {total} запросов за {elapsed:.1f}s ({total / elapsed:.1f} rps) ===")
    print("коды:", dict(sorted(results.codes.items())))
    print(f"LLM: calls={llm.calls} peak_parallel={llm.peak} avg_time={llm.total_time / max(1, llm.calls):.2f}s")
    guard = getattr(app.state, "llm_guard", None)
    if guard is not None:
        print("guard:", guard.snapshot())

    print("\nзадержки по эндпоинтам:")
    for name, values in sorted(results.latencies.items()):
        print(
            f"  {name:26s} n={len(values):4d} "
            f"p50={statistics.median(values) * 1000:7.0f}ms "
            f"p95={results.pct(name, 95) * 1000:7.0f}ms "
            f"max={max(values) * 1000:7.0f}ms"
        )

    if results.errors:
        print(f"\nошибки транспорта ({len(results.errors)}):")
        for err in results.errors[:5]:
            print("  ", err)

    bad_5xx = sum(count for code, count in results.codes.items() if code >= 500)
    print(f"\n5xx: {bad_5xx} (должно быть 0)")
    print(f"429 (лимит/очередь): {results.codes.get(429, 0)} — это ожидаемо при перегрузке")
    return 1 if bad_5xx else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Нагрузочный тест api AdaptENG")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--mix", choices=["read", "lesson", "burst"], default="lesson")
    parser.add_argument("--llm-delay", type=float, default=0.4)
    parser.add_argument("--llm-concurrency", type=int, default=8)
    parser.add_argument("--queue-max", type=int, default=64)
    parser.add_argument("--db", default="data/load_test.db")
    args = parser.parse_args()

    Path("data").mkdir(exist_ok=True)
    Path(args.db).unlink(missing_ok=True)
    return asyncio.run(
        run(
            users=args.users,
            mix=args.mix,
            llm_delay=args.llm_delay,
            concurrency=args.llm_concurrency,
            queue_max=args.queue_max,
            db_path=args.db,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())