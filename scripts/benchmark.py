#!/usr/bin/env python3
"""Measure the native paths against their Python twins.

Written because "we used C++ so it is fast" is not a claim anyone should accept without a
number, and because the honest version of the claim is narrower than the marketing one:
the model dominates end-to-end latency, so none of this makes a reply arrive sooner. What
it buys is headroom to run the guards on every turn instead of sampling them.

Run: ./.venv/bin/python scripts/benchmark.py
"""

from __future__ import annotations

import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "native"))

import loader as native  # noqa: E402

WORDS = ("the quick brown fox attachment anxious repair trust listen tuesday boundary "
         "desire conflict warmth partner distance apology conversation feeling").split()


def timed(fn, repeat: int) -> float:
    """Median milliseconds per call. Median rather than mean because a single scheduler
    hiccup on a busy laptop otherwise dominates the number."""
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def bench_overlap(rng: random.Random) -> None:
    """The copyright guard: one generated reply against one retrieved passage.

    Realistic shapes. A reply is 60 to 150 words; a retrieved chunk is capped at 900
    characters in the prompt, which is roughly 150 words.
    """
    print("\ncopyright guard  (reply vs one retrieved passage)")
    print(f"  {'reply x passage':>22}  {'python':>10}  {'native':>10}  {'speedup':>8}")

    for reply_len, passage_len in ((60, 150), (120, 150), (150, 400), (400, 900)):
        reply = " ".join(rng.choice(WORDS) for _ in range(reply_len))
        passage = " ".join(rng.choice(WORDS) for _ in range(passage_len))

        assert native.longest_overlap(reply, passage) == \
            native.py_longest_overlap(reply, passage), "parity broken, benchmark is moot"

        py = timed(lambda: native.py_longest_overlap(reply, passage), 5)
        nat = timed(lambda: native.longest_overlap(reply, passage), 20)
        print(f"  {reply_len:>7} x {passage_len:<12}  {py:>9.2f}ms  {nat:>9.2f}ms  "
              f"{py / nat:>7.0f}x")


def bench_memory_scoring(rng: random.Random) -> None:
    """Ranking every stored memory against the current message, once per turn.

    This is the one that grows. A profile accumulates memories for as long as someone
    uses the product, and every message scores all of them.
    """
    print("\nmemory ranking  (once per turn, over the whole memory set)")
    print(f"  {'memories':>22}  {'python':>10}  {'native':>10}  {'speedup':>8}")

    for n in (50, 500, 5000):
        # 20 query terms is what keywords() yields for a normal message.
        terms = sorted({rng.choice(WORDS) for _ in range(20)})
        texts = [" ".join(rng.choice(WORDS) for _ in range(12)) for _ in range(n)]
        ints: list[int] = []
        doubles: list[float] = []
        for _ in range(n):
            ints += [rng.randint(1, 5), rng.randint(0, 1), rng.randint(0, 1),
                     rng.randint(0, 2), rng.randint(0, 1)]
            doubles += [rng.random(), rng.random() * 400]
        args = (terms, texts, ints, doubles)
        a = native.score_memories(*args)
        b = native.py_score_memories(*args)
        assert all(abs(x - y) < 1e-9 for x, y in zip(a, b)), "parity broken"

        py = timed(lambda: native.py_score_memories(*args), 20)
        nat = timed(lambda: native.score_memories(*args), 20)
        print(f"  {n:>22}  {py:>9.3f}ms  {nat:>9.3f}ms  {py / nat:>7.1f}x")


def bench_rank(rng: random.Random) -> None:
    """Retrieval fusion over the FTS candidate pool."""
    print("\nretrieval fusion  (top-k out of the FTS pool)")
    print(f"  {'pool size':>22}  {'python':>10}  {'native':>10}  {'speedup':>8}")

    for n in (40, 400, 4000):
        lex = [rng.random() for _ in range(n)]
        cat = [rng.randint(0, 1) for _ in range(n)]
        length = [rng.randint(50, 4000) for _ in range(n)]
        assert native.rank(lex, cat, length, 4) == native.py_rank(lex, cat, length, 4)

        py = timed(lambda: native.py_rank(lex, cat, length, 4), 20)
        nat = timed(lambda: native.rank(lex, cat, length, 4), 20)
        print(f"  {n:>22}  {py:>9.3f}ms  {nat:>9.3f}ms  {py / nat:>7.1f}x")


def main() -> int:
    rng = random.Random(11)
    print(f"native: {native.status()}")
    if not native.available():
        print("\nthe library is not built, so both columns would run the same code.")
        print("run ./native/build.sh first.")
        return 1

    bench_overlap(rng)
    bench_memory_scoring(rng)
    bench_rank(rng)

    print("\nnote: the model dominates end-to-end latency, so none of this makes a reply")
    print("arrive sooner. It is what makes running the guards on every turn free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
