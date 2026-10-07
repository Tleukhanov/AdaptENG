"""Tests for Phase — RAG grammar tutor (core/rag.py).

RAG должен ДОПОЛНЯТЬ адаптивную практику, не ломая её:
это покрывают тесты ранжирования/роутинга и фоллбэка на обычный чат.
"""

import hashlib
import re

import pytest

from bot.data.grammar_base import GRAMMAR_CHUNKS
from core.rag import (
    EmbeddingsError,
    RAGGrammarTutor,
    build_messages,
    cosine,
)


def hash_embed(texts: list[str], dim: int = 64) -> list[list[float]]:
    """Детерминированный эмбеддер: близкий текст -> ненулевой косинус."""
    out = []
    for text in texts:
        vec = [0.0] * dim
        for token in re.findall(r"[a-z']+", text.lower()):
            vec[hashlib.md5(token.encode()).digest()[0] % dim] += 1.0
        out.append(vec)
    return out


class HashEmbedder:
    """Асинхронная обёртка над hash_embed (контракт эмбеддера — async)."""

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        return hash_embed(texts)


class FakeChat:
    def __init__(self, reply: str = "answer"):
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages, temperature=None, json_mode=False):
        self.calls.append(messages)
        return self.reply


CHUNKS = [
    {"id": "a", "title": "Present Perfect", "text": "have has done result news question ever already"},
    {"id": "b", "title": "Past Simple", "text": "did yesterday ago finished action"},
    {"id": "c", "title": "Must Have To", "text": "must have to obligation duty rule necessity"},
]


def tutor_for(fake_chat=None, embedder=HashEmbedder(), **kwargs):
    return RAGGrammarTutor(
        chat=fake_chat or FakeChat(),
        embedder=embedder,
        chunks=CHUNKS,
        **kwargs,
    )


# --- корпус -----------------------------------------------------------------

def test_corpus_integrity():
    ids = [c["id"] for c in GRAMMAR_CHUNKS]
    assert len(ids) >= 30, "корпус должен давать заявленный объём правил"
    assert len(ids) == len(set(ids)), "id правил должны быть уникальны"
    for chunk in GRAMMAR_CHUNKS:
        assert set(chunk) == {"id", "title", "text"}, f"структура чанка {chunk!r}"
        assert chunk["title"].strip()
        assert chunk["text"].strip()


# --- cosine ------------------------------------------------------------------

def test_cosine_identical_is_one():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_zero_vector_safe():
    assert cosine([], [1.0]) == 0.0


# --- search ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_ranks_by_similarity():
    tutor = tutor_for()
    hits = await tutor.search("Did you finish the lesson yesterday?")
    assert hits[0][0]["id"] == "b", "хвост про прошлое должен попасть в Past Simple"

    hits = await tutor.search("I must have to do my duty")
    assert hits[0][0]["id"] == "c"


@pytest.mark.asyncio
async def test_search_returns_top_k_only():
    tutor = tutor_for()
    hits = await tutor.search("yesterday finished", top_k=1)
    assert len(hits) == 1


# --- роутинг по порогу -------------------------------------------------------

@pytest.mark.asyncio
async def test_answer_rag_mode_with_citations():
    chat = FakeChat()
    tutor = tutor_for(chat, threshold=0.30, top_k=3)
    text, mode, citations = await tutor.answer("Explain must and have to, obligation and duty")
    assert mode == "rag"
    assert text == "answer"
    assert citations and citations[0][0] == "Must Have To"
    assert chat.calls and "Контекст:" in chat.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_answer_chat_mode_when_no_match():
    tutor = tutor_for(threshold=0.80)
    _, mode, citations = await tutor.answer("zzzz qqqq totally unrelated blah")
    assert mode == "chat"
    assert citations == []
    assert tutor._vectors is not None


# --- фоллбэк -----------------------------------------------------------------

class FailingEmbedder:
    async def __call__(self, texts):
        raise EmbeddingsError("network down")


@pytest.mark.asyncio
async def test_answer_falls_back_to_chat_on_embedding_failure():
    chat = FakeChat(reply="let's just talk")
    tutor = tutor_for(chat, embedder=FailingEmbedder())
    text, mode, citations = await tutor.answer("Hello, how are you?")
    assert mode == "chat"
    assert text == "let's just talk"
    assert citations == []
    assert "как обычно" in chat.calls[0][0]["content"]

    await tutor.answer("Second question")
    assert len(chat.calls) == 2, "фоллбэк должен работать повторно"


class NoisyEmbedder:
    async def __call__(self, texts):
        raise RuntimeError("provider 500")


@pytest.mark.asyncio
async def test_answer_handles_unexpected_embedding_error():
    tutor = tutor_for(embedder=NoisyEmbedder())
    text, mode, _ = await tutor.answer("anything")
    assert mode == "chat"
    assert text == "answer"


# --- build_messages ----------------------------------------------------------

def test_build_messages_with_interests():
    profile = {"level": "A2", "interests": "футбол, музыка"}
    msgs = build_messages("расскажи про артикль", profile, [CHUNKS[0]])
    system = msgs[0]["content"]
    assert msgs[1]["content"] == "расскажи про артикль"
    assert "футбол" in system and "музыка" in system
    assert "Контекст:" in system and "Present Perfect" in system


def test_build_messages_without_interests_uses_classic_examples():
    msgs = build_messages("q", {"level": "B1", "interests": []}, [])
    assert "классические примеры" in msgs[0]["content"]
    assert "Контекст:" not in msgs[0]["content"]
    assert "как обычно" in msgs[0]["content"]


def test_build_messages_preserves_profile_level():
    msgs = build_messages("q", {"level": "C1", "interests": "код"}, [CHUNKS[1]])
    assert "C1" in msgs[0]["content"]


# --- интеграция с корпусом ---------------------------------------------------

@pytest.mark.asyncio
async def test_rag_tutor_works_with_real_corpus():
    chat = FakeChat()
    tutor = RAGGrammarTutor(chat=chat, embedder=HashEmbedder(), threshold=0.30)
    text, mode, citations = await tutor.answer("Объясни Present Perfect: have, has, ever, already")
    assert mode in {"rag", "chat"}  # детерминированный фоллбэк не важен
    assert text == "answer"
    assert tutor.corpus_size == len(GRAMMAR_CHUNKS)