"""Memory rules, and the episode-to-episode continuity the hackathon actually scores.

`test_fact_survives_rollover_into_next_episode` is the important one: it establishes a
detail in episode one, rolls the context, and asserts the detail is still retrievable and
still in the capsule that opens episode two.
"""

from __future__ import annotations

import pytest

from ollie import chat, memory, retrieve
from ollie.memory import apply_state_delta, classify_sensitivity
from ollie.store import Store

from .conftest import FakeOllama


# ------------------------------------------------------------------ record hygiene


def test_memory_requires_a_source_message(store: Store, profile: str) -> None:
    with pytest.raises(ValueError):
        store.add_memory(profile, "user_fact", "user", "has sister", "Deniz",
                         0.9, 3, "normal", source_message_ids=[])


def test_memory_round_trips_through_encryption(store: Store, profile: str,
                                               session: dict) -> None:
    mid = store.append_message(session["id"], "user", "my sister is called Deniz")
    store.add_memory(profile, "user_fact", "user", "sister is called", "Deniz",
                     0.95, 3, "normal", [mid])
    stored = store.memories(profile)[0]
    assert stored["value"] == "Deniz"
    # The ciphertext must not contain the plaintext, or the encryption is decorative.
    raw = store.db.execute("SELECT enc_value FROM memories").fetchone()[0]
    assert b"Deniz" not in raw


def test_sensitive_values_stay_out_of_the_plaintext_search_column(
        store: Store, profile: str, session: dict) -> None:
    mid = store.append_message(session["id"], "user", "x")
    store.add_memory(profile, "user_fact", "user", "orientation", "bisexual",
                     0.9, 3, "special_category", [mid])
    search = store.db.execute("SELECT search_text FROM memories").fetchone()[0]
    assert "bisexual" not in search


@pytest.mark.parametrize("text,expected", [
    ("user enjoys hiking on sundays", "normal"),
    ("user works at Philips", "personal"),
    ("user has anxiety and takes medication", "special_category"),
    ("user is bisexual", "special_category"),
    ("user votes conservative", "special_category"),
])
def test_sensitivity_classification(text: str, expected: str) -> None:
    assert classify_sensitivity("normal", text) == expected


def test_classification_takes_the_stricter_of_model_and_pattern() -> None:
    """The model saying 'normal' does not override an obvious special category."""
    assert classify_sensitivity("normal", "user has depression") == "special_category"
    assert classify_sensitivity("special_category", "user likes tea") == "special_category"


# ------------------------------------------------------------------ state dynamics


def test_state_delta_is_clamped() -> None:
    state = {"warmth": 0.5, "trust": 0.5}
    new, applied = apply_state_delta(state, {"warmth": 0.9, "trust": -0.9})
    assert applied["warmth"] == pytest.approx(0.05)
    assert applied["trust"] == pytest.approx(-0.05)
    assert new["warmth"] == pytest.approx(0.55)


def test_a_correction_never_costs_trust() -> None:
    """Being corrected is how trust gets built. Punishing it teaches the user to lie."""
    _new, applied = apply_state_delta({"trust": 0.5}, {"trust": -0.08},
                                      user_corrected=True)
    assert applied.get("trust", 0.0) == 0.0


def test_conflict_tension_decays_on_its_own() -> None:
    new, applied = apply_state_delta({"conflict_tension": 0.30}, {})
    assert new["conflict_tension"] < 0.30
    assert applied["conflict_tension"] < 0


def test_state_stays_in_bounds() -> None:
    state = {"warmth": 0.99}
    for _ in range(10):
        state, _ = apply_state_delta(state, {"warmth": 0.08})
    assert 0.0 <= state["warmth"] <= 1.0


# ---------------------------------------------------------------------- retrieval


def test_special_category_memories_are_not_retrieved_casually(
        store: Store, profile: str, session: dict) -> None:
    mid = store.append_message(session["id"], "user", "x")
    store.add_memory(profile, "user_fact", "user", "struggles with", "anxiety",
                     0.9, 4, "special_category", [mid])
    hits = retrieve.search_memories(store, profile, "anxiety", mature=False)
    assert not hits, "a special-category memory surfaced outside mature mode"


def test_boundaries_are_always_retrievable(store: Store, profile: str,
                                           session: dict) -> None:
    """A boundary the user set must never be filtered away by a sensitivity rule."""
    mid = store.append_message(session["id"], "user", "x")
    store.add_memory(profile, "boundary", "user", "does not want", "advice unprompted",
                     0.95, 5, "special_category", [mid])
    assert retrieve.search_memories(store, profile, "advice", mature=False)


def test_locked_memories_rank_higher(store: Store, profile: str, session: dict) -> None:
    mid = store.append_message(session["id"], "user", "x")
    a = store.add_memory(profile, "user_fact", "user", "likes", "climbing",
                         0.8, 3, "normal", [mid])
    b = store.add_memory(profile, "user_fact", "user", "likes", "climbing gyms",
                         0.8, 3, "normal", [mid])
    store.lock_memory(b, True)
    ranked = retrieve.search_memories(store, profile, "climbing", mature=False)
    assert ranked[0].id == b, "the locked memory should outrank the identical unlocked one"


# --------------------------------------------------------- the continuity criterion


@pytest.mark.asyncio
async def test_fact_survives_rollover_into_next_episode(
        store: Store, profile: str, session: dict, persona_card: dict) -> None:
    """Episode one establishes a detail; episode two must still have it.

    This is the 'sustain across multiple interactions' criterion, as a test.
    """
    user_msg = store.append_message(
        session["id"], "user", "i have an interview on thursday and i'm dreading it")
    assistant_msg = store.append_message(
        session["id"], "assistant", "thursday. ok. what's the job.")

    fake = FakeOllama(json_replies=[{
        "memories": [{
            "kind": "user_fact", "subject": "user", "predicate": "has interview on",
            "value": "Thursday", "confidence": 0.95, "importance": 4,
            "sensitivity": "normal", "source_message_ids": [user_msg],
        }],
        "open_threads": ["find out how the Thursday interview went"],
        "state_delta": {"trust": 0.04, "emotional_depth": 0.03},
    }])

    result = await memory.extract(
        store, fake, "fake:1b", profile_id=profile, session_id=session["id"],
        persona_id=session["persona_id"],
        exchange=store.messages(session["id"]), state=session["state"], num_ctx=4096)

    assert len(result.committed) == 1
    assert result.state["trust"] > session["state"]["trust"]

    capsule_fake = FakeOllama(json_replies=[{
        "recent_summary": "They mentioned an interview on Thursday and were dreading it.",
        "unresolved_tension": "",
        "open_threads": ["find out how the Thursday interview went"],
        "shared_moments": ["the Thursday interview"],
        "carried_tics": ["trails off with 'anyway'"],
        "excluded": [],
    }])
    capsule = await memory.build_capsule(
        store, capsule_fake, "fake:1b", session_id=session["id"], profile_id=profile,
        persona=persona_card, state=result.state, num_ctx=4096)

    # Episode two opens with this text. The detail has to be in it.
    opening = memory.capsule_to_opening_context(capsule)
    assert "Thursday" in opening
    assert "interview" in opening.lower()

    episode_two = store.create_session(profile, session["persona_id"], "fake:1b", 4096,
                                       result.state, episode=2)
    store.append_message(episode_two, "system", opening)

    # And the durable record is retrievable from the new episode without the capsule.
    hits = retrieve.search_memories(store, profile, "how did the interview go",
                                    mature=False)
    assert any("Thursday" in h.value for h in hits), \
        "the fact did not survive into the next episode"


def test_an_edited_capsule_drops_what_the_user_removed() -> None:
    """The rollover dialog promises that what you delete is genuinely gone.

    The approve endpoint renders whichever capsule the client sends, so an edit made in the
    interface has to be absent from the text episode two opens with. This is the assertion
    behind the promise: a dialog that showed edit controls but still sent the model's draft
    would make that copy a lie, and the user would have no way to tell.
    """
    drafted = {
        "recent_summary": "They talked about the flat, and about their sister's diagnosis.",
        "unresolved_tension": "whether they are going to call their sister back",
        "open_threads": ["the flat viewing on Saturday", "calling their sister back"],
        "shared_moments": ["the argument about the flat", "their sister's diagnosis"],
        "carried_tics": ["says 'anyway' when changing the subject"],
        "excluded_memory_ids": [],
    }

    # What the user does in the dialog: rewrite the summary, drop the tension outright, and
    # delete every reference to the diagnosis they did not want carried forward.
    edited = {
        **drafted,
        "recent_summary": "They talked about the flat.",
        "unresolved_tension": None,
        "open_threads": ["the flat viewing on Saturday"],
        "shared_moments": ["the argument about the flat"],
    }

    opening = memory.capsule_to_opening_context(edited)

    assert "diagnosis" not in opening.lower(), "a deleted moment reached the next episode"
    assert "sister" not in opening.lower(), "a deleted thread reached the next episode"

    # The edit is a scalpel, not a reset: everything kept must still be carried.
    assert "flat" in opening.lower()
    assert "Saturday" in opening
    assert "anyway" in opening


@pytest.mark.asyncio
async def test_unattributed_memories_are_dropped(store: Store, profile: str,
                                                 session: dict) -> None:
    """A memory citing a message that does not exist is the model inventing history."""
    store.append_message(session["id"], "user", "hello")
    fake = FakeOllama(json_replies=[{
        "memories": [{
            "kind": "user_fact", "subject": "user", "predicate": "lives in",
            "value": "Berlin", "confidence": 0.9, "importance": 3,
            "sensitivity": "normal", "source_message_ids": ["msg_does_not_exist"],
        }],
        "state_delta": {},
    }])
    result = await memory.extract(
        store, fake, "fake:1b", profile_id=profile, session_id=session["id"],
        persona_id=session["persona_id"], exchange=store.messages(session["id"]),
        state=session["state"], num_ctx=4096)
    assert result.committed == []
    assert result.skipped == 1


# ------------------------------------------------------------------ context meter


def test_context_meter_escalates(store: Store, session: dict) -> None:
    assert memory.context_usage(store, session["id"], 4096)["stage"] == "ok"
    store.append_message(session["id"], "user", "x", tokens=3000)
    assert memory.context_usage(store, session["id"], 4096)["stage"] in {"choose", "block"}


# ------------------------------------------------- what the search surface contains


def test_personal_values_stay_searchable(store: Store, profile: str,
                                         session: dict) -> None:
    """A name or a place is most of what makes a relationship memory findable. Withholding
    it from the index sounded careful and meant "how is Deniz" could not retrieve the
    record about Deniz."""
    mid = store.append_message(session["id"], "user", "my sister Deniz is a vet")
    store.add_memory(profile, "user_fact", "sister", "is called", "Deniz",
                     0.95, 3, "personal", [mid])
    store.add_memory(profile, "user_fact", "user", "likes", "climbing",
                     0.9, 3, "normal", [mid])

    hits = retrieve.search_memories(store, profile, "how is deniz", mature=False)
    assert hits and hits[0].value == "Deniz", [h.value for h in hits]


def test_special_category_values_stay_out_of_the_index(store: Store, profile: str,
                                                       session: dict) -> None:
    """This is where withholding actually protects something."""
    mid = store.append_message(session["id"], "user", "x")
    store.add_memory(profile, "user_fact", "user", "struggles with", "anxiety",
                     0.9, 4, "special_category", [mid])
    surface = store.db.execute("SELECT search_text FROM memories").fetchone()[0]
    assert "anxiety" not in surface


def test_an_older_database_is_reindexed_on_open(tmp_path) -> None:
    """search_text is derived, so a definition change has to rebuild it. Without the
    migration an existing install keeps retrieving by the old rules and nothing errors:
    results are just quietly worse than on a fresh one."""
    from ollie.store import SCHEMA_VERSION, Store as S

    path = tmp_path / "old.db"
    store = S(path, key=b"0" * 32)
    profile = store.create_profile({}, {}, "x")
    persona_id = store.create_persona(profile, {"display_name": "y"}, "h")
    session_id = store.create_session(profile, persona_id, "m", 4096, {})
    mid = store.append_message(session_id, "user", "x")
    mem = store.add_memory(profile, "user_fact", "sister", "is called", "Deniz",
                           0.95, 3, "personal", [mid])

    # Simulate a database written before the change.
    with store.tx() as db:
        db.execute("UPDATE memories SET search_text='sister is called' WHERE id=?", (mem,))
        db.execute("PRAGMA user_version = 1")
    store.close()

    reopened = S(path, key=b"0" * 32)
    surface = reopened.db.execute("SELECT search_text FROM memories").fetchone()[0]
    assert "Deniz" in surface
    assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
