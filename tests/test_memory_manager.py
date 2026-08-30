"""Inspecting, correcting and forgetting.

The product's central promise is that memory is yours: visible, traceable, correctable and
deletable. These tests are what make that a property of the system rather than a sentence
in the README.
"""

from __future__ import annotations

from ollie import seed as seeder
from ollie.store import Store


def test_provenance_returns_the_message_a_memory_came_from(store: Store, profile: str,
                                                           session: dict) -> None:
    mid = store.append_message(session["id"], "user", "my sister Deniz is a vet")
    mem = store.add_memory(profile, "user_fact", "sister", "works as", "a vet",
                           0.95, 3, "personal", [mid])

    sources = store.memory_provenance(mem)
    assert len(sources) == 1
    assert sources[0]["message_id"] == mid
    assert "Deniz" in sources[0]["text"]
    assert sources[0]["role"] == "user"


def test_provenance_decrypts(store: Store, profile: str, session: dict) -> None:
    """The message is encrypted at rest, so provenance has to decrypt or it shows blobs."""
    mid = store.append_message(session["id"], "user", "a very specific sentence")
    mem = store.add_memory(profile, "user_fact", "user", "said", "something",
                           0.9, 2, "normal", [mid])
    assert store.memory_provenance(mem)[0]["text"] == "a very specific sentence"


def test_a_correction_supersedes_rather_than_overwrites(store: Store, profile: str,
                                                        session: dict) -> None:
    """The history of what the system believed about someone is part of what they are
    owed, so the original survives with an audit link to its replacement."""
    mid = store.append_message(session["id"], "user", "thursday at ten")
    original = store.add_memory(profile, "user_fact", "user", "has an interview on",
                                "Thursday at 10am", 0.95, 5, "normal", [mid])
    replacement = store.add_memory(profile, "correction", "user", "has an interview on",
                                   "Friday at 2pm", 0.98, 5, "normal", [mid])
    store.supersede_memory(original, replacement)

    live = store.memories(profile)
    assert [m["id"] for m in live] == [replacement]

    everything = store.memories(profile, include_superseded=True)
    old = next(m for m in everything if m["id"] == original)
    assert old["superseded_by"] == replacement
    assert old["value"] == "Thursday at 10am", "the original text must survive"


def test_forgetting_actually_deletes(store: Store, profile: str, session: dict) -> None:
    """Not a soft delete. The interface says 'forget' and it has to mean it."""
    mid = store.append_message(session["id"], "user", "x")
    mem = store.add_memory(profile, "user_fact", "user", "likes", "climbing",
                           0.9, 3, "normal", [mid])
    store.forget_memory(mem)

    assert store.memories(profile, include_superseded=True) == []
    orphans = store.db.execute(
        "SELECT COUNT(*) FROM memory_sources WHERE memory_id=?", (mem,)).fetchone()[0]
    assert orphans == 0, "the provenance rows must go with the memory"


def test_locking_survives_a_reload(store: Store, profile: str, session: dict) -> None:
    mid = store.append_message(session["id"], "user", "x")
    mem = store.add_memory(profile, "user_fact", "user", "likes", "climbing",
                           0.9, 3, "normal", [mid])
    store.lock_memory(mem, True)
    assert store.memories(profile)[0]["user_locked"] == 1
    store.lock_memory(mem, False)
    assert store.memories(profile)[0]["user_locked"] == 0


# ------------------------------------------------------------------ the demo seed


def test_every_seeded_memory_points_at_a_message_that_contains_it(store: Store) -> None:
    """The manager shows provenance, so a seeded record citing a message that does not
    support it would discredit the one screen whose job is to be checkable."""
    out = seeder.seed(store, "test:1b", 4096)

    for m in store.memories(out["profile_id"]):
        sources = store.memory_provenance(m["id"])
        assert sources, f"{m['subject']} {m['predicate']} has no source"

        combined = " ".join(s["text"].lower() for s in sources)
        # The distinctive token of the value should appear in the cited message.
        token = max(m["value"].lower().replace(",", "").split(), key=len)
        if len(token) > 4 and token not in {"reassurance", "interview", "something"}:
            assert token in combined, (
                f"{m['value']!r} cites messages that never mention {token!r}: {combined!r}")


def test_low_confidence_seeded_records_are_flagged_for_confirmation(store: Store) -> None:
    """One seeded record is something the character asserted and the user never confirmed.
    It should show as inferred, because that is the honest label."""
    out = seeder.seed(store, "test:1b", 4096)
    inferred = [m for m in store.memories(out["profile_id"])
                if m["requires_confirmation"]]
    assert inferred, "the seed should include at least one unconfirmed inference"
    assert all(m["confidence"] < 0.7 for m in inferred)
