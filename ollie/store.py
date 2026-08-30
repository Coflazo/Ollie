"""SQLite is the authoritative record. Everything else in Ollie is a derived index.

Two things make this more than a wrapper around sqlite3:

- Message bodies and memory values are encrypted at rest with AES-GCM, keyed from the
  macOS Keychain. A stolen copy of ollie.db is not a readable transcript of someone's
  private conversations. `python -m ollie dump` decrypts for debugging.
- Chunks carry both a FTS5 lexical index and an int8-quantised embedding blob, so
  retrieval can fuse the two without a vector database.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config

KEYCHAIN_SERVICE = "ollie-local-key"
NONCE_BYTES = 12

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    display_name TEXT,
    locale TEXT NOT NULL DEFAULT 'en',
    settings_json TEXT NOT NULL,
    personality_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    deleted_at REAL
);

CREATE TABLE IF NOT EXISTS personas (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    card_json TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    episode_number INTEGER NOT NULL DEFAULT 1,
    model_tag TEXT NOT NULL,
    context_cap INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    ended_at REAL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    role TEXT NOT NULL,
    enc_content BLOB NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id, ordinal);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    persona_id TEXT,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    enc_value BLOB NOT NULL,
    search_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL,
    importance INTEGER NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    user_locked INTEGER NOT NULL DEFAULT 0,
    requires_confirmation INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT,
    expires_at REAL,
    last_used_at REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_memories_profile ON memories(profile_id, superseded_by);

CREATE TABLE IF NOT EXISTS memory_sources (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    message_id TEXT NOT NULL,
    PRIMARY KEY (memory_id, message_id)
);

CREATE TABLE IF NOT EXISTS open_threads (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    due_at REAL,
    source_message_id TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS capsules (
    id TEXT PRIMARY KEY,
    from_session_id TEXT NOT NULL,
    to_session_id TEXT,
    capsule_json TEXT NOT NULL,
    user_approved INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS consent_receipts (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    granted_at REAL NOT NULL,
    withdrawn_at REAL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    license TEXT NOT NULL DEFAULT 'user-asserted-private-copy',
    redistributable INTEGER NOT NULL DEFAULT 0,
    content_rating TEXT NOT NULL DEFAULT 'general',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    locator TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'general',
    text TEXT NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    vec BLOB
);
CREATE INDEX IF NOT EXISTS ix_chunks_source ON chunks(source_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""


# --------------------------------------------------------------------------- crypto


def _keychain_get() -> bytes | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return base64.b64decode(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _keychain_put(key: bytes) -> bool:
    try:
        out = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
             "-a", "ollie", "-w", base64.b64encode(key).decode()],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def load_key() -> bytes:
    """Fetch the local encryption key, creating it on first launch.

    Falls back to a file in the data directory when the Keychain is unavailable (Linux,
    CI, a locked keychain). The fallback is chmod 0600 and the README says plainly that
    it is weaker than the Keychain path.
    """
    if env := os.environ.get("OLLIE_KEY_B64"):
        return base64.b64decode(env)
    if key := _keychain_get():
        return key

    key = AESGCM.generate_key(bit_length=256)
    if _keychain_put(key):
        return key

    config.ensure_dirs()
    fallback = config.DATA / "local.key"
    if fallback.exists():
        return base64.b64decode(fallback.read_bytes())
    fallback.write_bytes(base64.b64encode(key))
    fallback.chmod(0o600)
    return key


class Crypt:
    def __init__(self, key: bytes | None = None) -> None:
        self._aes = AESGCM(key or load_key())

    def enc(self, plaintext: str) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        return nonce + self._aes.encrypt(nonce, plaintext.encode(), None)

    def dec(self, blob: bytes) -> str:
        if not blob:
            return ""
        return self._aes.decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None).decode()


# ---------------------------------------------------------------------------- store


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, path: Path | None = None, key: bytes | None = None) -> None:
        config.ensure_dirs()
        self.path = Path(path or config.DB_PATH)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.crypt = Crypt(key)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def close(self) -> None:
        self.db.close()

    # -- profiles / personas / sessions ------------------------------------------

    def create_profile(self, settings: dict, personality: dict, name: str = "") -> str:
        pid = new_id("prof")
        with self.tx() as db:
            db.execute(
                "INSERT INTO profiles(id, display_name, locale, settings_json, "
                "personality_json, created_at) VALUES (?,?,?,?,?,?)",
                (pid, name, settings.get("locale", "en"), json.dumps(settings),
                 json.dumps(personality), time.time()),
            )
        return pid

    def create_persona(self, profile_id: str, card: dict, prompt_hash: str) -> str:
        pid = new_id("pers")
        with self.tx() as db:
            db.execute("UPDATE personas SET active=0 WHERE profile_id=?", (profile_id,))
            db.execute(
                "INSERT INTO personas(id, profile_id, version, card_json, prompt_hash, "
                "active, created_at) VALUES (?,?,?,?,?,1,?)",
                (pid, profile_id, 1, json.dumps(card), prompt_hash, time.time()),
            )
        return pid

    def create_session(self, profile_id: str, persona_id: str, model_tag: str,
                       context_cap: int, state: dict, episode: int = 1) -> str:
        sid = new_id("sess")
        with self.tx() as db:
            db.execute(
                "INSERT INTO sessions(id, profile_id, persona_id, episode_number, "
                "model_tag, context_cap, state_json, started_at) VALUES (?,?,?,?,?,?,?,?)",
                (sid, profile_id, persona_id, episode, model_tag, context_cap,
                 json.dumps(state), time.time()),
            )
        return sid

    def get(self, table: str, row_id: str) -> dict | None:
        if table not in {"profiles", "personas", "sessions", "capsules", "memories"}:
            raise ValueError(f"not a gettable table: {table}")
        row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        return dict(row) if row else None

    def set_session_state(self, session_id: str, state: dict, tokens_used: int) -> None:
        with self.tx() as db:
            db.execute("UPDATE sessions SET state_json=?, tokens_used=? WHERE id=?",
                       (json.dumps(state), tokens_used, session_id))

    # -- messages ------------------------------------------------------------------

    def append_message(self, session_id: str, role: str, content: str,
                       tokens: int = 0, meta: dict | None = None) -> str:
        mid = new_id("msg")
        with self.tx() as db:
            n = db.execute("SELECT COALESCE(MAX(ordinal), 0) + 1 FROM messages "
                           "WHERE session_id=?", (session_id,)).fetchone()[0]
            db.execute(
                "INSERT INTO messages(id, session_id, ordinal, role, enc_content, "
                "token_count, meta_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (mid, session_id, n, role, self.crypt.enc(content), tokens,
                 json.dumps(meta or {}), time.time()),
            )
        return mid

    def messages(self, session_id: str, limit: int | None = None) -> list[dict]:
        sql = "SELECT * FROM messages WHERE session_id=? ORDER BY ordinal"
        rows = self.db.execute(sql, (session_id,)).fetchall()
        if limit:
            rows = rows[-limit:]
        return [
            {**dict(r), "content": self.crypt.dec(r["enc_content"]),
             "meta": json.loads(r["meta_json"])}
            for r in rows
        ]

    # -- memories ------------------------------------------------------------------

    def add_memory(self, profile_id: str, kind: str, subject: str, predicate: str,
                   value: str, confidence: float, importance: int, sensitivity: str,
                   source_message_ids: list[str], persona_id: str | None = None,
                   requires_confirmation: bool = False) -> str:
        if not source_message_ids:
            raise ValueError("a memory without a source message is a hallucination")
        mid = new_id("mem")
        # search_text is the unencrypted retrieval surface. Sensitive values stay out of
        # it: we can find the memory by its subject and predicate without indexing the
        # secret itself in the clear.
        search = f"{subject} {predicate}"
        if sensitivity == "normal":
            search = f"{search} {value}"
        with self.tx() as db:
            db.execute(
                "INSERT INTO memories(id, profile_id, persona_id, kind, subject, "
                "predicate, enc_value, search_text, confidence, importance, sensitivity, "
                "requires_confirmation, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, profile_id, persona_id, kind, subject, predicate,
                 self.crypt.enc(value), search, confidence, importance, sensitivity,
                 int(requires_confirmation), time.time()),
            )
            db.executemany(
                "INSERT OR IGNORE INTO memory_sources(memory_id, message_id) VALUES (?,?)",
                [(mid, m) for m in source_message_ids],
            )
        return mid

    def memories_for_scoring(self, profile_id: str) -> list[dict]:
        """Every live memory, with metadata and the plaintext search surface, but without
        decrypting the values.

        Ranking runs on every turn over every stored record. Decrypting all of them to
        score them means an AES operation per memory per message, and it means the whole
        of someone's history sits in process memory in the clear every time they say
        anything. Scoring here against `search_text`, then decrypting only the handful
        that survive, is both faster and a smaller exposure.
        """
        rows = self.db.execute(
            "SELECT id, kind, subject, predicate, search_text, confidence, importance, "
            "sensitivity, user_locked, requires_confirmation, created_at "
            "FROM memories WHERE profile_id=? AND superseded_by IS NULL",
            (profile_id,)).fetchall()
        return [dict(r) for r in rows]

    def decrypt_values(self, memory_ids: list[str]) -> dict[str, str]:
        """Plaintext for a specific set of memories, and nothing else."""
        if not memory_ids:
            return {}
        placeholders = ",".join("?" * len(memory_ids))
        rows = self.db.execute(
            f"SELECT id, enc_value FROM memories WHERE id IN ({placeholders})",
            memory_ids).fetchall()
        return {r["id"]: self.crypt.dec(r["enc_value"]) for r in rows}

    def memories(self, profile_id: str, include_superseded: bool = False) -> list[dict]:
        sql = "SELECT * FROM memories WHERE profile_id=?"
        if not include_superseded:
            sql += " AND superseded_by IS NULL"
        sql += " ORDER BY importance DESC, created_at DESC"
        return [{**dict(r), "value": self.crypt.dec(r["enc_value"])}
                for r in self.db.execute(sql, (profile_id,)).fetchall()]

    def memory_provenance(self, memory_id: str) -> list[dict]:
        """The messages a memory was drawn from, decrypted.

        Shown in the memory manager. A record the user cannot trace back to something
        they actually said is a record they have no basis to trust or correct.
        """
        rows = self.db.execute(
            "SELECT m.id, m.role, m.enc_content, m.created_at FROM memory_sources ms "
            "JOIN messages m ON m.id = ms.message_id WHERE ms.memory_id=? "
            "ORDER BY m.created_at", (memory_id,)).fetchall()
        return [{"message_id": r["id"], "role": r["role"],
                 "text": self.crypt.dec(r["enc_content"]), "created_at": r["created_at"]}
                for r in rows]

    def supersede_memory(self, old_id: str, new_id_: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE memories SET superseded_by=? WHERE id=?", (new_id_, old_id))

    def lock_memory(self, memory_id: str, locked: bool = True) -> None:
        with self.tx() as db:
            db.execute("UPDATE memories SET user_locked=? WHERE id=?",
                       (int(locked), memory_id))

    def forget_memory(self, memory_id: str) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    # -- threads and capsules --------------------------------------------------------

    def add_thread(self, profile_id: str, session_id: str, title: str,
                   source_message_id: str) -> str:
        tid = new_id("thr")
        with self.tx() as db:
            db.execute(
                "INSERT INTO open_threads(id, profile_id, session_id, title, "
                "source_message_id, created_at) VALUES (?,?,?,?,?,?)",
                (tid, profile_id, session_id, title, source_message_id, time.time()),
            )
        return tid

    def threads(self, profile_id: str, status: str = "open") -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM open_threads WHERE profile_id=? AND status=? "
            "ORDER BY created_at DESC", (profile_id, status)).fetchall()]

    def resolve_thread(self, thread_id: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE open_threads SET status='resolved' WHERE id=?", (thread_id,))

    def save_capsule(self, from_session: str, capsule: dict, approved: bool = False) -> str:
        cid = new_id("caps")
        with self.tx() as db:
            db.execute(
                "INSERT INTO capsules(id, from_session_id, capsule_json, user_approved, "
                "created_at) VALUES (?,?,?,?,?)",
                (cid, from_session, json.dumps(capsule), int(approved), time.time()),
            )
        return cid

    def approve_capsule(self, capsule_id: str, capsule: dict, to_session: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE capsules SET capsule_json=?, user_approved=1, "
                       "to_session_id=? WHERE id=?",
                       (json.dumps(capsule), to_session, capsule_id))

    def latest_capsule(self, profile_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT c.* FROM capsules c JOIN sessions s ON s.id = c.from_session_id "
            "WHERE s.profile_id=? AND c.user_approved=1 ORDER BY c.created_at DESC LIMIT 1",
            (profile_id,)).fetchone()
        return json.loads(row["capsule_json"]) if row else None

    # -- corpus ----------------------------------------------------------------------

    def upsert_source(self, source_id: str, title: str, author: str, category: str,
                      path: str, sha256: str, content_rating: str) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO sources(id, title, author, category, path, "
                "sha256, content_rating, ingested_at) VALUES (?,?,?,?,?,?,?,?)",
                (source_id, title, author, category, path, sha256, content_rating,
                 time.time()),
            )

    def add_chunks(self, source_id: str, rows: list[dict]) -> None:
        with self.tx() as db:
            db.executemany(
                "INSERT INTO chunks(source_id, ordinal, locator, category, sensitivity, "
                "text, token_estimate, vec) VALUES (?,?,?,?,?,?,?,?)",
                [(source_id, r["ordinal"], r.get("locator", ""), r["category"],
                  r.get("sensitivity", "general"), r["text"], r.get("tokens", 0),
                  r.get("vec")) for r in rows],
            )
            db.execute("UPDATE sources SET chunk_count = (SELECT COUNT(*) FROM chunks "
                       "WHERE source_id=?) WHERE id=?", (source_id, source_id))

    def source_ingested(self, sha256: str) -> bool:
        return self.db.execute("SELECT 1 FROM sources WHERE sha256=?",
                               (sha256,)).fetchone() is not None

    def corpus_stats(self) -> dict[str, Any]:
        s = self.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        c = self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        v = self.db.execute("SELECT COUNT(*) FROM chunks WHERE vec IS NOT NULL").fetchone()[0]
        return {"sources": s, "chunks": c, "embedded": v}
