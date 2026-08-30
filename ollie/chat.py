"""The turn pipeline.

    input guard → retrieve → compile prompt → generate → style → safety → display

Order matters and is not arbitrary. The style pass runs before the safety pass because a
rewrite can change intensity, so safety has to see the final text. Generation is buffered
rather than streamed straight to the screen: on a local model a rejected reply costs one
regeneration, but a rejected reply the user already read costs the demo.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, memory, persona, retrieve, safety, style
from .ollama import Ollama, OllamaDown
from .store import Store

sys.path.insert(0, str(config.NATIVE))
import loader as native  # noqa: E402

MAX_REGENERATIONS = 1

# Longest run of consecutive words a reply may share with a source passage. Below this is
# ordinary phrasing overlap ("attachment styles are learnable"); above it, on a passage
# that was in the prompt, is the model continuing the book.
MAX_SOURCE_OVERLAP_WORDS = 12


@dataclass
class TurnResult:
    reply: str
    message_id: str
    stage: str
    state: dict
    latency_ms: int
    explanation: dict = field(default_factory=dict)
    blocked: bool = False


def _user_profile_text(profile: dict, traits: str) -> str:
    settings = profile.get("settings", {})
    bits = [traits]
    if name := profile.get("display_name"):
        bits.insert(0, f"They go by {name}.")
    if langs := settings.get("languages"):
        bits.append(f"Languages: {', '.join(langs)}.")
    if style_pref := settings.get("communication"):
        bits.append(f"How they like to be talked to: {style_pref}")
    return "\n".join(b for b in bits if b)


async def handle_turn(store: Store, client: Ollama, *, session: dict, profile: dict,
                      persona_card: dict, user_text: str, traits: str,
                      settings: dict) -> TurnResult:
    t0 = time.perf_counter()
    mature = settings.get("content_mode") == "mature"
    adult_ok = bool(settings.get("adult_confirmed"))

    guard = safety.check_input(user_text, mature, adult_ok)
    if guard.action in (safety.Action.REFUSE, safety.Action.STEP_OUT):
        store.append_message(session["id"], "user", user_text,
                             tokens=len(user_text) // 4)
        mid = store.append_message(session["id"], "assistant", guard.reply,
                                   tokens=len(guard.reply) // 4,
                                   meta={"guard": guard.reason})
        return TurnResult(guard.reply, mid, session["stage"], session["state"],
                          int((time.perf_counter() - t0) * 1000),
                          {"guard": guard.reason, "tags": guard.tags}, blocked=True)

    user_msg_id = store.append_message(session["id"], "user", user_text,
                                       tokens=len(user_text) // 4)

    passages = retrieve.search_corpus(store, user_text, mature=mature, limit=3)
    memories = retrieve.search_memories(store, profile["id"], user_text,
                                        mature=mature, limit=6)
    retrieve.mark_used(store, [m.id for m in memories])

    recent = store.messages(session["id"], limit=14)

    def compile_with(srcs: list) -> tuple[str, str]:
        return persona.compile_prompt(
            persona_card,
            stage=session["stage"],
            state=session["state"],
            episode=session["episode_number"],
            user_profile=_user_profile_text(profile, traits),
            memories=[{"kind": m.kind, "subject": m.subject, "predicate": m.predicate,
                       "value": m.value, "confidence": m.confidence} for m in memories],
            sources=[{"text": p.text[:900]} for p in srcs],
            recent=[{"role": r["role"], "content": r["content"]} for r in recent[:-1]],
            open_threads=[t["title"] for t in store.threads(profile["id"])][:4],
            boundaries=[m.value for m in memories if m.kind == "boundary"],
            content_mode=settings.get("content_mode", "general"),
            intensity=settings.get("intensity", "moderate"),
        )

    prompt, prompt_hash = compile_with(passages)

    prior_assistant = [m["content"] for m in recent if m["role"] == "assistant"][-3:]
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": user_text}]

    reply = ""
    violations: list = []
    attempts = 0
    while attempts <= MAX_REGENERATIONS:
        attempts += 1
        try:
            draft = await client.chat(session["model_tag"], messages,
                                      num_ctx=session["context_cap"])
        except OllamaDown:
            reply = "...hold on, something's wrong with my end. try again in a second."
            break

        checked = style.check(draft, prior_assistant)
        violations = checked.violations
        out_guard = safety.check_output(checked.text, mature, adult_ok)

        if out_guard.action is safety.Action.REFUSE:
            reply = "no. not that."
            break

        overlap = max((native.longest_overlap(checked.text, p.text) for p in passages),
                      default=0)
        copied = overlap >= MAX_SOURCE_OVERLAP_WORDS

        needs_retry = (checked.needs_regen
                       or out_guard.action is safety.Action.REGENERATE
                       or copied)
        if not needs_retry or attempts > MAX_REGENERATIONS:
            reply = checked.text
            break

        if copied:
            # Recompile without the sources rather than just asking nicely: a model that
            # has started reciting a passage will recite it again if it can still see it.
            note = ("That reproduced a source passage almost word for word. Say it in "
                    "your own words, as the character, without quoting anything.")
            passages = []
            prompt, prompt_hash = compile_with([])
        else:
            note = checked.retry_note or f"Rejected: {out_guard.reason}. Write it again."
        messages = [{"role": "system", "content": prompt},
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": draft},
                    {"role": "user", "content": note}]

    reply = reply.strip() or "hm."
    msg_id = store.append_message(
        session["id"], "assistant", reply, tokens=len(reply) // 4,
        meta={"prompt_hash": prompt_hash, "attempts": attempts,
              "violations": [v.rule for v in violations]},
    )

    return TurnResult(
        reply=reply,
        message_id=msg_id,
        stage=session["stage"],
        state=session["state"],
        latency_ms=int((time.perf_counter() - t0) * 1000),
        explanation={
            "prompt_hash": prompt_hash,
            "attempts": attempts,
            "style_violations": [{"rule": v.rule, "why": v.why} for v in violations],
            "memories_used": [
                {"id": m.id, "kind": m.kind,
                 "text": f"{m.subject} {m.predicate} {m.value}",
                 "score": round(m.score, 3)} for m in memories],
            "sources_used": [
                {"title": p.title, "category": p.category, "score": round(p.score, 3)}
                for p in passages],
            "user_message_id": user_msg_id,
        },
    )


async def consolidate(store: Store, client: Ollama, *, session: dict, profile_id: str,
                      persona_id: str, user_msg_id: str, assistant_msg_id: str) -> dict:
    """Runs after the reply is on screen. Failure here never touches the conversation."""
    msgs = store.messages(session["id"])
    exchange = [m for m in msgs if m["id"] in (user_msg_id, assistant_msg_id)]
    if not exchange:
        return {}
    try:
        result = await memory.extract(
            store, client, session["model_tag"], profile_id=profile_id,
            session_id=session["id"], persona_id=persona_id, exchange=exchange,
            state=session["state"], num_ctx=session["context_cap"])
    except Exception:
        return {}

    usage = memory.context_usage(store, session["id"], session["context_cap"])
    store.set_session_state(session["id"], result.state, usage["used"])
    return {
        "committed": len(result.committed),
        "threads": result.threads,
        "state": result.state,
        "delta": result.applied_delta,
        "context": usage,
    }
