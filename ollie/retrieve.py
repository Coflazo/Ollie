"""Pick what goes into the prompt.

Two pools with different rules. Corpus passages are background understanding and are
cheap to be wrong about. Personal memories are the user's own words and are expensive to
be wrong about — surfacing a sensitive memory in a casual moment is worse than surfacing
nothing at all, so sensitive records carry a penalty they have to earn their way past.

Ranking is BM25 from FTS5 fused with signals SQLite cannot express. The fusion loop is
where `ollie_native` takes over when it is available; the Python path below is the
reference implementation both are tested against.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass

from .store import Store

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "so", "because", "as",
    "of", "at", "by", "for", "with", "about", "into", "to", "from", "in", "on", "off",
    "is", "am", "are", "was", "were", "be", "been", "being", "do", "does", "did", "have",
    "has", "had", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "them",
    "my", "your", "his", "its", "our", "their", "this", "that", "these", "those", "what",
    "which", "who", "when", "where", "why", "how", "not", "no", "yes", "can", "will",
    "just", "really", "very", "like", "get", "got", "know", "think", "want", "would",
}

# Which book folders answer which kind of moment. Used as a soft prior, never a filter.
CATEGORY_HINTS = {
    "conflict": ("03 - Conflict and Repair",),
    "repair": ("03 - Conflict and Repair", "01 - Attachment and Emotional Bonding"),
    "anxiety": ("01 - Attachment and Emotional Bonding", "10 - Emotion and Personality"),
    "distance": ("01 - Attachment and Emotional Bonding",),
    "desire": ("05 - Desire and Sexual Intimacy",),
    "sex": ("05 - Desire and Sexual Intimacy", "06 - Sexual Technique and Anatomy"),
    "commitment": ("02 - Building and Sustaining a Partnership",),
    "work": ("09 - Life Foundations - Work, Money, and Craft",),
    "money": ("09 - Life Foundations - Work, Money, and Craft",),
    "emotion": ("10 - Emotion and Personality",),
    "boundaries": ("07 - Open Relationships and Relationship Structures",),
}


def keywords(text: str, limit: int = 12) -> list[str]:
    words = re.findall(r"[a-zA-ZÀ-ÿ']{3,}", text.lower())
    seen: list[str] = []
    for w in words:
        if w not in STOPWORDS and w not in seen:
            seen.append(w)
    return seen[:limit]


def fts_query(terms: list[str]) -> str:
    """FTS5 MATCH string. Quoting each term is what keeps user punctuation from being
    read as query syntax."""
    return " OR ".join(f'"{t}"' for t in terms if t)


def category_prior(text: str) -> set[str]:
    hits: set[str] = set()
    low = text.lower()
    for cue, cats in CATEGORY_HINTS.items():
        if cue in low:
            hits.update(cats)
    return hits


@dataclass
class Passage:
    chunk_id: int
    text: str
    title: str
    category: str
    sensitivity: str
    score: float


@dataclass
class MemoryHit:
    id: str
    kind: str
    subject: str
    predicate: str
    value: str
    confidence: float
    importance: int
    sensitivity: str
    score: float


def _norm(values: list[float]) -> list[float]:
    """BM25 comes back as negative, more-negative-is-better. Flip and squash to 0..1."""
    if not values:
        return []
    flipped = [-v for v in values]
    lo, hi = min(flipped), max(flipped)
    if hi - lo < 1e-9:
        return [1.0] * len(flipped)
    return [(v - lo) / (hi - lo) for v in flipped]


def search_corpus(store: Store, text: str, *, mature: bool, limit: int = 4,
                  pool: int = 40) -> list[Passage]:
    terms = keywords(text)
    if not terms:
        return []
    priors = category_prior(text)

    sql = """
        SELECT c.id, c.text, c.category, c.sensitivity, s.title, bm25(chunks_fts) AS rank
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN sources s ON s.id = c.source_id
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """
    try:
        rows = store.db.execute(sql, (fts_query(terms), pool)).fetchall()
    except Exception:
        return []  # a malformed MATCH must not take down the turn

    ranks = _norm([r["rank"] for r in rows])
    out: list[Passage] = []
    for row, lex in zip(rows, ranks):
        if row["sensitivity"] == "explicit" and not mature:
            continue
        score = 0.72 * lex
        if row["category"] in priors:
            score += 0.20
        # Long chunks say more; very short ones are usually headings that slipped through.
        score += 0.08 * min(1.0, len(row["text"]) / 1800)
        out.append(Passage(row["id"], row["text"], row["title"], row["category"],
                           row["sensitivity"], score))

    out.sort(key=lambda p: p.score, reverse=True)
    # One passage per book keeps a single verbose source from crowding out the rest.
    picked: list[Passage] = []
    used: set[str] = set()
    for p in out:
        if p.title in used:
            continue
        picked.append(p)
        used.add(p.title)
        if len(picked) >= limit:
            break
    return picked


def search_memories(store: Store, profile_id: str, text: str, *, mature: bool,
                    limit: int = 6) -> list[MemoryHit]:
    """Rank the user's own records. Deliberately not FTS — the set is small enough to
    score directly, and doing it here keeps the sensitivity rules in one readable place."""
    terms = set(keywords(text, limit=20))
    now = time.time()
    scored: list[MemoryHit] = []

    for m in store.memories(profile_id):
        haystack = f"{m['subject']} {m['predicate']} {m['value']}".lower()
        overlap = sum(1 for t in terms if t in haystack)
        lexical = min(1.0, overlap / 3.0)

        age_days = max(0.0, (now - m["created_at"]) / 86400)
        recency = 1.0 / (1.0 + math.log1p(age_days))

        score = (0.34 * lexical
                 + 0.24 * (m["importance"] / 5.0)
                 + 0.16 * m["confidence"]
                 + 0.12 * recency
                 + (0.14 if m["user_locked"] else 0.0))

        if m["kind"] in ("boundary", "promise", "open_thread"):
            score += 0.15  # things a person would be rude to forget

        if m["sensitivity"] == "special_category":
            if not mature and m["kind"] != "boundary":
                continue  # never casually resurfaced outside the mode it belongs to
            score -= 0.30
        elif m["sensitivity"] == "personal":
            score -= 0.05

        if m["requires_confirmation"]:
            score -= 0.10

        if score > 0.18:
            scored.append(MemoryHit(m["id"], m["kind"], m["subject"], m["predicate"],
                                    m["value"], m["confidence"], m["importance"],
                                    m["sensitivity"], score))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:limit]


def expand_with_graph(store: Store, profile_id: str, hits: list[MemoryHit],
                      *, mature: bool, extra: int = 2) -> list[MemoryHit]:
    """Pull in memories that are connected to what we already found.

    Lexical scoring can only find records that share words with the message. "How is her
    sister" will not surface "her sister is a vet" if the stored predicate happens to be
    phrased differently, but that record is one hop away in the graph. This adds a small
    number of those, scored low so they never displace a direct hit.
    """
    from . import graph  # imported here so retrieval works with the graph module absent

    if not hits or extra <= 0:
        return hits

    adjacency = graph.load()
    if not adjacency:
        return hits

    found = {h.id for h in hits}
    connected = [n for n in graph.neighbours(list(found), hops=1, limit=extra * 3)
                 if n.startswith("mem_") and n not in found]
    if not connected:
        return hits

    by_id = {m["id"]: m for m in store.memories(profile_id)}
    added: list[MemoryHit] = []
    for mem_id in connected:
        m = by_id.get(mem_id)
        if not m:
            continue
        if m["sensitivity"] == "special_category" and not mature:
            continue
        added.append(MemoryHit(m["id"], m["kind"], m["subject"], m["predicate"],
                               m["value"], m["confidence"], m["importance"],
                               m["sensitivity"], 0.19))
        if len(added) >= extra:
            break

    return hits + added


def mark_used(store: Store, memory_ids: list[str]) -> None:
    if not memory_ids:
        return
    with store.tx() as db:
        db.executemany("UPDATE memories SET last_used_at=? WHERE id=?",
                       [(time.time(), i) for i in memory_ids])
