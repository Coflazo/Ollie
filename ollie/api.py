"""Local HTTP API. Single user, single machine, no auth, no cloud.

There is no authentication because there is no remote: the server binds to localhost and
the only client is the browser tab Ollie opened. Anything that would need auth is a
feature we have deliberately not built.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import chat, config, graph, hardware, market, memory, persona, safety, types16
from .ollama import Ollama, OllamaDown, select_model
from .store import Store

app = FastAPI(title="Ollie", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


class State:
    """Everything the running app needs. Durable data lives in SQLite; this is the
    in-process cache plus the things that only make sense while the app is open."""

    def __init__(self) -> None:
        self.store = Store()
        self._client: Ollama | None = None
        self.probe = hardware.probe()
        self.tier = config.tier_for(self.probe.ram_gb)
        self.model: str | None = None
        self.installed: list[str] = []
        self.profile_id: str | None = None
        self.persona_id: str | None = None
        self.session_id: str | None = None
        self.traits = persona.TraitProfile()
        self.interview: list[dict] = []
        self.candidates: list[dict] = []
        self.matching: dict = {}
        self.known_type: str = ""
        self.settings: dict[str, Any] = {
            "content_mode": "general", "adult_confirmed": False,
            "intensity": "moderate", "languages": ["English"],
        }
        self.last_consolidation: dict = {}
        self.resumable: dict | None = None

    # Set by `serve --demo`. Everything else stays real: real prompts, real extraction,
    # real style filter, real retrieval. Only inference is scripted.
    use_mock: bool = False

    @property
    def client(self) -> Ollama:
        """Built on first use, inside the loop that will actually use it.

        httpx binds its connection pool to the running event loop. Constructing the client
        at import time and then touching it from a throwaway `asyncio.run` during startup
        leaves the pool holding a closed loop, and every later request fails with
        "Event loop is closed".
        """
        if self._client is None:
            if self.use_mock:
                from .mock import MockOllama

                self._client = MockOllama()  # type: ignore[assignment]
            else:
                self._client = Ollama()
        return self._client

    async def resolve_model(self, override: str | None = None) -> str | None:
        self.model, self.installed = await select_model(self.client, self.tier, override)
        return self.model

    def session(self) -> dict:
        if not self.session_id:
            raise HTTPException(409, "no active session")
        row = self.store.get("sessions", self.session_id)
        if not row:
            raise HTTPException(409, "session vanished")
        return {**row, "state": json.loads(row["state_json"]),
                "stage": json.loads(row["state_json"]).get("stage", "first_date")}

    def profile(self) -> dict:
        if not self.profile_id:
            raise HTTPException(409, "no profile")
        row = self.store.get("profiles", self.profile_id)
        return {**row, "settings": json.loads(row["settings_json"])}

    def persona_card(self) -> dict:
        if not self.persona_id:
            raise HTTPException(409, "no persona")
        return json.loads(self.store.get("personas", self.persona_id)["card_json"])

    def adopt_latest_session(self) -> dict | None:
        """Pick up the most recent unfinished conversation on disk.

        Session state lives in memory while the app runs but the record is in SQLite, so
        without this a restart, or anything written by `ollie seed`, would be invisible.
        Resuming is also what a person expects from something that claims to remember them.
        """
        row = self.store.db.execute(
            "SELECT s.*, p.card_json FROM sessions s "
            "JOIN personas p ON p.id = s.persona_id "
            "WHERE s.ended_at IS NULL ORDER BY s.started_at DESC LIMIT 1").fetchone()
        if not row:
            return None

        self.profile_id = row["profile_id"]
        self.persona_id = row["persona_id"]
        self.session_id = row["id"]

        profile = self.store.get("profiles", row["profile_id"]) or {}
        stored = json.loads(profile.get("settings_json") or "{}")
        self.settings.update({k: v for k, v in stored.items() if k in self.settings})

        card = json.loads(row["card_json"])
        return {"persona": card, "episode": row["episode_number"],
                "session_id": row["id"],
                "messages": len(self.store.messages(row["id"]))}


S = State()


# ------------------------------------------------------------------------ setup


@app.get("/v1/health")
async def health() -> dict:
    alive = await S.client.alive()
    return {
        "ok": True,
        "ollama": alive,
        "model": S.model,
        "installed": S.installed,
        "tier": S.tier.name,
        "corpus": S.store.corpus_stats(),
        "flags": {"native": config.FLAGS.native, "graphify": config.FLAGS.graphify,
                  "marketplace": config.FLAGS.marketplace},
    }


@app.get("/v1/setup/probe")
async def setup_probe(model: str | None = None) -> dict:
    alive = await S.client.alive()
    if S.use_mock:
        # Demo mode has a model by definition, so do not go asking Ollama about one.
        chosen = S.model or "demo:scripted"
        S.installed = [chosen]
    else:
        chosen = await S.resolve_model(model) if alive else None
    return {
        "hardware": S.probe.as_dict(),
        "summary": hardware.describe(S.probe, S.tier),
        "tier": {"name": S.tier.name, "context_cap": S.tier.context_cap,
                 "candidates": S.tier.candidates},
        "ollama": alive,
        "model": chosen,
        "installed": S.installed,
        "needs_pull": alive and chosen is None,
        "suggested_pull": S.tier.candidates[0] if chosen is None else None,
        "resumable": S.resumable,
    }


# -------------------------------------------------------------------- onboarding


class Questionnaire(BaseModel):
    answers: dict[str, int]
    preferences: dict[str, Any] = Field(default_factory=dict)
    display_name: str = ""
    # A user who already knows their four-letter type can say so and skip the inference.
    known_type: str = ""


@app.get("/v1/onboarding/questions")
async def questions() -> dict:
    return {"items": [{"id": k, "text": t} for k, t, _f, _d in persona.QUESTIONNAIRE],
            "scale": {"1": "not me at all", "5": "very much me"},
            "interview_turns": persona.INTERVIEW_TURNS,
            "types": list(types16.TYPES)}


@app.post("/v1/onboarding/questionnaire")
async def submit_questionnaire(body: Questionnaire) -> dict:
    big_five = persona.score_questionnaire(body.answers)
    S.traits = persona.TraitProfile(big_five=big_five)
    S.interview = []
    S.settings.update({k: v for k, v in body.preferences.items()
                       if k in {"content_mode", "intensity", "languages",
                                "communication", "adult_confirmed"}})
    S.known_type = body.known_type.strip().upper() if body.known_type else ""
    S.profile_id = S.store.create_profile(
        {**S.settings, "preferences": body.preferences}, {"big_five": big_five},
        body.display_name)

    if not S.model:
        raise HTTPException(503, "no model available")
    question = await persona.next_interview_question(
        S.client, S.model, S.interview, S.traits, S.tier.context_cap)
    S.interview.append({"role": "ollie", "content": question})
    return {"profile_id": S.profile_id, "big_five": big_five, "question": question,
            "turn": 1, "total": persona.INTERVIEW_TURNS}


class InterviewAnswer(BaseModel):
    answer: str


@app.post("/v1/onboarding/interview")
async def interview(body: InterviewAnswer) -> dict:
    if not S.model:
        raise HTTPException(503, "no model available")
    S.interview.append({"role": "user", "content": body.answer})
    answered = sum(1 for t in S.interview if t["role"] == "user")

    if answered < persona.INTERVIEW_TURNS:
        question = await persona.next_interview_question(
            S.client, S.model, S.interview, S.traits, S.tier.context_cap)
        S.interview.append({"role": "ollie", "content": question})
        return {"done": False, "question": question,
                "turn": answered + 1, "total": persona.INTERVIEW_TURNS}

    S.traits = await persona.extract_traits(
        S.client, S.model, S.interview, S.traits.big_five, S.tier.context_cap)
    S.candidates, S.matching = await persona.generate_candidates(
        S.client, S.model, S.traits, S.settings, S.tier.context_cap,
        user_type=S.known_type or None)

    return {
        "done": True,
        "read": {
            "summary": S.traits.summary(),
            "dimensions": [
                {"name": k, "score": v, "confidence": S.traits.confidence.get(k, 0),
                 "evidence": S.traits.evidence.get(k, "")}
                for k, v in sorted(S.traits.dimensions.items(),
                                   key=lambda kv: -abs(kv[1] - 0.5))],
            "texture": S.traits.texture,
            "dodges": S.traits.dodges,
            "contradictions": S.traits.contradictions,
        },
        "matching": S.matching,
        "candidates": S.candidates,
    }


class Selection(BaseModel):
    candidate_id: str
    edits: dict[str, Any] = Field(default_factory=dict)


@app.post("/v1/personas/select")
async def select_persona(body: Selection) -> dict:
    card = next((c for c in S.candidates if c["id"] == body.candidate_id), None)
    if not card:
        raise HTTPException(404, "no such candidate")
    card = {**card, **body.edits}

    verdict = safety.check_persona(card)
    if verdict.blocked:
        raise HTTPException(400, f"character rejected: {verdict.reason}")

    _prompt, prompt_hash = persona.compile_prompt(
        card, stage="first_date", state=persona.DEFAULT_STATE, episode=1,
        user_profile=S.traits.summary(), memories=[], sources=[], recent=[],
        open_threads=[], boundaries=[], content_mode=S.settings["content_mode"])

    S.persona_id = S.store.create_persona(S.profile_id, card, prompt_hash)
    state = {**persona.DEFAULT_STATE, "stage": "first_date"}
    S.session_id = S.store.create_session(S.profile_id, S.persona_id, S.model,
                                          S.tier.context_cap, state)
    return {"persona_id": S.persona_id, "session_id": S.session_id,
            "persona": card, "prompt_hash": prompt_hash}


# ------------------------------------------------------------------------- chat


class Message(BaseModel):
    text: str


@app.post("/v1/sessions/messages")
async def send_message(body: Message, background: BackgroundTasks) -> dict:
    session = S.session()
    result = await chat.handle_turn(
        S.store, S.client, session=session, profile=S.profile(),
        persona_card=S.persona_card(), user_text=body.text,
        traits=S.traits.summary(), settings=S.settings)

    if not result.blocked:
        background.add_task(_consolidate, session, result)

    usage = memory.context_usage(S.store, session["id"], session["context_cap"])
    return {"reply": result.reply, "message_id": result.message_id,
            "latency_ms": result.latency_ms, "explanation": result.explanation,
            "context": usage, "state": result.state}


async def _consolidate(session: dict, result: chat.TurnResult) -> None:
    S.last_consolidation = await chat.consolidate(
        S.store, S.client, session=session, profile_id=S.profile_id,
        persona_id=S.persona_id,
        user_msg_id=result.explanation.get("user_message_id", ""),
        assistant_msg_id=result.message_id)


@app.get("/v1/sessions/messages")
async def session_messages() -> dict:
    """The transcript so far. A resumed conversation has to show what was already said,
    otherwise "it remembers you" is contradicted by an empty screen."""
    session = S.session()
    return {"episode": session["episode_number"], "messages": [
        {"id": m["id"], "role": m["role"], "content": m["content"],
         "meta": m["meta"]}
        for m in S.store.messages(session["id"]) if m["role"] != "system"
    ]}


@app.get("/v1/sessions/context")
async def context() -> dict:
    session = S.session()
    # The session's own state is included so the interface can show it on load rather than
    # waiting for the first turn. A resumed conversation should look resumed immediately.
    return {**memory.context_usage(S.store, session["id"], session["context_cap"]),
            "state": session["state"],
            "episode": session["episode_number"],
            "consolidation": S.last_consolidation}


@app.get("/v1/memories")
async def list_memories(provenance: bool = False) -> dict:
    """Every live memory. With `provenance`, each one also carries the message it came
    from, because a record the user cannot trace is a record they cannot judge."""
    if not S.profile_id:
        return {"memories": [], "threads": []}

    out = []
    for m in S.store.memories(S.profile_id):
        row = {k: m[k] for k in ("id", "kind", "subject", "predicate", "confidence",
                                 "importance", "sensitivity", "user_locked",
                                 "requires_confirmation", "created_at")}
        row["value"] = m["value"]
        if provenance:
            row["sources"] = S.store.memory_provenance(m["id"])
        out.append(row)

    return {"memories": out, "threads": S.store.threads(S.profile_id)}


class MemoryEdit(BaseModel):
    value: str | None = None
    lock: bool | None = None


@app.patch("/v1/memories/{memory_id}")
async def patch_memory(memory_id: str, body: MemoryEdit | None = None,
                       lock: bool | None = None) -> dict:
    """Lock a memory, or correct it.

    A correction does not overwrite. It writes a new record that supersedes the old one,
    keeping the original and the audit link, because the history of what the system
    believed about someone is part of what they are entitled to see. The replacement
    inherits the original's provenance: the user is correcting what was understood, not
    inventing a new source.
    """
    if not S.profile_id:
        raise HTTPException(409, "no profile")

    lock_value = lock if lock is not None else (body.lock if body else None)
    if lock_value is not None:
        S.store.lock_memory(memory_id, lock_value)

    if body and body.value is not None:
        original = S.store.get("memories", memory_id)
        if not original:
            raise HTTPException(404, "no such memory")
        sources = [s["message_id"] for s in S.store.memory_provenance(memory_id)]
        new_id = S.store.add_memory(
            profile_id=S.profile_id, kind="correction", subject=original["subject"],
            predicate=original["predicate"], value=body.value,
            confidence=0.98, importance=max(3, original["importance"]),
            sensitivity=original["sensitivity"],
            source_message_ids=sources or ["user_correction"],
            persona_id=S.persona_id, requires_confirmation=False,
        )
        S.store.supersede_memory(memory_id, new_id)
        S.store.lock_memory(new_id, True)  # the user said it explicitly; keep it
        return {"ok": True, "replaced_by": new_id}

    return {"ok": True}


@app.delete("/v1/memories/{memory_id}")
async def delete_memory(memory_id: str) -> dict:
    S.store.forget_memory(memory_id)
    return {"ok": True}


# --------------------------------------------------------------------- rollover


@app.post("/v1/sessions/rollover/draft")
async def draft_capsule() -> dict:
    session = S.session()
    capsule = await memory.build_capsule(
        S.store, S.client, S.model, session_id=session["id"],
        profile_id=S.profile_id, persona=S.persona_card(),
        state=session["state"], num_ctx=session["context_cap"])
    capsule_id = S.store.save_capsule(session["id"], capsule)
    return {"capsule_id": capsule_id, "capsule": capsule}


class CapsuleApproval(BaseModel):
    capsule_id: str
    capsule: dict


@app.post("/v1/sessions/rollover/approve")
async def approve_capsule(body: CapsuleApproval) -> dict:
    old = S.session()
    state = {**body.capsule.get("interaction_state", old["state"]),
             "stage": old["state"].get("stage", "first_date")}

    new_session = S.store.create_session(
        S.profile_id, S.persona_id, S.model, S.tier.context_cap, state,
        episode=old["episode_number"] + 1)
    S.store.approve_capsule(body.capsule_id, body.capsule, new_session)

    # Rollover is the natural consolidation point: the episode is closed, so a sanitised
    # card can be written and the graph rebuilt from it. Both are best-effort. A graph
    # that fails to build costs one hop of retrieval quality, never the conversation.
    try:
        persona_card = S.persona_card()
        graph.write_episode_card(
            S.store, session_id=old["id"],
            persona_name=persona_card.get("display_name", "them"),
            summary=body.capsule.get("recent_summary", ""),
            threads=body.capsule.get("open_threads", []),
            deltas={k: v for k, v in old["state"].items() if isinstance(v, (int, float))},
        )
        graph.build(S.store)
    except Exception:
        pass

    opening = memory.capsule_to_opening_context(body.capsule)
    S.store.append_message(new_session, "system", opening, tokens=len(opening) // 4)
    S.session_id = new_session
    return {"session_id": new_session, "episode": old["episode_number"] + 1,
            "carried": opening}


# ------------------------------------------------------------------ marketplace


@app.post("/v1/marketplace/preview")
async def marketplace_preview() -> dict:
    session = S.session()
    return market.build_preview(S.store, profile_id=S.profile_id,
                                session_id=session["id"])


@app.post("/v1/marketplace/accept")
async def marketplace_accept(body: dict) -> dict:
    return market.write_receipt(S.store, profile_id=S.profile_id, preview=body)


# ---------------------------------------------------------------------- static


WEB_DIST = config.ROOT / "web" / "dist"
if WEB_DIST.exists():
    # Mounted explicitly rather than serving the whole tree at "/", so a stray file in
    # dist can never shadow a /v1 route.
    for sub in ("assets", "fonts"):
        if (WEB_DIST / sub).is_dir():
            app.mount(f"/{sub}", StaticFiles(directory=WEB_DIST / sub), name=sub)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")


@app.on_event("startup")
async def startup() -> None:
    config.ensure_dirs()

    # Report what actually loaded rather than what was configured. The health endpoint is
    # the only place a user can see whether the native path or the fallback is live.
    import sys

    sys.path.insert(0, str(config.NATIVE))
    try:
        import loader as native

        config.FLAGS.native = native.available()
    except ImportError:
        config.FLAGS.native = False

    from . import graph

    config.FLAGS.graphify = graph.available()

    S.resumable = S.adopt_latest_session()

    if S.use_mock:
        S.model = S.model or "demo:scripted"
        return
    if S.model:
        return  # the launcher already picked one; do not spend a round trip repeating it
    try:
        await S.resolve_model()
    except OllamaDown:
        pass
