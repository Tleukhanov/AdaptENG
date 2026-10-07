"""RAG-тьютор грамматики: ответы по корпусу правил.

Принцип: RAG ДОПОЛНЯЕТ адаптивную практику, но не подменяет её.
Тьютор работает только в отдельном режиме (команда /tutor), обычные потоки
(практика, уроки, диагностика, SRS) не затронуты. Если эмбеддинги
недоступны или вопрос не похож на правило — тьютор мягко отвечает обычным
LLM-чатом: пользователь всегда получает ответ.
"""

from __future__ import annotations

import asyncio
import logging

from bot.data.grammar_base import GRAMMAR_CHUNKS

logger = logging.getLogger(__name__)

EMBED_MODEL = "openai/text-embedding-3-small"
DEFAULT_THRESHOLD = 0.30
TOP_K = 3


class EmbeddingsError(Exception):
    """Эмбеддинги недоступны (сеть, провайдер, локальная модель)."""


def cosine(a, b):
    """Косинусная близость двух векторов; безопасно для нулевых."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _split_interests(profile) -> list[str]:
    raw = (profile or {}).get("interests") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    return [str(item).strip() for item in raw if str(item).strip()]


def build_messages(
    question: str,
    profile: dict | None,
    found: list[dict],
) -> list[dict[str, str]]:
    """Склейка LLM-сообщений: профиль (кто) + контекст (что) или чистый чат.

    found — найденные чанки корпуса (пустой список = обычный чат без контекста).
    """
    level = (profile or {}).get("level") or "?"
    interests = _split_interests(profile)
    if interests:
        examples_rule = (
            "Примеры строй на интересах ученика: " + ", ".join(interests) + ". "
            "Классические примеры из контекста НЕ приводи — придумай свои."
        )
    else:
        examples_rule = (
            "Интересы ученика неизвестны — используй классические примеры из контекста."
        )

    base = (
        f"Ты репетитор английского для русскоязычного ученика уровня {level}. "
        f"Отвечай по-русски. Объясняй просто и коротко. {examples_rule}"
    )
    if found:
        context = "\n\n".join(f"[{c['title']}] {c['text']}" for c in found)
        system = (
            base + " Отвечай СТРОГО по контексту ниже и укажи, из какого правила взял ответ. "
            "Если ответа нет в контексте — честно скажи, что это вне материалов, "
            "и ответь коротко сам."
            f"\n\nКонтекст:\n{context}"
        )
    else:
        system = base + " Отвечай как обычно, дружелюбно и коротко."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


class RAGGrammarTutor:
    """RAG-тьютор: эмбеддинги корпуса → top-k → роутинг по порогу.

    chat — LLM-провайдер (любой объект с ``async chat(messages, ...)``).
    embedder — асинхронная функция ``(texts: list[str]) -> list[list[float]]``.
    Весь корпус эмбеддится один раз (лениво, при первом вопросе).
    """

    def __init__(
        self,
        chat,
        embedder,
        *,
        chunks: list[dict] | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        top_k: int = TOP_K,
    ):
        self._chat = chat
        self._embedder = embedder
        self._chunks = chunks if chunks is not None else GRAMMAR_CHUNKS
        self._threshold = threshold
        self._top_k = top_k
        self._vectors = None
        self._init_lock = asyncio.Lock()

    @property
    def corpus_size(self) -> int:
        return len(self._chunks)

    async def ensure_vectors(self) -> None:
        """Эмбеддит весь корпус один раз (первый вопрос). Идемпотентно."""
        if self._vectors is not None:
            return
        async with self._init_lock:
            if self._vectors is not None:
                return
            try:
                self._vectors = await self._embedder([c["text"] for c in self._chunks])
            except Exception as exc:
                logger.warning("RAG: эмбеддинги недоступны: %s", exc)
                raise EmbeddingsError from exc

    async def search(self, question: str, top_k: int | None = None) -> list[tuple[dict, float]]:
        """Отсортированные по близости чанки (chunk, cosine) для вопроса."""
        if not question.strip():
            return []
        await self.ensure_vectors()
        qv = (await self._embedder([question]))[0]
        limit = top_k or self._top_k
        ranked = sorted(
            zip(self._chunks, self._vectors),
            key=lambda item: cosine(qv, item[1]),
            reverse=True,
        )
        return [(chunk, cosine(qv, vec)) for chunk, vec in ranked[:limit]]

    async def answer(
        self,
        question: str,
        profile: dict | None = None,
    ) -> tuple[str, str, list[tuple[str, float]]]:
        """Ответ: ``(text, mode, citations)``. mode: 'rag' | 'chat'.

        Любой сбой эмбеддингов не ломает ответ — переходим в обычный чат.
        """
        hits: list[tuple[dict, float]] = []
        try:
            hits = await self.search(question)
        except EmbeddingsError:
            hits = []
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG search failed (%s), fallback to chat", type(exc).__name__)
            hits = []

        best = hits[0][1] if hits else 0.0
        found = [chunk for chunk, _ in hits] if best >= self._threshold else []
        mode = "rag" if found else "chat"

        messages = build_messages(question, profile, found)
        text = await self._chat.chat(messages, temperature=0.0)
        citations = (
            [(chunk["title"], round(score, 3)) for chunk, score in hits] if found else []
        )
        return text, mode, citations