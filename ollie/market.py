"""A simulated research-data marketplace. Nothing leaves the machine.

The buyer is fictional. No request is made, no payment is processed, no partnership is
implied with any real company. Every artifact this module writes carries that on its face,
because a convincing mock of a data sale is exactly the kind of thing that gets quoted out
of context later.

It exists to make a real argument visible: the user's conversation has value, and the only
honest version of that market is one where they see precisely what would leave, decide
field by field, and can still say no at the end.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, privacy
from .store import Store

BUYER = "Nova Robotics Research"  # fictional
POLICY_VERSION = "sim-2026.08"
BANNER = (
    "THIS IS A LOCAL SIMULATION.\n"
    "NO DATA WAS SENT. NO BUYER EXISTS. NO PAYMENT WAS PROCESSED.\n"
    "NO PARTNERSHIP WITH ANY REAL COMPANY IS CLAIMED OR IMPLIED.\n"
)


def mock_quote(turns: int, languages: int, repairs: int, high_risk: bool) -> float:
    """Deterministic and deliberately small. The number is an illustration of an
    incentive model, not a market price, and it is capped so it cannot read as one."""
    value = (0.50
             + 0.002 * turns
             + 0.25 * languages
             + 0.40 * repairs
             - (0.50 if high_risk else 0.0))
    return round(max(0.0, min(8.0, value)), 2)


def build_preview(store: Store, *, profile_id: str, session_id: str) -> dict:
    """Redact the session locally and show the user exactly what a contribution would be."""
    messages = store.messages(session_id)
    profile = store.get("profiles", profile_id) or {}
    memories = store.memories(profile_id)

    # Names the system already knows. A pattern scanner cannot tell a first name from any
    # other capitalised word, but the extractor has already recorded "sister is called
    # Deniz" as a fact, so that name is known and must not survive an export just because
    # it was never typed into a profile field.
    #
    # The filter is deliberately narrow. Taking every word from the value redacted
    # "user is called by their middle name" into "my [PERSON_1] [PERSON_4]", which
    # destroys the text and tells the user something false about what was in it. A name
    # here has to be a single capitalised alphabetic token in a short value.
    names = [n for n in [profile.get("display_name", "")] if n]
    for m in memories:
        if not any(cue in m["predicate"].lower()
                   for cue in ("called", "named", "name is")):
            continue
        words = m["value"].split()
        if len(words) > 3:
            continue  # a sentence, not a name
        names.extend(w.strip(".,'\"") for w in words
                     if w[:1].isupper() and w.strip(".,'\"").isalpha() and len(w) > 2)

    redacted: list[dict] = []
    all_spans: list[privacy.Span] = []
    joined_plain: list[str] = []

    for m in messages:
        if m["role"] == "system":
            continue
        clean, spans = privacy.redact(m["content"], names)
        all_spans.extend(spans)
        joined_plain.append(m["content"])
        redacted.append({"role": m["role"], "text": clean,
                         "removed": len(spans)})

    plain = "\n".join(joined_plain)
    risk = privacy.linkability(plain, all_spans)

    # Anything the extractor flagged as special category is excluded by default rather
    # than redacted. Redacting a sentence about someone's sexuality still leaves a
    # sentence about someone's sexuality.
    excluded = [m for m in memories if m["sensitivity"] == "special_category"]
    repairs = sum(1 for m in memories if m["kind"] == "correction")
    quote = mock_quote(len(redacted), len(set(profile.get("locale", "en"))),
                       repairs, risk["level"] == "high")

    counts: dict[str, int] = {}
    for s in all_spans:
        counts[s.kind] = counts.get(s.kind, 0) + 1

    return {
        "simulation": True,
        "uploaded": False,
        "paid": False,
        "buyer": BUYER,
        "buyer_is_fictional": True,
        "banner": BANNER,
        "purpose": "evaluating conversational repair in companion dialogue",
        "turn_count": len(redacted),
        "removed_by_kind": counts,
        "excluded_special_category": len(excluded),
        "sample": redacted[:8],
        "linkability": risk,
        "quote_eur": quote,
        "policy_version": POLICY_VERSION,
    }


def write_receipt(store: Store, *, profile_id: str, preview: dict) -> dict:
    """Records the user's decision locally. Still sends nothing anywhere."""
    receipt = {
        "simulation": True,
        "uploaded": False,
        "paid": False,
        "buyer": BUYER,
        "buyer_is_fictional": True,
        "purpose": preview.get("purpose", ""),
        "turn_count": preview.get("turn_count", 0),
        "excluded_special_category": preview.get("excluded_special_category", 0),
        "linkability_level": (preview.get("linkability") or {}).get("level"),
        "quote_eur": preview.get("quote_eur", 0.0),
        "policy_version": POLICY_VERSION,
        "granted_at": time.time(),
        "banner": BANNER,
    }

    receipt_id = f"receipt_{int(receipt['granted_at'])}"
    out: Path = config.DATA / "exports" / f"{receipt_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2))
    (out.parent / f"{receipt_id}_README_SIMULATION.txt").write_text(BANNER)

    with store.tx() as db:
        db.execute(
            "INSERT INTO consent_receipts(id, profile_id, purpose, scope_json, "
            "policy_version, granted_at) VALUES (?,?,?,?,?,?)",
            (receipt_id, profile_id, receipt["purpose"], json.dumps(receipt),
             POLICY_VERSION, receipt["granted_at"]),
        )

    return {"receipt_id": receipt_id, "path": str(out), "receipt": receipt}
