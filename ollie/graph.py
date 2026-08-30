"""Graph consolidation over the relationship, using Graphify when it is available.

Two things happen here, and it matters that they are separable.

Ollie writes a sanitised Markdown card per episode into `graphify_ws/`. Raw messages never
go in: a card is a short third-person summary with the source message IDs attached, which is
both cheaper to process and far safer to have sitting on disk in a second place.

If the `graphify` CLI is installed, it turns that workspace into a NetworkX node-link
`graph.json`. If it is not, `emit_fallback_graph` writes the same shape directly from
SQLite. Downstream code reads `graph.json` and cannot tell which produced it, so Graphify is
an enhancer and never a dependency. The demo runs identically without it.

Graphify runs over episode cards, which are kilobytes. It is never pointed at the book
corpus: 57 books through an LLM extraction pass would take hours on the machine this was
built on, and BM25 already answers the question the books are there to answer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import deque
from pathlib import Path

from . import config
from .store import Store

CARD_TEMPLATE = """\
---
type: relationship_episode
episode_id: {episode_id}
date: {date}
participants: [user, {persona}]
sensitivity: {sensitivity}
source_message_ids: [{sources}]
---

# {title}

{summary}

## Open threads

{threads}

## What changed

{deltas}
"""


def available() -> bool:
    return shutil.which("graphify") is not None


# ------------------------------------------------------------------- episode cards


def write_episode_card(store: Store, *, session_id: str, persona_name: str,
                       summary: str, threads: list[str], deltas: dict[str, float],
                       sensitivity: str = "personal") -> Path:
    """One sanitised card per episode. Never raw messages."""
    config.GRAPH_WS.mkdir(parents=True, exist_ok=True)
    session = store.get("sessions", session_id) or {}
    messages = store.messages(session_id)
    sources = ", ".join(m["id"] for m in messages[:2] + messages[-2:])

    card = CARD_TEMPLATE.format(
        episode_id=session_id,
        date=session.get("started_at", ""),
        persona=persona_name.lower().replace(" ", "_"),
        sensitivity=sensitivity,
        sources=sources,
        title=f"Episode {session.get('episode_number', 1)} with {persona_name}",
        summary=summary.strip() or "(no summary)",
        threads="\n".join(f"- {t}" for t in threads) or "- none",
        deltas="\n".join(f"- {k}: {v:+.2f}" for k, v in deltas.items()) or "- none",
    )
    path = config.GRAPH_WS / f"{session_id}.md"
    path.write_text(card)
    return path


# ---------------------------------------------------------------------- graph build


def build(store: Store, timeout: int = 120) -> Path | None:
    """Run Graphify over the card workspace, or fall back to writing the graph ourselves."""
    out = config.DATA / "graph.json"
    if not available():
        return emit_fallback_graph(out, store)

    try:
        subprocess.run(
            ["graphify", str(config.GRAPH_WS), "--code-only"],
            capture_output=True, timeout=timeout, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return emit_fallback_graph(out, store)

    produced = config.GRAPH_WS / "graphify-out" / "graph.json"
    if not produced.exists():
        return emit_fallback_graph(out, store)

    # Replace atomically so a reader never sees a half-written graph.
    tmp = out.with_suffix(".json.tmp")
    tmp.write_bytes(produced.read_bytes())
    tmp.replace(out)
    return out


def emit_fallback_graph(out: Path, store: Store | None = None) -> Path:
    """Same node-link shape Graphify produces, built from SQLite.

    Nodes are memories, open threads and episodes. Edges connect a memory to the episode it
    came from and to any other memory sharing a subject, which is what makes "what else do
    I know about her sister" a single hop instead of a scan.
    """
    store = store or Store()
    nodes: list[dict] = []
    links: list[dict] = []
    seen: set[str] = set()

    profile = store.db.execute(
        "SELECT id FROM profiles ORDER BY created_at DESC LIMIT 1").fetchone()
    if profile:
        by_subject: dict[str, list[str]] = {}
        for m in store.memories(profile["id"]):
            nodes.append({"id": m["id"], "label": f"{m['subject']} {m['predicate']}",
                          "kind": m["kind"], "sensitivity": m["sensitivity"],
                          "importance": m["importance"]})
            seen.add(m["id"])
            by_subject.setdefault(m["subject"].lower(), []).append(m["id"])

            for src in store.db.execute(
                    "SELECT message_id FROM memory_sources WHERE memory_id=?",
                    (m["id"],)).fetchall():
                sess = store.db.execute("SELECT session_id FROM messages WHERE id=?",
                                        (src["message_id"],)).fetchone()
                if not sess:
                    continue
                ep = sess["session_id"]
                if ep not in seen:
                    nodes.append({"id": ep, "label": f"episode {ep[-4:]}", "kind": "episode"})
                    seen.add(ep)
                links.append({"source": m["id"], "target": ep, "rel": "recorded_in"})

        for ids in by_subject.values():
            for a, b in zip(ids, ids[1:]):
                links.append({"source": a, "target": b, "rel": "same_subject"})

        for t in store.threads(profile["id"]):
            nodes.append({"id": t["id"], "label": t["title"], "kind": "open_thread"})
            if t["session_id"] in seen:
                links.append({"source": t["id"], "target": t["session_id"],
                              "rel": "opened_in"})

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "directed": False, "multigraph": False,
        "graph": {"generator": "ollie.graph.emit_fallback_graph"},
        "nodes": nodes, "links": links,
    }, indent=1))
    return out


# ------------------------------------------------------------------------ traversal


def load(path: Path | None = None) -> dict[str, list[str]]:
    """Adjacency list from graph.json, whichever tool wrote it."""
    p = path or (config.DATA / "graph.json")
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

    adjacency: dict[str, list[str]] = {}
    for link in data.get("links", data.get("edges", [])):
        a, b = str(link.get("source", "")), str(link.get("target", ""))
        if not a or not b:
            continue
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    return adjacency


def neighbours(seed_ids: list[str], hops: int = 2, limit: int = 12,
               adjacency: dict[str, list[str]] | None = None) -> list[str]:
    """Bounded breadth-first expansion from the memories retrieval already found.

    This is the part a plain lexical search cannot do: a memory that shares no words with
    the current message can still be one hop from one that does.
    """
    adj = adjacency if adjacency is not None else load()
    if not adj:
        return []

    seen = set(seed_ids)
    out: list[str] = []
    queue: deque[tuple[str, int]] = deque((s, 0) for s in seed_ids)

    while queue and len(out) < limit:
        node, depth = queue.popleft()
        if depth >= hops:
            continue
        for nxt in adj.get(node, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            out.append(nxt)
            queue.append((nxt, depth + 1))
            if len(out) >= limit:
                break
    return out
