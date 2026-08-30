"""Paths, hardware tiers and feature flags.

Everything that differs between the 8 GB build machine and the 48 GB demo machine is
resolved here, so the rest of the codebase never branches on hardware.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("OLLIE_DATA", ROOT / "data"))
BOOKS = Path(os.environ.get("OLLIE_BOOKS", ROOT / "Books"))
PROMPTS = ROOT / "prompts"
NATIVE = ROOT / "native"
GRAPH_WS = DATA / "graphify_ws"

DB_PATH = DATA / "ollie.db"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text:latest"
EMBED_DIM = 768

# Rollover thresholds as a fraction of the context cap. Ollie never waits for 100%:
# a summary written against a full window is a bad summary.
CTX_METER = 0.70
CTX_DRAFT = 0.80
CTX_CHOOSE = 0.90
CTX_BLOCK = 0.95


@dataclass(frozen=True)
class Tier:
    """One hardware bracket: which models to prefer and how much context to allow."""

    name: str
    min_ram_gb: float
    candidates: list[str]
    context_cap: int
    two_pass_style: bool
    ingest_batch: int


# Ordered from largest to smallest; the first tier whose min_ram_gb fits wins.
# Candidates are a preference order, not a promise that any given tag exists. Startup
# intersects this with whatever `GET /api/tags` actually reports.
TIERS: list[Tier] = [
    Tier("xl", 64, ["qwen3:32b", "gemma3:27b", "qwen2.5:32b-instruct-q4_K_M"], 32768, True, 32),
    Tier("l", 32, ["qwen3:14b", "gemma3:12b", "qwen2.5:14b-instruct-q4_K_M"], 16384, True, 24),
    Tier("m", 16, ["qwen3:8b", "gemma3:4b", "qwen2.5:7b-instruct-q4_K_M"], 12288, True, 16),
    Tier("s", 7, ["qwen2.5:3b-instruct-q4_K_M", "qwen3:1.7b", "llama3.2:3b"], 4096, False, 8),
    Tier("xs", 0, ["qwen2.5:0.5b-instruct", "llama3.2:1b"], 2048, False, 4),
]


def tier_for(ram_gb: float) -> Tier:
    for t in TIERS:
        if ram_gb >= t.min_ram_gb:
            return t
    return TIERS[-1]


@dataclass
class Flags:
    """Optional subsystems. Every one of these can be off and the demo still runs."""

    graphify: bool = False  # flipped on at startup if the graphify CLI is importable
    native: bool = False  # flipped on if libollie_native loaded
    marketplace: bool = True
    mature_available: bool = True


FLAGS = Flags()


def ensure_dirs() -> None:
    for p in (DATA, GRAPH_WS, DATA / "exports"):
        p.mkdir(parents=True, exist_ok=True)


def load_models_json() -> dict:
    p = ROOT / "config" / "models.json"
    return json.loads(p.read_text()) if p.exists() else {}
