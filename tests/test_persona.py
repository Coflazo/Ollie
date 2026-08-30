"""Candidate generation, and the one part of it that could not be left to instructions."""

from __future__ import annotations

import pytest

from ollie import persona
from ollie.persona import CANDIDATE_SCHEMA, _schema_for


def _props(schema: dict) -> dict:
    return schema["properties"]["candidates"]["items"]["properties"]


@pytest.mark.parametrize("seeking,expected", [
    ("men", "he/him"), ("Men", "he/him"), ("  male  ", "he/him"), ("guys", "he/him"),
    ("women", "she/her"), ("FEMALE", "she/her"), ("girls", "she/her"),
    ("nonbinary", "they/them"),
])
def test_an_unambiguous_answer_pins_the_pronouns(seeking: str, expected: str) -> None:
    """Asking was not enough.

    Told "men", the model returned a woman or a they/them in two runs out of two, and
    strengthening the wording twice did not move it. Ollama enforces the schema during
    decoding, so the enum makes a mismatch impossible rather than discouraged.
    """
    assert _props(_schema_for(seeking))["pronouns"]["enum"] == [expected]


def test_pronouns_are_decided_before_the_name() -> None:
    """Otherwise the model writes "Nora" and is then forced into he/him after the fact."""
    assert list(_props(_schema_for("men")))[0] == "pronouns"


@pytest.mark.parametrize("seeking", ["anyone", "everyone", "both", "", "   ",
                                     "whoever is interesting", "i don't mind"])
def test_an_open_answer_constrains_nothing(seeking: str) -> None:
    """Guessing at what someone meant is worse than leaving it to the prompt."""
    assert _schema_for(seeking) is CANDIDATE_SCHEMA


def test_constraining_does_not_mutate_the_shared_schema() -> None:
    """`_schema_for` runs once per onboarding against a module-level dict."""
    _schema_for("men")
    _schema_for("women")
    assert _props(CANDIDATE_SCHEMA)["pronouns"] == {"type": "string"}


def test_every_field_survives_the_rebuild() -> None:
    assert set(_props(_schema_for("men"))) == set(_props(CANDIDATE_SCHEMA))


def test_the_prompt_still_asks_as_well_as_the_schema() -> None:
    """The enum only covers the unambiguous answers; everything else rests on the ask."""
    assert "seeking" in persona.CANDIDATE_PROMPT
