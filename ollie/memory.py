"""What survives a conversation, and what survives the end of one.

The model proposes; this module decides. Everything arriving from the extraction call is
treated as a suggestion from an unreliable narrator: confidences get capped, deltas get
clamped, records without a source message are dropped, and the rules that protect the
user (a correction cannot cost them trust; sensitive material is flagged not guessed) are
enforced here in code rather than requested in a prompt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import config
from .ollama import Ollama
from .store import Store

_env = Environment(loader=FileSystemLoader(config.PROMPTS), undefined=StrictUndefined,
                   trim_blocks=True, lstrip_blocks=True)

VALID_KINDS = {"user_fact", "preference", "boundary", "shared_event", "promise",
               "open_thread", "correction", "persona_fact"}
VALID_SENSITIVITY = {"normal", "personal", "special_category"}

STATE_KEYS = ("warmth", "trust", "playfulness", "emotional_depth",
              "romantic_tension", "conflict_tension")

MAX_PROPOSED_DELTA = 0.08
MAX_APPLIED_DELTA = 0.05

MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"},
                    "importance": {"type": "integer"},
                    "sensitivity": {"type": "string"},
                    "source_message_ids": {"type": "array", "items": {"type": "string"}},
                    "supersedes": {"type": "string"},
                },
                "required": ["kind", "subject", "predicate", "value", "confidence",
                             "importance", "sensitivity", "source_message_ids"],
            },
        },
        "open_threads": {"type": "array", "items": {"type": "string"}},
        "state_delta": {
            "type": "object",
            "properties": {k: {"type": "number"} for k in STATE_KEYS},
        },
    },
    "required": ["memories"],
}

CAPSULE_SCHEMA = {
    "type": "object",
    "properties": {
        "recent_summary": {"type": "string"},
        "unresolved_tension": {"type": "string"},
        "open_threads": {"type": "array", "items": {"type": "string"}},
        "shared_moments": {"type": "array", "items": {"type": "string"}},
        "carried_tics": {"type": "array", "items": {"type": "string"}},
        "excluded": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recent_summary", "open_threads", "shared_moments"],
}

# Belt and braces on the extractor's sensitivity call. If either the model or these
# patterns think a record is sensitive, it is sensitive.
_SPECIAL = re.compile(
    r"\b(sex|sexual|orgasm|aroused|kink|porn|masturbat|libido|"
    r"depress|anxiety|anxious|therapy|therapist|medication|diagnos|adhd|autis|"
    r"bipolar|trauma|abuse|assault|self[- ]harm|suicid|"
    r"muslim|christian|jewish|hindu|atheist|religio|"
    r"gay|lesbian|bisexual|queer|trans|nonbinary|asexual|"
    r"vote|voting|political|conservative|liberal|socialist)\w*", re.I)
_PERSONAL = re.compile(
    r"(\b(street|avenue|road|address|postcode|zip|"
    r"university|college|school|employer|company|hospital|clinic)\b"
    r"|\bwork(s|ed|ing)?\s+(at|for)\b|\bstudie[sd]\s+at\b|\blives?\s+(in|on|at)\b"
    r"|@|\+\d{6,})", re.I)


@dataclass
class ExtractionResult:
    committed: list[str] = field(default_factory=list)
    threads: list[str] = field(default_factory=list)
    state: dict[str, float] = field(default_factory=dict)
    applied_delta: dict[str, float] = field(default_factory=dict)
    skipped: int = 0


def _clamp(v: object, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        return max(lo, min(hi, float(v)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def classify_sensitivity(claimed: str, text: str) -> str:
    """Take the stricter of what the model said and what the text obviously contains."""
    claimed = claimed if claimed in VALID_SENSITIVITY else "normal"
    if _SPECIAL.search(text):
        return "special_category"
    if claimed == "special_category":
        return "special_category"
    if _PERSONAL.search(text) or claimed == "personal":
        return "personal"
    return "normal"


def apply_state_delta(current: dict[str, float], proposed: dict,
                      *, user_corrected: bool = False,
                      repair_happened: bool = False) -> tuple[dict[str, float], dict[str, float]]:
    """Move the interaction state, slowly.

    Returns (new_state, applied_delta). A character whose feelings swing a full point per
    message is a slot machine, not a person, so this is where the model's enthusiasm gets
    turned into something with inertia.
    """
    new = dict(current)
    applied: dict[str, float] = {}

    for key in STATE_KEYS:
        raw = _clamp(proposed.get(key, 0.0), -MAX_PROPOSED_DELTA, MAX_PROPOSED_DELTA)
        delta = max(-MAX_APPLIED_DELTA, min(MAX_APPLIED_DELTA, raw))

        # Being corrected is how trust gets built, not how it gets lost.
        if key == "trust" and user_corrected and delta < 0:
            delta = 0.0

        if key == "conflict_tension" and repair_happened:
            delta = min(delta, -0.02)

        if abs(delta) > 1e-6:
            new[key] = round(max(0.0, min(1.0, new.get(key, 0.5) + delta)), 4)
            applied[key] = round(delta, 4)

    # Tension fades on its own. Without this, one bad exchange colours every later one.
    if not applied.get("conflict_tension") and new.get("conflict_tension", 0) > 0:
        decayed = round(max(0.0, new["conflict_tension"] - 0.01), 4)
        if decayed != new["conflict_tension"]:
            applied["conflict_tension"] = round(decayed - new["conflict_tension"], 4)
            new["conflict_tension"] = decayed

    return new, applied


async def extract(store: Store, client: Ollama, model: str, *, profile_id: str,
                  session_id: str, persona_id: str, exchange: list[dict],
                  state: dict[str, float], num_ctx: int) -> ExtractionResult:
    """Background pass over the last exchange. Never raises into the conversation."""
    result = ExtractionResult(state=dict(state))

    existing = store.memories(profile_id)[:20]
    prompt = _env.get_template("memory_extract.j2").render(
        exchange=exchange,
        existing=[{"kind": m["kind"], "subject": m["subject"],
                   "predicate": m["predicate"], "value": m["value"]} for m in existing],
    )
    data = await client.chat_json(model, [{"role": "user", "content": prompt}],
                                  MEMORY_SCHEMA, num_ctx=num_ctx)
    if not data:
        return result

    valid_ids = {m["id"] for m in exchange}
    user_corrected = False

    for item in data.get("memories", []):
        kind = str(item.get("kind", "")).strip()
        if kind not in VALID_KINDS:
            result.skipped += 1
            continue

        sources = [s for s in item.get("source_message_ids", []) if s in valid_ids]
        if not sources:
            result.skipped += 1  # unattributable, therefore not a memory
            continue

        value = str(item.get("value", "")).strip()
        subject = str(item.get("subject", "")).strip()
        predicate = str(item.get("predicate", "")).strip()
        if not value or not subject:
            result.skipped += 1
            continue

        confidence = _clamp(item.get("confidence"), 0.0, 1.0, 0.5)
        importance = int(_clamp(item.get("importance"), 1, 5, 2))
        sensitivity = classify_sensitivity(
            str(item.get("sensitivity", "")), f"{subject} {predicate} {value}")

        # Corrections and stated boundaries are things the user took trouble over.
        if kind == "correction":
            user_corrected = True
            confidence = max(confidence, 0.9)
        elif kind == "boundary":
            confidence = max(confidence, 0.9)
            importance = max(importance, 4)

        requires_confirmation = confidence < 0.7

        try:
            mem_id = store.add_memory(
                profile_id=profile_id, kind=kind, subject=subject, predicate=predicate,
                value=value, confidence=confidence, importance=importance,
                sensitivity=sensitivity, source_message_ids=sources,
                persona_id=persona_id, requires_confirmation=requires_confirmation,
            )
        except ValueError:
            result.skipped += 1
            continue

        if supersedes := str(item.get("supersedes", "")).strip():
            if store.get("memories", supersedes):
                store.supersede_memory(supersedes, mem_id)

        result.committed.append(mem_id)

    for title in data.get("open_threads", [])[:3]:
        title = str(title).strip()
        if title:
            store.add_thread(profile_id, session_id, title, exchange[-1]["id"])
            result.threads.append(title)

    repair = any(m.get("kind") == "correction" for m in data.get("memories", []))
    result.state, result.applied_delta = apply_state_delta(
        state, data.get("state_delta", {}) or {},
        user_corrected=user_corrected, repair_happened=repair)
    return result


# ------------------------------------------------------------------------- rollover


def context_usage(store: Store, session_id: str, context_cap: int) -> dict:
    """How full the window is. Ollie acts at 70/80/90/95 rather than waiting for a
    failed request at 100."""
    rows = store.db.execute(
        "SELECT COALESCE(SUM(token_count), 0) FROM messages WHERE session_id=?",
        (session_id,)).fetchone()
    used = rows[0] or 0
    # The system prompt is re-sent every turn and is the largest fixed cost.
    used += 1400
    frac = min(1.0, used / max(1, context_cap))
    stage = ("block" if frac >= config.CTX_BLOCK else
             "choose" if frac >= config.CTX_CHOOSE else
             "draft" if frac >= config.CTX_DRAFT else
             "meter" if frac >= config.CTX_METER else "ok")
    return {"used": used, "cap": context_cap, "fraction": round(frac, 3), "stage": stage}


async def build_capsule(store: Store, client: Ollama, model: str, *, session_id: str,
                        profile_id: str, persona: dict, state: dict[str, float],
                        num_ctx: int) -> dict:
    """The handover into the next episode. Structured, and shown to the user before use."""
    messages = store.messages(session_id)
    threads = [t["title"] for t in store.threads(profile_id)]

    prompt = _env.get_template("capsule.j2").render(
        messages=[{"id": m["id"], "role": m["role"], "content": m["content"]}
                  for m in messages[-40:]],
        state=state, threads=threads,
    )
    data = await client.chat_json(model, [{"role": "user", "content": prompt}],
                                  CAPSULE_SCHEMA, num_ctx=num_ctx) or {}

    excluded = [m["id"] for m in store.memories(profile_id)
                if m["sensitivity"] == "special_category" and not m["user_locked"]]

    return {
        "persona_id": persona.get("id", ""),
        "persona_name": persona.get("display_name", ""),
        "interaction_state": state,
        "recent_summary": str(data.get("recent_summary", "")).strip(),
        "unresolved_tension": str(data.get("unresolved_tension", "")).strip() or None,
        "open_threads": [str(t) for t in data.get("open_threads", [])][:6] or threads[:6],
        "shared_moments": [str(m) for m in data.get("shared_moments", [])][:5],
        "carried_tics": [str(t) for t in data.get("carried_tics", [])][:4]
                        or persona.get("tics", []),
        "excluded_memory_ids": excluded,
        "source_message_range": [messages[0]["id"], messages[-1]["id"]] if messages else [],
        "model_tag": model,
    }


def capsule_to_opening_context(capsule: dict) -> str:
    """Render an approved capsule into the text episode two actually opens with."""
    parts = [f"Last time: {capsule.get('recent_summary', '')}".strip()]
    if tension := capsule.get("unresolved_tension"):
        parts.append(f"Still unresolved between you: {tension}")
    if moments := capsule.get("shared_moments"):
        parts.append("Things you would not have forgotten: " + "; ".join(moments))
    if threads := capsule.get("open_threads"):
        parts.append("Left hanging: " + "; ".join(threads))
    if tics := capsule.get("carried_tics"):
        parts.append("Keep talking the way you talk: " + "; ".join(tics))
    return "\n".join(p for p in parts if p.strip())
