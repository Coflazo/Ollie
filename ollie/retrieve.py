"""Pick what goes into the prompt.

Two pools with different rules. Corpus passages are background understanding and are
cheap to be wrong about. Personal memories are the user's own words and are expensive to
be wrong about, surfacing a sensitive memory in a casual moment is worse than surfacing
nothing at all, so sensitive records carry a penalty they have to earn their way past.

Ranking is BM25 from FTS5 fused with signals SQLite cannot express. The fusion loop is
where `ollie_native` takes over when it is available; the Python path below is the
reference implementation both are tested against.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass

from . import config
from .store import Store

if str(config.NATIVE) not in sys.path:
    sys.path.insert(0, str(config.NATIVE))
import loader as native  # noqa: E402

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

    eligible = [r for r in rows if not (r["sensitivity"] == "explicit" and not mature)]
    if not eligible:
        return []

    lex = _norm([r["rank"] for r in eligible])
    # Fusion runs natively: BM25 relevance, the category prior, and a length bonus, since
    # very short chunks are usually headings that slipped through the splitter.
    order = native.rank(
        lex,
        [int(r["category"] in priors) for r in eligible],
        [len(r["text"]) for r in eligible],
        len(eligible),
    )
    out = [
        Passage(eligible[i]["id"], eligible[i]["text"], eligible[i]["title"],
                eligible[i]["category"], eligible[i]["sensitivity"],
                0.72 * lex[i]
                + 0.20 * (1.0 if eligible[i]["category"] in priors else 0.0)
                + 0.08 * min(1.0, len(eligible[i]["text"]) / 1800))
        for i in order
    ]
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


SENSITIVITY_CODE = {"normal": 0, "personal": 1, "special_category": 2}
COMMITMENT_KINDS = ("boundary", "promise", "open_thread")
MIN_MEMORY_SCORE = 0.18


def search_memories(store: Store, profile_id: str, text: str, *, mature: bool,
                    limit: int = 6) -> list[MemoryHit]:
    """Rank the user's own records against the current message.

    Two things make this different from the corpus search. The sensitivity rules are
    exclusions rather than penalties, so they are applied here in Python where they are
    readable and testable. And nothing is decrypted until it has earned a place in the
    prompt: scoring runs against the plaintext search column, and only the survivors get
    their values decrypted.
    """
    terms = set(keywords(text, limit=20))
    now = time.time()

    candidates = [
        m for m in store.memories_for_scoring(profile_id)
        # A special-category record is never casually resurfaced outside the mode it
        # belongs to. A boundary is the exception: it must always be visible, because
        # forgetting a limit is worse than mentioning a sensitive one.
        if not (m["sensitivity"] == "special_category"
                and not mature and m["kind"] != "boundary")
    ]
    if not candidates:
        return []

    # Flattened so the whole ranking crosses into native code in one call: 5 ints and
    # 2 doubles per record, plus the terms and the search surfaces as newline-joined
    # blobs. Newlines are stripped because they are the record separator.
    ints: list[int] = []
    doubles: list[float] = []
    texts: list[str] = []
    for m in candidates:
        ints += [m["importance"], int(m["user_locked"]),
                 int(m["kind"] in COMMITMENT_KINDS),
                 SENSITIVITY_CODE.get(m["sensitivity"], 0),
                 int(m["requires_confirmation"])]
        doubles += [m["confidence"], max(0.0, (now - m["created_at"]) / 86400)]
        texts.append(m["search_text"].lower().replace("\n", " "))

    scores = native.score_memories(sorted(terms), texts, ints, doubles)

    ranked = sorted(
        ((s, i) for i, s in enumerate(scores) if s > MIN_MEMORY_SCORE),
        key=lambda pair: (-pair[0], pair[1]),
    )[:limit]

    values = store.decrypt_values([candidates[i]["id"] for _s, i in ranked])
    return [
        MemoryHit(candidates[i]["id"], candidates[i]["kind"], candidates[i]["subject"],
                  candidates[i]["predicate"], values.get(candidates[i]["id"], ""),
                  candidates[i]["confidence"], candidates[i]["importance"],
                  candidates[i]["sensitivity"], score)
        for score, i in ranked
    ]


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
