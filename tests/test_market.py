"""The simulated marketplace, and the promises it has to keep.

Every test here is about a claim being true rather than merely displayed. The simulation
banners have to survive into the artifacts, the export has to actually redact, and the
result must never be described as anonymous.
"""

from __future__ import annotations

import json

from ollie import market
from ollie.store import Store


def _conversation(store: Store, profile: str, session: dict) -> None:
    for role, text in [
        ("user", "my sister Deniz is driving me, you can reach me on 06 12345678"),
        ("assistant", "right. tell her not to give you a pep talk."),
        ("user", "email me at cagan.test@example.com if you think of anything"),
    ]:
        store.append_message(session["id"], role, text)


def test_preview_redacts_direct_identifiers(store: Store, profile: str,
                                            session: dict) -> None:
    _conversation(store, profile, session)
    preview = market.build_preview(store, profile_id=profile, session_id=session["id"])

    joined = " ".join(m["text"] for m in preview["sample"])
    assert "cagan.test@example.com" not in joined
    assert "[EMAIL_1]" in joined
    assert preview["removed_by_kind"].get("email", 0) >= 1


def test_names_the_system_already_knows_are_redacted(store: Store, profile: str,
                                                     session: dict) -> None:
    """A pattern scanner cannot tell a first name from any capitalised word, but the
    extractor already recorded this one as a fact, so it must not survive an export."""
    mid = store.append_message(session["id"], "user", "my sister Deniz is driving me")
    store.add_memory(profile, "user_fact", "sister", "is called", "Deniz",
                     0.95, 3, "personal", [mid])

    preview = market.build_preview(store, profile_id=profile, session_id=session["id"])
    joined = " ".join(m["text"] for m in preview["sample"])
    assert "Deniz" not in joined


def test_special_category_is_excluded_not_redacted(store: Store, profile: str,
                                                   session: dict) -> None:
    """Redacting a sentence about someone's health still leaves a sentence about their
    health, so those records are dropped from the contribution entirely."""
    mid = store.append_message(session["id"], "user", "x")
    store.add_memory(profile, "user_fact", "user", "struggles with", "anxiety",
                     0.9, 4, "special_category", [mid])

    preview = market.build_preview(store, profile_id=profile, session_id=session["id"])
    assert preview["excluded_special_category"] == 1


def test_system_messages_never_enter_the_export(store: Store, profile: str,
                                                session: dict) -> None:
    """The rollover opening is a system message containing the whole carried summary."""
    store.append_message(session["id"], "system", "Last time: they mentioned Deniz.")
    store.append_message(session["id"], "user", "hi")

    preview = market.build_preview(store, profile_id=profile, session_id=session["id"])
    assert all(m["role"] != "system" for m in preview["sample"])
    assert preview["turn_count"] == 1


def test_risk_report_never_claims_anonymity(store: Store, profile: str,
                                            session: dict) -> None:
    _conversation(store, profile, session)
    preview = market.build_preview(store, profile_id=profile, session_id=session["id"])
    note = preview["linkability"]["note"].lower()
    assert "pseudonymised" in note
    assert "not anonymous" in note


def test_preview_is_marked_as_a_simulation(store: Store, profile: str,
                                           session: dict) -> None:
    _conversation(store, profile, session)
    preview = market.build_preview(store, profile_id=profile, session_id=session["id"])
    assert preview["simulation"] is True
    assert preview["uploaded"] is False
    assert preview["paid"] is False
    assert preview["buyer_is_fictional"] is True
    assert "NO DATA WAS SENT" in preview["banner"]


def test_quote_is_deterministic_and_capped() -> None:
    assert market.mock_quote(8, 1, 0, False) == market.mock_quote(8, 1, 0, False)
    assert market.mock_quote(100000, 50, 50, False) <= 8.0
    assert market.mock_quote(0, 0, 0, True) >= 0.0


def test_high_risk_lowers_the_offer() -> None:
    """The incentive has to point the right way: harder to de-identify is worth less,
    not more."""
    assert market.mock_quote(20, 1, 1, True) < market.mock_quote(20, 1, 1, False)


def test_receipt_is_written_locally_and_says_nothing_was_sent(
        store: Store, profile: str, session: dict, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(market.config, "DATA", tmp_path)
    _conversation(store, profile, session)
    preview = market.build_preview(store, profile_id=profile, session_id=session["id"])

    out = market.write_receipt(store, profile_id=profile, preview=preview)
    written = json.loads((tmp_path / "exports" / f"{out['receipt_id']}.json").read_text())

    assert written["uploaded"] is False
    assert written["paid"] is False
    assert written["buyer_is_fictional"] is True
    assert (tmp_path / "exports" /
            f"{out['receipt_id']}_README_SIMULATION.txt").exists()

    row = store.db.execute("SELECT COUNT(*) FROM consent_receipts").fetchone()[0]
    assert row == 1
