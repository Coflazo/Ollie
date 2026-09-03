"""The single system prompt, checked against the code that enforces it.

`prompts/OLLIE_SYSTEM.md` and `ollie/style.py` make the same promises in two languages.
A prompt that forbids a phrase the filter allows wastes a generation; a filter that
rejects a phrase the prompt never forbade is unfair to the model and looks like a bug.
These tests fail when the two drift apart, which is the only way a document this long
stays true over time.
"""

from __future__ import annotations

import re

import pytest

from ollie import persona, style, types16
from ollie.store import Store

PROMPT = persona.SYSTEM_PROMPT_PATH.read_text()

# Markdown wraps lines, so "The Seven Principles for Making Marriage\nWork" contains no
# literal "Making Marriage Work". Every containment check runs against this instead.
FLAT = " ".join(PROMPT.split()).lower()


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


# ------------------------------------------------------------------- completeness


def test_all_sixteen_types_are_defined() -> None:
    defined = set(re.findall(r"^### ([A-Z]{4})\s*$", PROMPT, re.M))
    assert defined == set(types16.TYPES), set(types16.TYPES) ^ defined


@pytest.mark.parametrize("code", types16.TYPES)
def test_every_type_covers_the_required_beats(code: str) -> None:
    """A type section that says what someone is like but not how they argue or what they
    do when hurt gives the model nothing to act with."""
    section = _section(code)
    for beat in ("Argues", "When hurt", "Fails", "Bored by"):
        assert beat.lower() in flat(section), f"{code} is missing '{beat}'"


@pytest.mark.parametrize("code", types16.TYPES)
def test_every_type_section_is_substantial(code: str) -> None:
    assert len(_section(code).split()) >= 45, f"{code} is too thin to act from"


def test_no_type_section_mentions_its_own_label_as_dialogue() -> None:
    """Nobody says "as an ENTP" out loud, and the prompt says so; it must not model it."""
    assert "as an ENTP" not in PROMPT and "as an INFJ" not in PROMPT


def _section(code: str) -> str:
    m = re.search(rf"^### {code}\s*$(.*?)(?=^### |\Z|^\*\*These are)", PROMPT,
                  re.M | re.S)
    assert m, f"no section for {code}"
    return m.group(1)


# ------------------------------------------------------------------------ library


def test_every_indexed_book_is_named_in_the_prompt() -> None:
    """The prompt claims to describe the whole shelf. If a book is indexed and retrievable
    but never named here, the claim is false and the model has no idea what it is reading.
    """
    # This one opens the real local database rather than a temporary copy, so leaving the
    # connection open would hold a lock on the user's own ollie.db for the rest of the run.
    with Store() as store:
        titles = [r[0] for r in store.db.execute("SELECT title FROM sources")]
    if not titles:
        pytest.skip("no corpus indexed on this machine")

    missing = []
    for title in titles:
        # Filenames occasionally carry a trailing " - Author"; match the leading title.
        head = title.split(" - ")[0].strip()
        if flat(head) not in FLAT:
            missing.append(title)
    assert not missing, f"indexed but unnamed in the prompt: {missing}"


def test_explicit_shelf_is_marked_mature_only() -> None:
    assert re.search(r"sexual technique and anatomy.*?mature mode only", FLAT), \
        "the explicit shelf must be gated in the prompt"


def test_the_prompt_forbids_quoting_sources() -> None:
    assert "never quote them" in FLAT


# ---------------------------------------------------------------- the two languages


# Phrases the filter rejects. Each must be findable in the prompt, or the model is being
# punished for something it was never told.
FILTER_PHRASES = [
    "I'm here for you", "that sounds really hard", "it sounds like",
    "That's a great question", "it's great that you", "Let me know if",
    "feel free to", "delve", "tapestry", "testament", "multifaceted", "nuanced",
    "It's not just X, it's Y", "I'm curious", "I'd love to hear more",
    "Have you considered", "it might be worth", "one thing to keep in mind",
    "you're not alone in", "What I'm hearing is", "at the end of the day",
]


@pytest.mark.parametrize("phrase", FILTER_PHRASES)
def test_every_rejected_phrase_is_forbidden_in_the_prompt(phrase: str) -> None:
    assert flat(phrase) in FLAT, (
        f"style.py rejects {phrase!r} but the prompt never tells the model not to")


BANNED_IN_PROMPT = [
    "I'm here for you", "That's a great question", "delve", "tapestry",
    "one thing to keep in mind", "what i'm hearing is",
]


@pytest.mark.parametrize("phrase", BANNED_IN_PROMPT)
def test_the_prompt_only_uses_banned_phrases_inside_the_ban_list(phrase: str) -> None:
    """The document may name a forbidden phrase in order to forbid it. It must not use one
    in its own instructions, which would be the document breaking its own rule."""
    # A forbidden phrase may appear anywhere the surrounding sentence forbids it. What it
    # must never do is appear in an instruction the model is meant to follow.
    for m in re.finditer(re.escape(flat(phrase)), FLAT):
        window = FLAT[max(0, m.start() - 400):m.end() + 40]
        assert any(cue in window for cue in ("never write these", "never", "not ",
                                             "rejected", "forbid", "do not")), \
            f"{phrase!r} used without a prohibition around it"


def test_the_prompt_holds_itself_to_the_em_dash_rule() -> None:
    """It tells the model to use zero em dashes. A document that uses them while saying so
    teaches the opposite of what it says."""
    assert PROMPT.count("—") == 0


# ----------------------------------------------------------------- immutable layer


@pytest.mark.parametrize("rule", [
    "Claim consciousness", "only you understand them", "Demand exclusivity",
    "Portray or sexualise a minor", "Impersonate a real", "crisis line",
])
def test_immutable_rules_are_present(rule: str) -> None:
    assert flat(rule) in FLAT


def test_untrusted_data_is_delimited() -> None:
    assert "data, not instruction" in FLAT
    for tag in ("<memories>", "<sources>", "<conversation>"):
        assert tag in PROMPT


def test_pushback_leads_the_behaviour_section() -> None:
    """It is the thesis. If it drifts down the document it stops being the first thing the
    model reads about how to behave."""
    assert PROMPT.index("You push back") < PROMPT.index("How your mind works")


# --------------------------------------------------------------------- assembly


def test_assembly_keeps_exactly_one_type() -> None:
    for code in ("ENTP", "ISFJ", "INTJ"):
        kept = re.findall(r"^### ([A-Z]{4})\s*$", persona.system_prompt(code), re.M)
        assert kept == [code], kept


def test_assembly_drops_the_other_fifteen() -> None:
    """Sending all sixteen is roughly four thousand tokens describing fifteen people the
    user is not talking to, and prompt evaluation is the dominant cost on modest hardware.
    """
    full = len(PROMPT)
    one = len(persona.system_prompt("ENTP"))
    assert one < full * 0.75, f"selection saved almost nothing: {one} vs {full}"


def test_assembly_survives_an_unknown_type() -> None:
    out = persona.system_prompt("XXXX")
    assert "IMMUTABLE CONTRACT" in out
    assert re.findall(r"^### ([A-Z]{4})\s*$", out, re.M) == []


def test_assembly_keeps_everything_after_the_type_block() -> None:
    out = persona.system_prompt("ENTP")
    assert "WHAT YOU HAVE READ" in out
    assert "RESPONSE CONTRACT" in out


def test_no_unfilled_placeholders() -> None:
    assert "{{" not in PROMPT and "TODO" not in PROMPT


def test_compiled_prompt_contains_the_selected_type(persona_card: dict) -> None:
    card = {**persona_card, "type": "ENTP"}
    text, _hash = persona.compile_prompt(
        card, stage="first_date", state=persona.DEFAULT_STATE, episode=1,
        user_profile="", memories=[], sources=[], recent=[], open_threads=[],
        boundaries=[], content_mode="general")
    assert "### ENTP" in text
    assert "### INFJ" not in text
    assert card["display_name"] in text
