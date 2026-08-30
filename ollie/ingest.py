"""Turn a shelf of PDFs and EPUBs into a retrievable index.

Nothing here trains anything. Books become chunks, chunks get a lexical index and an
embedding, and relevant passages are placed into the prompt at generation time. That
distinction is why a source can be removed in one command and why the same corpus works
across different Ollama models.

Run as `python -m ollie.ingest --tier a` for the twelve demo-path titles, or `--tier all`.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import time
import zipfile
from pathlib import Path

import httpx
import numpy as np
from lxml import etree

from . import config
from .store import Store, new_id

# The demo path only needs these twelve. The rest ingest afterwards in the background so
# a slow shelf never blocks a working chat.
TIER_A = [
    "Attached", "Hold Me Tight", "The Seven Principles", "Eight Dates",
    "Nonviolent Communication", "Difficult Conversations", "Come As You Are",
    "Mating in Captivity", "She Comes First", "The Guide To Getting It On",
    "Gifts Differing", "How Emotions Are Made",
]

# Folders 05 and 06 are explicit. Chunks from them are tagged so retrieval can require a
# mature-mode session before surfacing them.
EXPLICIT_FOLDERS = ("05 - ", "06 - ", "07 - ")

TARGET_TOKENS = 700
OVERLAP_TOKENS = 80
MIN_CHUNK_CHARS = 220


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ------------------------------------------------------------------- text extraction


def _clean(text: str) -> str:
    text = text.replace("\xad", "").replace("​", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)          # de-hyphenate across line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Bare page numbers on their own line are noise in every book we have.
    text = re.sub(r"\n\s*\d{1,4}\s*\n", "\n\n", text)
    return text.strip()


def extract_pdf(path: Path) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t:
                parts.append(t)
    return _clean("\n\n".join(parts))


def extract_epub(path: Path) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist()
                 if n.lower().endswith((".xhtml", ".html", ".htm"))]
        # Spine order is approximated by sorted filenames, which is right for every
        # EPUB in this library (ch01, ch02, ...) and harmless when it is not.
        for name in sorted(names):
            try:
                raw = z.read(name)
            except KeyError:
                continue
            try:
                tree = etree.parse(io.BytesIO(raw), etree.HTMLParser())
            except etree.XMLSyntaxError:
                continue
            root = tree.getroot()
            if root is None:
                continue
            for bad in root.xpath("//script | //style | //nav"):
                bad.getparent().remove(bad)
            text = "\n".join(t.strip() for t in root.itertext() if t.strip())
            if len(text) > 200:
                parts.append(text)
    return _clean("\n\n".join(parts))


def extract(path: Path) -> str:
    return extract_pdf(path) if path.suffix.lower() == ".pdf" else extract_epub(path)


# --------------------------------------------------------------------------- chunking


def chunk(text: str) -> list[str]:
    """Split on paragraphs, pack to ~700 tokens, carry ~80 tokens of overlap."""
    paras = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 40]
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for p in paras:
        n = est_tokens(p)
        if size + n > TARGET_TOKENS and buf:
            out.append("\n\n".join(buf))
            # Carry the tail of the previous chunk so an idea split across a boundary is
            # still retrievable from either side.
            tail, carried = [], 0
            for prev in reversed(buf):
                tail.insert(0, prev)
                carried += est_tokens(prev)
                if carried >= OVERLAP_TOKENS:
                    break
            buf, size = tail, carried
        buf.append(p)
        size += n
    if buf:
        out.append("\n\n".join(buf))
    return [c for c in out if len(c) >= MIN_CHUNK_CHARS]


# ------------------------------------------------------------------------- embeddings


def quantize(vec: np.ndarray) -> bytes:
    """Unit-normalise then pack to int8. Cosine over the packed form is a plain dot
    product, which is what makes the native scorer a single tight loop."""
    v = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm > 0:
        v = v / norm
    return np.clip(np.rint(v * 127.0), -127, 127).astype(np.int8).tobytes()


def embed_batch(client: httpx.Client, texts: list[str]) -> list[bytes | None]:
    try:
        r = client.post(f"{config.OLLAMA_URL}/api/embed",
                        json={"model": config.EMBED_MODEL, "input": texts}, timeout=300)
        r.raise_for_status()
        return [quantize(np.array(e)) for e in r.json()["embeddings"]]
    except Exception as exc:  # embeddings are an optimisation, never a hard requirement
        print(f"  embed failed ({exc.__class__.__name__}), keeping lexical only",
              file=sys.stderr)
        return [None] * len(texts)


# ------------------------------------------------------------------------------ books


def parse_name(path: Path) -> tuple[str, str]:
    """`Title - Author (Year).ext` is the catalog convention; fall back to the stem."""
    stem = path.stem
    m = re.match(r"^(.*?) - (.*?)\s*\((.*)\)$", stem)
    return (m.group(1).strip(), m.group(2).strip()) if m else (stem, "")


def discover(books_dir: Path, tier: str) -> list[Path]:
    found = sorted(p for p in books_dir.rglob("*")
                   if p.is_file() and p.suffix.lower() in {".pdf", ".epub"})
    if tier != "a":
        return found
    picked = []
    for frag in TIER_A:
        for p in found:
            if p.name.startswith(frag) and p not in picked:
                picked.append(p)
                break
    return picked


def ingest_one(store: Store, client: httpx.Client | None, path: Path, root: Path,
               batch: int) -> int:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if store.source_ingested(sha):
        print(f"skip (already indexed) {path.name}")
        return 0

    title, author = parse_name(path)
    rel = path.resolve().relative_to(root.resolve())
    category = rel.parts[0] if len(rel.parts) > 1 else "uncategorised"
    rating = "explicit" if category.startswith(EXPLICIT_FOLDERS) else "general"

    t0 = time.time()
    text = extract(path)
    if len(text) < 2000:
        print(f"skip (no extractable text, likely scanned) {path.name}")
        return 0
    chunks = chunk(text)

    source_id = new_id("src")
    store.upsert_source(source_id, title, author, category, str(rel), sha, rating)

    rows: list[dict] = []
    if client is None:
        rows = [{"ordinal": i, "category": category, "sensitivity": rating,
                 "text": c, "tokens": est_tokens(c), "vec": None}
                for i, c in enumerate(chunks)]
    else:
        for i in range(0, len(chunks), batch):
            window = chunks[i:i + batch]
            vecs = embed_batch(client, window)
            for j, (c, v) in enumerate(zip(window, vecs)):
                rows.append({"ordinal": i + j, "category": category,
                             "sensitivity": rating, "text": c,
                             "tokens": est_tokens(c), "vec": v})
    store.add_chunks(source_id, rows)
    print(f"ok {path.name}: {len(rows)} chunks in {time.time() - t0:.1f}s")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["a", "all"], default="a")
    ap.add_argument("--books", type=Path, default=config.BOOKS)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--embed", action="store_true",
                    help="also compute embeddings; needs real hardware, see below")
    args = ap.parse_args()

    if not args.books.exists():
        print(f"no books directory at {args.books}", file=sys.stderr)
        return 1

    store = Store()
    paths = discover(args.books, args.tier)
    mode = "lexical + embeddings" if args.embed else "lexical only"
    print(f"ingesting {len(paths)} book(s), tier={args.tier}, {mode}\n")

    # Embeddings are opt-in because they are not worth their cost on a memory-constrained
    # machine: measured at 67s per batch of 8 on the 8 GB Intel build box, which is about
    # twelve hours for twelve books. FTS5 alone retrieves topical passages from these
    # titles perfectly well, so the default path skips them.
    total = 0
    client = httpx.Client() if args.embed else None
    try:
        for p in paths:
            try:
                total += ingest_one(store, client, p, args.books, args.batch)
            except Exception as exc:
                print(f"FAIL {p.name}: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    finally:
        if client:
            client.close()

    print(f"\ndone: {total} new chunks. corpus={store.corpus_stats()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
