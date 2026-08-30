"""Graph consolidation, with and without the Graphify CLI present.

The point of these tests is the substitutability claim in the README: whichever tool wrote
`graph.json`, everything downstream behaves the same. If that stops being true, Graphify has
quietly become a dependency instead of an enhancer.
"""

from __future__ import annotations

import json

from ollie import graph
from ollie.store import Store


def test_fallback_graph_has_the_networkx_node_link_shape(store: Store, profile: str,
                                                         session: dict, tmp_path) -> None:
    mid = store.append_message(session["id"], "user", "my sister Deniz just moved")
    store.add_memory(profile, "user_fact", "sister", "is called", "Deniz",
                     0.95, 3, "normal", [mid])

    out = graph.emit_fallback_graph(tmp_path / "graph.json", store)
    data = json.loads(out.read_text())

    assert set(data) >= {"nodes", "links", "directed", "multigraph"}
    assert all("id" in n for n in data["nodes"])
    assert all({"source", "target"} <= set(l) for l in data["links"])


def test_memories_are_linked_to_the_episode_they_came_from(store: Store, profile: str,
                                                           session: dict, tmp_path) -> None:
    mid = store.append_message(session["id"], "user", "x")
    mem = store.add_memory(profile, "user_fact", "user", "likes", "climbing",
                           0.9, 3, "normal", [mid])

    data = json.loads(graph.emit_fallback_graph(tmp_path / "g.json", store).read_text())
    ids = {n["id"] for n in data["nodes"]}
    assert mem in ids and session["id"] in ids
    assert any(l["source"] == mem and l["target"] == session["id"] for l in data["links"])


def test_memories_about_the_same_subject_are_connected(store: Store, profile: str,
                                                       session: dict, tmp_path) -> None:
    """The reason the graph exists: two facts about her sister should be one hop apart
    even when the second shares no words with the query that found the first."""
    mid = store.append_message(session["id"], "user", "x")
    a = store.add_memory(profile, "user_fact", "sister", "is called", "Deniz",
                         0.9, 3, "normal", [mid])
    b = store.add_memory(profile, "user_fact", "sister", "works as", "a vet",
                         0.9, 3, "normal", [mid])

    adjacency = graph.load(graph.emit_fallback_graph(tmp_path / "g.json", store))
    assert b in graph.neighbours([a], hops=1, adjacency=adjacency)


def test_traversal_is_bounded(tmp_path) -> None:
    """A runaway expansion would blow the prompt budget, so hops and limit both bite."""
    chain = {str(i): [str(i + 1)] for i in range(50)}
    for i in range(1, 51):
        chain.setdefault(str(i), []).append(str(i - 1))

    assert len(graph.neighbours(["0"], hops=2, limit=99, adjacency=chain)) <= 2
    assert len(graph.neighbours(["0"], hops=99, limit=5, adjacency=chain)) == 5


def test_missing_graph_is_not_an_error(tmp_path) -> None:
    assert graph.load(tmp_path / "does-not-exist.json") == {}
    assert graph.neighbours(["a"], adjacency={}) == []


def test_corrupt_graph_is_not_an_error(tmp_path) -> None:
    bad = tmp_path / "graph.json"
    bad.write_text("{not json at all")
    assert graph.load(bad) == {}


def test_episode_card_carries_provenance_and_no_raw_messages(
        store: Store, profile: str, session: dict, monkeypatch, tmp_path) -> None:
    """Cards are what leaves SQLite. A card containing the transcript would defeat the
    reason for having cards at all."""
    monkeypatch.setattr(graph.config, "GRAPH_WS", tmp_path)
    secret = "my therapist's name is Anneke and I see her on Tuesdays"
    store.append_message(session["id"], "user", secret)

    card = graph.write_episode_card(
        store, session_id=session["id"], persona_name="Mira",
        summary="They talked about the week and left a plan open.",
        threads=["decide on Saturday"], deltas={"trust": 0.03})

    text = card.read_text()
    assert "Anneke" not in text
    assert secret not in text
    assert "source_message_ids" in text
    assert "decide on Saturday" in text


def test_load_accepts_either_links_or_edges_key(tmp_path) -> None:
    """Graphify and the fallback have agreed on `links` so far; accepting `edges` too
    means a schema change upstream degrades instead of silently emptying the graph."""
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"nodes": [{"id": "a"}, {"id": "b"}],
                             "edges": [{"source": "a", "target": "b"}]}))
    assert graph.load(p) == {"a": ["b"], "b": ["a"]}
