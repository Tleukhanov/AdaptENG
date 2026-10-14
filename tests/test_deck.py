import json

import pytest

from core.deck import (
    DECK_PRESETS,
    Deck,
    DeckService,
    QuizItem,
    Slide,
    VocabCard,
    build_deck_prompt,
    deck_from_json,
    generate_deck,
)
from providers.base import LLMProvider


VALID_DECK = {
    "title": "Coffee Around the World",
    "subtitle_ru": "Путешествие по кофейным традициям",
    "preset": "mixed",
    "emoji": "☕",
    "slides": [
        {"headline": "Why coffee?", "body": "Coffee is a popular morning drink.", "emoji": "🌅"},
        {"headline": "Espresso in Italy", "body": "Italians enjoy espresso at the bar.", "emoji": "🇮🇹"},
    ],
    "vocabulary": [
        {"word": "brew", "translation": "заваривать", "example": "I brew coffee.", "transcription": "/bruː/"},
        {"word": "roast", "translation": "обжаривать", "example": "They roast beans.", "transcription": "/rəʊst/"},
        {"word": "bean", "translation": "зерно", "example": "A bean smells good.", "transcription": "/biːn/"},
    ],
    "quiz": [
        {"question": "What does brew mean?", "options": ["заваривать", "пить", "есть"], "answer_index": 0, "explanation_ru": "To brew — заваривать."},
        {"question": "Where is espresso popular?", "options": ["Italy", "Japan", "Brazil"], "answer_index": 0, "explanation_ru": "Espresso особенно популярен в Италии."},
        {"question": "What is a bean?", "options": ["зерно", "чашка", "ложка"], "answer_index": 0, "explanation_ru": "Bean — зерно кофе."},
    ],
    "dialogue": {
        "scene_ru": "Ты в итальянской кофейне.",
        "lines": [
            {"character": "Barista", "line": "Ciao! Would you like a coffee?"},
            {"character": "You", "line": "Yes, please. I would like an espresso."},
            {"character": "Barista", "line": "Would you like sugar?"},
            {"character": "You", "line": "No, thank you."},
        ],
        "choices": [
            {"line": "Yes, please. I would like an espresso.", "next": 1},
            {"line": "No, thank you. I prefer tea.", "next": 2},
            {"line": "A cappuccino, please.", "next": 1},
            {"line": "Just water, thank you.", "next": 2},
        ],
    },
}

VALID_DECK_JSON = json.dumps(VALID_DECK, ensure_ascii=False)


class FakeLLM(LLMProvider):
    def __init__(self, response: str):
        self.response = response
        self.calls = 0
        self.last_messages = None
        self.last_temperature = None
        self.last_json_mode = None

    async def chat(self, messages, temperature=None, json_mode=False, **kwargs):
        self.calls += 1
        self.last_messages = messages
        self.last_temperature = temperature
        self.last_json_mode = json_mode
        return self.response


@pytest.mark.parametrize("preset", DECK_PRESETS)
async def test_generate_deck_for_every_preset(preset):
    llm = FakeLLM(VALID_DECK_JSON)
    deck = await generate_deck(llm, "Coffee", preset=preset)

    assert deck is not None
    assert deck.title == "Coffee"
    assert deck.subtitle_ru == "Путешествие по кофейным традициям"
    assert deck.preset == preset
    assert llm.calls == 1
    assert llm.last_temperature == 0.7
    assert llm.last_json_mode is True

    if preset in {"presentation", "mixed"}:
        assert len(deck.slides) == 2
    else:
        assert deck.slides == []
    if preset in {"cards", "mixed"}:
        assert len(deck.vocabulary) == 3
        assert deck.vocabulary[0].word == "brew"
        assert deck.vocabulary[0].transcription == "/bruː/"
    else:
        assert deck.vocabulary == []
    if preset in {"quiz", "mixed"}:
        assert len(deck.quiz) == 3
        assert all(0 <= item.answer_index < len(item.options) for item in deck.quiz)
    else:
        assert deck.quiz == []
    if preset in {"dialogue", "mixed"}:
        assert deck.dialogue is not None
        assert deck.dialogue.scene_ru == "Ты в итальянской кофейне."
        assert len(deck.dialogue.lines) == 4
        assert len(deck.dialogue.choices) == 4
    else:
        assert deck.dialogue is None


async def test_invalid_json_returns_none_without_exception():
    for response in ("", "not json", "{broken", "[]", "null"):
        assert await generate_deck(FakeLLM(response), "Coffee") is None


async def test_quiz_drops_missing_or_invalid_answer_index():
    raw = {
        "title": "Quiz",
        "quiz": [
            {"question": "Good", "options": ["one", "two"], "answer_index": 0},
            {"question": "No index", "options": ["one", "two"]},
            {"question": "Too large", "options": ["one", "two"], "answer_index": 2},
            {"question": "One option", "options": ["one"], "answer_index": 0},
            {"question": "Wrong type", "options": ["one", "two"], "answer_index": True},
            "broken",
        ],
    }
    deck = deck_from_json(json.dumps(raw), preset="quiz")

    assert deck is not None
    assert len(deck.quiz) == 1
    assert deck.quiz[0].question == "Good"
    assert deck.quiz[0].answer_index == 0


def test_partial_fields_are_safe_and_defaults_are_used():
    raw = {
        "preset": "cards",
        "vocabulary": [
            {"word": "check"},
            {"unexpected": "value"},
            "broken",
        ],
    }
    deck = deck_from_json(json.dumps(raw))

    assert deck is not None
    assert len(deck.vocabulary) == 1
    assert deck.vocabulary[0].word == "check"
    assert deck.vocabulary[0].translation == ""
    assert deck.vocabulary[0].transcription == ""
    assert deck.title == "English lesson"
    assert deck.emoji == "📚"


def test_vocabulary_example_in_russian_is_cleared():
    raw = {
        "preset": "cards",
        "vocabulary": [
            {
                "word": "humiliate",
                "translation": "унижать",
                "example": "Он унижает её каждое утро.",
            },
            {
                "word": "brew",
                "translation": "заваривать",
                "example": "I brew coffee every morning.",
            },
        ],
    }
    deck = deck_from_json(json.dumps(raw))

    assert deck is not None
    assert len(deck.vocabulary) == 2
    assert deck.vocabulary[0].example == ""
    assert deck.vocabulary[0].word == "humiliate"
    assert deck.vocabulary[1].example == "I brew coffee every morning."


def test_prompt_demands_english_examples():
    messages = build_deck_prompt("Coffee", preset="cards")
    system = messages[0]["content"]
    assert "example" in system
    assert "English" in system
    assert "Cyrillic" in system


def test_prompt_includes_profile_and_weak_areas():
    messages = build_deck_prompt(
        "Coffee",
        preset="mixed",
        profile="Goal: Работа в IT; Interests: chess, travel",
        weak_areas_prompt="Student weak areas (ask about these): Present Perfect",
    )
    system = messages[0]["content"] + messages[1]["content"] + messages[2]["content"]
    assert "Работа в IT" in system
    assert "chess" in system
    assert "Present Perfect" in system


async def test_plan_hint_sets_deck_topic_and_reaches_prompt():
    llm = FakeLLM(VALID_DECK_JSON)
    deck = await generate_deck(
        llm,
        "Old topic",
        plan_hint="Plan lesson 1/12: Travel English. Focus: airport small talk",
    )

    assert deck is not None
    assert deck.title == "Travel English"
    prompt_text = " ".join(message["content"] for message in llm.last_messages)
    assert "LESSON PLAN CONTEXT" in prompt_text
    assert "Travel English" in prompt_text
    assert "airport small talk" in prompt_text


def test_prompt_contains_level_profile_recent_topics_and_character():
    messages = build_deck_prompt(
        "Coffee",
        level="C1",
        profile={"first_name": "Alex", "interests": ["coffee", "travel"], "weak_areas": "articles"},
        recent_topics=["Cooking", "Travel"],
        character_prompt="Be warm and playful.",
        preset="mixed",
    )
    text = " ".join(message["content"] for message in messages)

    assert len(messages) == 3
    assert "advanced (C1)" in text
    assert "Name: Alex" in text
    assert "Interests: coffee, travel" in text
    assert "Cooking" in text
    assert "Be warm and playful" in text
    assert "mixed" in text


def test_deck_json_roundtrip():
    original = Deck(
        title="Chess",
        subtitle_ru="Шахматы",
        preset="mixed",
        emoji="♟️",
        slides=[Slide("Opening", "Control the centre.", "♟️")],
        vocabulary=[VocabCard("opening", "дебют", "Learn an opening.", "/oʊpənɪŋ/")],
        quiz=[QuizItem("What is it?", ["A move", "A game"], 1, "Это ход.")],
    )
    restored = deck_from_json(original.to_json())

    assert restored == original


async def test_service_and_function_use_one_llm_call():
    llm = FakeLLM(VALID_DECK_JSON)
    service_deck = await DeckService(llm).generate("Coffee", preset="cards")

    assert service_deck is not None
    assert service_deck.preset == "cards"
    assert llm.calls == 1
