"""Test doubles.

The whole turn pipeline is tested without touching a model. That is not only for speed.
It is the only way to assert deterministic things about a stochastic system. `FakeOllama`
returns scripted replies, so a test can prove that a reply containing "I'm here for you"
gets rejected and regenerated, which is impossible to assert reliably against real
inference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ollie.store import Store


class FakeOllama:
    """Scripted stand-in for `ollie.ollama.Ollama`.

    `replies` is consumed in order by `chat`; `json_replies` by `chat_json`. Both record
    what they were called with so tests can assert on the assembled prompt.
    """

    def __init__(self, replies: list[str] | None = None,
                 json_replies: list[dict | None] | None = None) -> None:
        self.replies = list(replies or [])
        self.json_replies = list(json_replies or [])
        self.calls: list[dict] = []

    async def chat(self, model, messages, *, temperature=0.85, num_ctx=4096,
                   schema=None, stop=None, think=False) -> str:
        self.calls.append({"model": model, "messages": messages, "schema": schema,
                           "think": think})
        return self.replies.pop(0) if self.replies else "hm."

    async def chat_json(self, model, messages, schema, num_ctx=4096):
        self.calls.append({"model": model, "messages": messages, "schema": schema})
        return self.json_replies.pop(0) if self.json_replies else None

    async def alive(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    @property
    def last_prompt(self) -> str:
        return self.calls[-1]["messages"][0]["content"] if self.calls else ""


@pytest.fixture
def store(tmp_path: Path) -> Store:
    # A fixed key keeps the encrypted columns exercised without touching the Keychain.
    return Store(tmp_path / "test.db", key=b"0" * 32)


@pytest.fixture
def profile(store: Store) -> str:
    return store.create_profile({"content_mode": "general"}, {"big_five": {}}, "Cagan")


@pytest.fixture
def persona_card() -> dict:
    from ollie import persona
    return persona._fallback_card(0)


@pytest.fixture
def session(store: Store, profile: str, persona_card: dict) -> dict:
    from ollie import persona
    pid = store.create_persona(profile, persona_card, "hash")
    state = {**persona.DEFAULT_STATE, "stage": "first_date"}
    sid = store.create_session(profile, pid, "fake:1b", 4096, state)
    return {"id": sid, "persona_id": pid, "state": state, "stage": "first_date",
            "episode_number": 1, "model_tag": "fake:1b", "context_cap": 4096}
