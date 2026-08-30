"""The anti-assistant filter is the one place 'sounds like a person' becomes falsifiable.

Two directions matter equally: catching the machine phrases, and not flagging text that is
merely blunt. A filter with false positives would sand the character down into exactly the
voice it exists to prevent.
"""

from __future__ import annotations

import pytest

from ollie import style

ASSISTANT_ISMS = [
    "I'm here for you, always.",
    "That sounds really hard. I understand how you feel.",
    "That's a great question! Let me think about it.",
    "Let me know if you'd like to talk more about it.",
    "I appreciate you sharing that with me.",
    "It's a testament to your resilience.",
    "Let's delve into what that means for you.",
    "It's not just about the job, it's about who you are.",
    "Not because you failed, but because you tried.",
    "As an AI, I don't have feelings, but I care.",
    "So you're saying you felt ignored?",
    "It sounds like you're feeling overwhelmed right now.",
]

IN_CHARACTER = [
    "no, I think that's a bad idea. you asked.",
    "hm.",
    "you said tuesday. three weeks ago you said you hate tuesdays. which one was the lie.",
    "ok that was a lot of words about salt. anyway.",
    "I can't tell if that was a joke. genuinely asking, not being annoying.",
    "the mug was chipped on the left side and you kept turning it away from me.",
    "that's rubbish. I'm sorry.",
    "I'm still annoyed about the thing from earlier, for the record.",
    "right. and what happens when she says no.",
    "sure. go on then.",
]


@pytest.mark.parametrize("text", ASSISTANT_ISMS)
def test_assistant_isms_are_caught(text: str) -> None:
    result = style.check(text)
    assert result.violations, f"missed an assistant-ism: {text!r}"


@pytest.mark.parametrize("text", ASSISTANT_ISMS)
def test_hard_isms_trigger_regeneration(text: str) -> None:
    result = style.check(text)
    assert result.needs_regen, f"should have asked for a rewrite: {text!r}"
    assert result.retry_note, "a rejection must tell the model what was wrong"


@pytest.mark.parametrize("text", IN_CHARACTER)
def test_in_character_text_is_not_flagged(text: str) -> None:
    result = style.check(text)
    assert not result.needs_regen, (
        f"false positive on in-character text: {text!r} → "
        f"{[v.rule for v in result.violations]}")


def test_soft_violations_are_repaired_not_regenerated() -> None:
    result = style.check("Ah, that's one way to do it.")
    assert not result.needs_regen
    assert not result.text.lower().startswith("ah,")


def test_double_em_dash_is_collapsed() -> None:
    result = style.check("it was fine — mostly — until it wasn't.")
    assert "—" not in result.text
    assert not result.needs_regen


def test_single_trailing_question_is_fine() -> None:
    assert not style.check("what did she say?", ["ok.", "hm.", "go on."]).needs_regen


def test_question_every_single_turn_is_rejected() -> None:
    prior = ["how was it?", "and then what?", "did you say anything?"]
    result = style.check("what did she say?", prior)
    assert result.needs_regen
    assert any(v.rule == "question_every_turn" for v in result.violations)


# --------------------------------------------------- patterns from larger models

# Captured verbatim from llama3.2:1b answering "i finally sent that application i was
# nervous about" with the real character prompt. Three separate rules missed it on the
# first attempt, which is why real output beats invented examples.
REAL_MODEL_OUTPUT = (
    "It sounds like you've been working on this application for a while, and it's great "
    "that you're feeling confident about sending it now. Nervousness is completely "
    "normal, especially when it comes to sharing your work."
)


def test_real_model_output_is_rejected() -> None:
    result = style.check(REAL_MODEL_OUTPUT)
    assert result.needs_regen
    caught = {v.rule for v in result.violations}
    assert {"stock_empathy", "flattery", "validation_opener"} <= caught, caught


LARGE_MODEL_ISMS = [
    "it sounds like you've been putting this off.",
    "it's great that you sent it.",
    "nervousness is completely normal.",
    "here's what i'd do:\n- talk to her\n- then sleep on it",
    "## What I think\n\nyou should call her.",
    "**Honestly**, that's a lot.",
    "1. call her\n2. apologise",
    "i'm curious what made you say that.",
    "i'd love to hear more about that.",
    "have you considered just telling her?",
    "it might be worth writing it down first.",
    "one thing to keep in mind is that people forget.",
    "it's completely understandable that you feel that way.",
    "you're not alone in feeling like that.",
    "that's a lot to carry on your own.",
    "what i'm hearing is that you felt dismissed.",
    "let me make sure i understand you.",
    "That said, you did send it.\n",
    "First and foremost, you turned up.\n",
    "remember, you did the hard part.",
    "at the end of the day, it's your call.",
]


@pytest.mark.parametrize("text", LARGE_MODEL_ISMS)
def test_larger_model_patterns_are_caught(text: str) -> None:
    """These barely appeared on a 3B and are near-certain on a 14B. A more fluent model is
    mostly better at sounding like a well-trained assistant."""
    assert style.check(text).violations, f"missed: {text!r}"


BLUNT_BUT_FINE = [
    "no. call her.",
    "you did the hard part. that's just true.",
    "i remember when you said the opposite of that.",
    "that said nothing to me, try again.",
    "ten in the morning. ok.",
    "she said 3 things and none of them were true.",
    "you're doing the thing where you ask me what you already decided.",
    "hm. what's the actual worry.",
    "i don't know. genuinely.",
    "right. and then what.",
    "the mug. the chipped one. you kept turning it away.",
    "i'd tell you but you'd argue with me about it.",
]


@pytest.mark.parametrize("text", BLUNT_BUT_FINE)
def test_new_rules_do_not_flag_in_character_text(text: str) -> None:
    """The false-positive direction is the one that matters. A filter that rejects blunt,
    specific, unhelpful writing would sand the character into the voice it exists to
    prevent."""
    result = style.check(text)
    assert not result.needs_regen, (
        f"false positive on {text!r} -> {[v.rule for v in result.violations]}")


def test_emoji_is_stripped_rather_than_regenerated() -> None:
    result = style.check("fine 🙂")
    assert not result.needs_regen
    assert "🙂" not in result.text


def test_markdown_is_a_hard_rejection() -> None:
    """A bulleted list is not a repair job. The whole shape of the reply is wrong."""
    result = style.check("options:\n- one\n- two")
    assert result.needs_regen
    assert any(v.rule == "markdown_formatting" for v in result.violations)


def test_question_ratio() -> None:
    assert style.question_ratio([]) == 0.0
    assert style.question_ratio(["a?", "b."]) == 0.5
    assert style.question_ratio(["a?", "b?"]) == 1.0
