"""ctypes binding for libollie_native, with a pure-Python implementation of every function.

The fallbacks are not an afterthought — they are the reference semantics. The C++ is an
optimisation that must agree with them, and `tests/test_native_parity.py` is what holds it
to that. Ollie is fully functional with `available() == False`.
"""

from __future__ import annotations

import ctypes
import math
import platform
import re
from pathlib import Path

_NATIVE_DIR = Path(__file__).resolve().parent
_lib: ctypes.CDLL | None = None
_load_error: str = "not attempted"

_WORD = re.compile(r"[a-z0-9]+")


def _library_path() -> Path:
    ext = "dylib" if platform.system() == "Darwin" else "so"
    return _NATIVE_DIR / f"libollie_native.{ext}"


def _load() -> ctypes.CDLL | None:
    global _lib, _load_error
    if _lib is not None:
        return _lib
    path = _library_path()
    if not path.exists():
        _load_error = f"not built: {path.name} missing (run native/build.sh)"
        return None
    try:
        lib = ctypes.CDLL(str(path))
    except OSError as exc:
        _load_error = f"load failed: {exc}"
        return None

    lib.ollie_physical_ram.restype = ctypes.c_uint64
    lib.ollie_physical_ram.argtypes = []

    lib.ollie_longest_overlap.restype = ctypes.c_int32
    lib.ollie_longest_overlap.argtypes = [ctypes.c_char_p, ctypes.c_char_p]

    lib.ollie_rank.restype = ctypes.c_int32
    lib.ollie_rank.argtypes = [
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32), ctypes.c_int32, ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
    ]

    lib.ollie_score_memories.restype = ctypes.c_int32
    lib.ollie_score_memories.argtypes = [
        ctypes.c_char_p,                  # terms, newline separated
        ctypes.c_char_p,                  # search texts, newline separated
        ctypes.POINTER(ctypes.c_int32),   # 5 per record
        ctypes.POINTER(ctypes.c_double),  # 2 per record
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_double),  # out_scores
    ]

    lib.ollie_version.restype = ctypes.c_char_p
    lib.ollie_version.argtypes = []

    _lib = lib
    _load_error = ""
    return _lib


def available() -> bool:
    return _load() is not None


def status() -> str:
    return "native" if available() else f"python fallback ({_load_error})"


# ----------------------------------------------------------------- pure Python twins


def _py_tokenize(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def py_longest_overlap(reply: str, source: str) -> int:
    a, b = _py_tokenize(reply), _py_tokenize(source)
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def py_rank(lexical: list[float], category_hit: list[int], lengths: list[int],
            k: int) -> list[int]:
    scored = [
        (0.72 * lexical[i] + 0.20 * (1.0 if category_hit[i] else 0.0)
         + 0.08 * min(1.0, lengths[i] / 1800.0), i)
        for i in range(len(lexical))
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [i for _score, i in scored[:k]]


def py_score_memories(terms: list[str], texts: list[str], ints: list[int],
                      doubles: list[float]) -> list[float]:
    """Reference implementation. `ints` is 5 per record, `doubles` is 2 per record."""
    out: list[float] = []
    for i, haystack in enumerate(texts):
        overlap = sum(1 for t in terms if t and t in haystack)
        importance, locked, commitment, sensitivity, confirm = ints[i * 5:i * 5 + 5]
        confidence, age_days = doubles[i * 2:i * 2 + 2]

        lexical = min(1.0, overlap / 3.0)
        recency = 1.0 / (1.0 + math.log1p(max(0.0, age_days)))
        score = (0.34 * lexical
                 + 0.24 * (importance / 5.0)
                 + 0.16 * confidence
                 + 0.12 * recency
                 + (0.14 if locked else 0.0)
                 + (0.15 if commitment else 0.0))
        if sensitivity == 2:
            score -= 0.30
        elif sensitivity == 1:
            score -= 0.05
        if confirm:
            score -= 0.10
        out.append(score)
    return out


def py_physical_ram() -> int:
    import subprocess
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return int(out) if out else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


# ------------------------------------------------------------------- public surface


def longest_overlap(reply: str, source: str) -> int:
    """Longest run of consecutive shared words. Used by the copyright guard."""
    lib = _load()
    if lib is None:
        return py_longest_overlap(reply, source)
    return int(lib.ollie_longest_overlap(reply.encode("utf-8", "ignore"),
                                         source.encode("utf-8", "ignore")))


def rank(lexical: list[float], category_hit: list[int], lengths: list[int],
         k: int) -> list[int]:
    """Indices of the top k candidates, best first."""
    n = len(lexical)
    if n == 0 or k <= 0:
        return []
    lib = _load()
    if lib is None:
        return py_rank(lexical, category_hit, lengths, k)

    take = min(k, n)
    c_lex = (ctypes.c_double * n)(*lexical)
    c_cat = (ctypes.c_int32 * n)(*category_hit)
    c_len = (ctypes.c_int32 * n)(*lengths)
    out = (ctypes.c_int32 * take)()
    count = lib.ollie_rank(c_lex, c_cat, c_len, n, take, out)
    return [int(out[i]) for i in range(count)]


def score_memories(terms: list[str], texts: list[str], ints: list[int],
                   doubles: list[float]) -> list[float]:
    """Score every stored memory against the current message.

    Includes the term matching, not just the arithmetic. An earlier split that did the
    matching in Python and only the multiply-adds here measured slower than pure Python,
    because marshalling through ctypes cost more than it saved. Records must contain no
    newline in their search text; the store guarantees that.
    """
    n = len(texts)
    if n == 0:
        return []
    lib = _load()
    if lib is None:
        return py_score_memories(terms, texts, ints, doubles)

    out = (ctypes.c_double * n)()
    lib.ollie_score_memories(
        "\n".join(terms).encode("utf-8", "ignore"),
        "\n".join(texts).encode("utf-8", "ignore"),
        (ctypes.c_int32 * len(ints))(*ints),
        (ctypes.c_double * len(doubles))(*doubles),
        n, out,
    )
    return [float(out[i]) for i in range(n)]


def physical_ram() -> int:
    lib = _load()
    return int(lib.ollie_physical_ram()) if lib else py_physical_ram()
