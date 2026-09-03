"""Test doubles.

The whole turn pipeline is tested without touching a model. That is not only for speed.
It is the only way to assert deterministic things about a stochastic system. `FakeOllama`
returns scripted replies, so a test can prove that a reply containing "I'm here for you"
gets rejected and regenerated, which is impossible to assert reliably against real
inference.
"""

from __future__ import annotations

import getpass
import json
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from ollie.store import Store

ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config: pytest.Config) -> None:
    """Use a project-local temp root when the system one has become unusable.

    pytest keeps its scratch directories under `<system temp>/pytest-of-<user>`. If that
    directory ends up with permissions that deny its own owner, which happens on Windows
    when repeated cleanups are interrupted, every test in the run fails during fixture
    setup with `PermissionError` and a path that has nothing to do with the code under
    test. It is a genuinely confusing hour for anyone who meets it for the first time.

    So probe it, and fall back to a directory inside the checkout. This says loudly what it
    did rather than hiding it: the machine still has a broken temp directory, and the
    warning carries the command that repairs it.
    """
    if config.option.basetemp:
        return  # someone chose one explicitly; do not second-guess them

    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - getuser consults several backends, any can fail
        user = "unknown"
    root = Path(tempfile.gettempdir()) / f"pytest-of-{user}"

    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".ollie-write-probe"
        probe.mkdir(exist_ok=True)
        probe.rmdir()
        return
    except OSError as exc:
        fallback = ROOT / ".test-tmp" / "pytest"
        fallback.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(fallback)
        config.issue_config_time_warning(
            pytest.PytestWarning(
                f"{root} is not usable ({exc.__class__.__name__}: {exc}), so temporary "
                f"files are going to {fallback} instead.\n"
                f"To repair it, from an Administrator prompt:\n"
                f'    takeown /F "{root}" /R /D Y && rmdir /S /Q "{root}"'
            ),
            stacklevel=2,
        )


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
def store(tmp_path: Path) -> Iterator[Store]:
    # A fixed key keeps the encrypted columns exercised without touching the Keychain.
    opened = Store(tmp_path / "test.db", key=b"0" * 32)
    yield opened
    # Closing is not tidiness, it is what makes the suite work on Windows. POSIX lets you
    # unlink a file that is still open; Windows refuses, so an unclosed connection leaves
    # test.db, test.db-wal and test.db-shm locked. pytest keeps the last three tmp_path
    # trees and deletes the rest, that delete then fails, and the debris accumulates until
    # the whole temp root is unusable and every test errors during setup rather than
    # anywhere near the code that caused it.
    opened.close()


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
