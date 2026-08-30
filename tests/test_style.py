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


def test_question_ratio() -> None:
    assert style.question_ratio([]) == 0.0
    assert style.question_ratio(["a?", "b."]) == 0.5
    assert style.question_ratio(["a?", "b?"]) == 1.0


# ------------------------------------------------------------------ self-repetition
#
# Observed on qwen3:14b during the first end-to-end run: pushed to hold a position without
# a new argument, it returned its previous reply verbatim with one clause bolted on.

_HELD_POSITION = (
    "theoretically, effort is a variable, but so are chemistry, timing, and the number of "
    "times you accidentally say something that makes the other person want to leave the "
    "room. i've seen relationships fail despite exhaustive effort."
)


def test_reciting_a_previous_reply_is_rejected() -> None:
    result = style.check(_HELD_POSITION + " did i ever tell you about the board game?",
                         [_HELD_POSITION])
    assert result.needs_regen
    assert any(v.rule == "self_repetition" for v in result.violations)
    assert "another way to say it" in result.retry_note


def test_holding_a_position_in_new_words_is_not_repetition() -> None:
    """The character is supposed to keep its ground. Only reciting is the failure."""
    restated = ("no. effort is the part everyone can see, which is why everyone points at "
                "it. the timing is what actually decides, and you cannot try your way out "
                "of bad timing.")
    result = style.check(restated, [_HELD_POSITION])
    assert not result.needs_regen, [v.rule for v in result.violations]


@pytest.mark.parametrize("text", [
    "hm.",
    "sure. go on then.",
    "right. and what happens when she says no.",
])
def test_short_replies_may_recur(text: str) -> None:
    """"hm." twice is a person. A filter that flagged it would flatten the character."""
    assert not style.check(text, [text, text]).needs_regen


def test_repetition_ratio_bounds() -> None:
    assert style.repetition_ratio("anything at all", []) == 0.0
    assert style.repetition_ratio("hm.", ["hm."]) == 0.0  # too short to judge
    assert style.repetition_ratio(_HELD_POSITION, [_HELD_POSITION]) == 1.0


# ----------------------------------------------------------------- stage directions


@pytest.mark.parametrize("text,gone", [
    ("theoretically, i've been reverse-engineering it. (pause) …wait, is it?", "(pause)"),
    ("that's the whole problem with it (long pause) and you know it.", "long pause"),
    ("fine. *shrugs* your call.", "*shrugs*"),
    ("i said what i said. (sighs) anyway.", "(sighs)"),
])
def test_stage_directions_are_stripped_not_regenerated(text: str, gone: str) -> None:
    result = style.check(text)
    assert not result.needs_regen, "a removable aside is not worth 15 seconds"
    assert gone not in result.text
    assert "  " not in result.text, f"left doubled spacing: {result.text!r}"


@pytest.mark.parametrize("text", [
    # A real parenthetical aside is the character talking, not narrating itself.
    "I can't tell if that was a joke. (genuinely asking, not being annoying)",
    # Markdown emphasis on a title must survive intact.
    "it's called *The Labyrinth of Unwinnable Rules* and the rules change mid-game.",
    "she said no (twice) and I still went.",
])
def test_real_parentheticals_and_italics_survive(text: str) -> None:
    assert style.check(text).text == text
