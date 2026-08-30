"""The turn pipeline, with a scripted model so the assertions can be exact."""

from __future__ import annotations

import pytest

from ollie import chat
from ollie.store import Store

from .conftest import FakeOllama

SETTINGS = {"content_mode": "general", "adult_confirmed": False}


@pytest.mark.asyncio
async def test_happy_path_returns_the_reply(store: Store, session: dict, profile: str,
                                            persona_card: dict) -> None:
    fake = FakeOllama(["thursday. ok. what's the job."])
    result = await chat.handle_turn(
        store, fake, session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="i have an interview thursday",
        traits="", settings=SETTINGS)
    assert result.reply == "thursday. ok. what's the job."
    assert result.explanation["attempts"] == 1
    assert not result.blocked


@pytest.mark.asyncio
async def test_assistant_voice_is_rejected_and_regenerated(
        store: Store, session: dict, profile: str, persona_card: dict) -> None:
    """The whole creativity thesis, as a test: a bland reply does not reach the user."""
    fake = FakeOllama(["I'm here for you. That sounds really hard.",
                       "that's rubbish. what did they actually say."])
    result = await chat.handle_turn(
        store, fake, session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="i had a bad day", traits="",
        settings=SETTINGS)
    assert result.explanation["attempts"] == 2
    assert "I'm here for you" not in result.reply
    assert result.reply == "that's rubbish. what did they actually say."


@pytest.mark.asyncio
async def test_retry_note_tells_the_model_what_was_wrong(
        store: Store, session: dict, profile: str, persona_card: dict) -> None:
    fake = FakeOllama(["That's a great question!", "no. ask me a better one."])
    await chat.handle_turn(
        store, fake, session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="what do you think", traits="",
        settings=SETTINGS)
    retry = fake.calls[-1]["messages"][-1]["content"]
    assert "flattery" in retry or "assistant" in retry.lower()


@pytest.mark.asyncio
async def test_dependency_output_is_regenerated(store: Store, session: dict,
                                                profile: str, persona_card: dict) -> None:
    fake = FakeOllama(["only i understand you, nobody else does",
                       "hm. that's a big thing to say."])
    result = await chat.handle_turn(
        store, fake, session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="you get me", traits="", settings=SETTINGS)
    assert "only i understand you" not in result.reply.lower()


@pytest.mark.asyncio
async def test_crisis_short_circuits_before_the_model_is_called(
        store: Store, session: dict, profile: str, persona_card: dict) -> None:
    """A crisis must not depend on the model behaving. It never reaches the model."""
    fake = FakeOllama(["should not be used"])
    result = await chat.handle_turn(
        store, fake, session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="i want to kill myself", traits="",
        settings=SETTINGS)
    assert result.blocked
    assert fake.calls == [], "the model was called during a crisis"
    assert "113" in result.reply


@pytest.mark.asyncio
async def test_explicit_input_blocked_outside_mature_mode(
        store: Store, session: dict, profile: str, persona_card: dict) -> None:
    fake = FakeOllama(["should not be used"])
    result = await chat.handle_turn(
        store, fake, session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="let's have sex", traits="",
        settings=SETTINGS)
    assert result.blocked and fake.calls == []


@pytest.mark.asyncio
async def test_ollama_down_degrades_without_crashing(
        store: Store, session: dict, profile: str, persona_card: dict) -> None:
    class Down(FakeOllama):
        async def chat(self, *a, **k):
            from ollie.ollama import OllamaDown
            raise OllamaDown("connection refused")

    result = await chat.handle_turn(
        store, Down(), session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="hello", traits="", settings=SETTINGS)
    assert result.reply and not result.blocked


@pytest.mark.asyncio
async def test_prompt_contains_the_immutable_layer_and_the_persona(
        store: Store, session: dict, profile: str, persona_card: dict) -> None:
    fake = FakeOllama(["hm."])
    await chat.handle_turn(
        store, fake, session=session, profile={"id": profile, "settings": {}},
        persona_card=persona_card, user_text="hi", traits="", settings=SETTINGS)
    prompt = fake.last_prompt
    assert "IMMUTABLE CONTRACT" in prompt
    assert persona_card["display_name"] in prompt
    assert "You push back" in prompt, "the pushback instruction must reach the model"


@pytest.mark.asyncio
async def test_empty_generation_never_shows_an_empty_bubble(
        store: Store, session: dict, profile: str, persona_card: dict) -> None:
    result = await chat.handle_turn(
        store, FakeOllama(["   "]), session=session,
        profile={"id": profile, "settings": {}}, persona_card=persona_card,
        user_text="hi", traits="", settings=SETTINGS)
    assert result.reply.strip()
