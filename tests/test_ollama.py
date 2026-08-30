"""Handling what models actually return, as opposed to what they are supposed to return.

Qwen 3 is a reasoning model and it is what the demo machine runs. Newer Ollama puts the
reasoning in a separate field, which we never read; older builds and imperfect templates
inline it in the content. Left alone that reaches the user as the character monologuing
about how to be in character, and it breaks json.loads on every structured call.
"""

from __future__ import annotations

import pytest

from ollie.ollama import parse_json_object, strip_thinking


# ------------------------------------------------------------------ thinking blocks


def test_plain_text_is_untouched() -> None:
    assert strip_thinking("no. that's a bad idea.") == "no. that's a bad idea."
    assert strip_thinking("") == ""


@pytest.mark.parametrize("tag", ["think", "thinking", "reasoning"])
def test_reasoning_blocks_are_removed(tag: str) -> None:
    raw = f"<{tag}>The user seems upset. I should be blunt but kind.</{tag}>that's rubbish."
    assert strip_thinking(raw) == "that's rubbish."


def test_reasoning_is_case_insensitive() -> None:
    assert strip_thinking("<THINK>hmm</THINK>ok.") == "ok."


def test_multiline_reasoning_is_removed() -> None:
    raw = """<think>
    They mentioned Thursday earlier.
    I should bring that up without announcing it.
    </think>
    so what happened thursday."""
    assert strip_thinking(raw) == "so what happened thursday."


def test_unterminated_reasoning_is_dropped() -> None:
    """Generation cut off mid-thought. Showing half a monologue is worse than showing
    nothing, and the caller substitutes a fallback for an empty reply."""
    assert "should be blunt" not in strip_thinking("<think>I should be blunt about this")


def test_angle_brackets_in_normal_text_survive() -> None:
    """The character can talk about code without being mangled."""
    text = "you wrote <div> and then complained the page was empty. amazing."
    assert strip_thinking(text) == text


def test_multiple_blocks_are_all_removed() -> None:
    assert strip_thinking("<think>a</think>hm.<think>b</think> ok.") == "hm. ok."


# -------------------------------------------------------------------- json recovery


def test_bare_object_parses() -> None:
    assert parse_json_object('{"memories": []}') == {"memories": []}


def test_markdown_fenced_object_parses() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('```\n{"a": 1}\n```') == {"a": 1}


def test_object_after_a_preamble_parses() -> None:
    """Some models explain themselves before complying. Recovering means a memory still
    gets recorded when the model is untidy rather than wrong."""
    assert parse_json_object('Here is the JSON you asked for:\n{"a": 1}') == {"a": 1}


def test_object_after_reasoning_parses() -> None:
    assert parse_json_object('<think>what did they say</think>{"a": 1}') == {"a": 1}


def test_nested_objects_survive_extraction() -> None:
    raw = 'sure:\n{"state_delta": {"trust": 0.04}, "memories": [{"kind": "user_fact"}]}'
    parsed = parse_json_object(raw)
    assert parsed is not None
    assert parsed["state_delta"]["trust"] == 0.04


@pytest.mark.parametrize("raw", ["", "no json here at all", "{broken", "[1, 2, 3]", "null"])
def test_unrecoverable_output_returns_none(raw: str) -> None:
    """A JSON array is valid JSON but not the object the schema promised, so it is
    rejected rather than handed on for the caller to trip over."""
    assert parse_json_object(raw) is None
