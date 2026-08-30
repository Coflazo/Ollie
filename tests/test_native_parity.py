"""The C++ and the Python must agree, or the native path is a source of silent bugs.

Ollie picks the native implementation when the shared library loads and the Python one
when it does not. That is only safe if the two are indistinguishable, so these tests run
both on the same inputs, including randomised ones, which is where hand-ported code
actually diverges, and compare.

The suite passes whether or not the library is built. When it is missing, the native calls
fall through to Python and the comparisons become trivially true; `test_native_is_built`
reports which mode ran so a green suite is never mistaken for coverage it did not have.
"""

from __future__ import annotations

import random
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "native"))
import loader  # noqa: E402

WORDS = ["the", "quick", "brown", "fox", "attachment", "anxious", "repair", "trust",
         "conversation", "boundary", "desire", "listen", "apologise", "tuesday"]


def test_native_is_built() -> None:
    """Not an assertion about correctness, a report so CI output says which path ran."""
    print(f"\nnative status: {loader.status()}")
    assert loader.status()


# ------------------------------------------------------------------- overlap guard


@pytest.mark.parametrize("reply,source,expected", [
    ("", "", 0),
    ("hello", "", 0),
    ("nothing in common here", "entirely different words", 0),
    ("the quick brown fox", "the quick brown fox", 4),
    ("a the quick brown fox b", "x the quick brown fox y", 4),
    ("Attachment styles are not destiny", "attachment styles are NOT destiny!", 5),
])
def test_overlap_known_cases(reply: str, source: str, expected: int) -> None:
    assert loader.longest_overlap(reply, source) == expected
    assert loader.py_longest_overlap(reply, source) == expected


def test_overlap_ignores_punctuation_and_case() -> None:
    a = "Secure attachment, it turns out, is learnable."
    b = "secure attachment it turns out is learnable"
    assert loader.longest_overlap(a, b) == 7


@pytest.mark.parametrize("seed", range(40))
def test_overlap_parity_on_random_input(seed: int) -> None:
    rng = random.Random(seed)
    a = " ".join(rng.choice(WORDS) for _ in range(rng.randint(0, 40)))
    b = " ".join(rng.choice(WORDS) for _ in range(rng.randint(0, 40)))
    assert loader.longest_overlap(a, b) == loader.py_longest_overlap(a, b), (a, b)


def test_overlap_is_symmetric() -> None:
    a, b = "one two three four five", "zero one two three nine"
    assert loader.longest_overlap(a, b) == loader.longest_overlap(b, a)


# ----------------------------------------------------------------- retrieval rank


def test_rank_orders_by_fused_score() -> None:
    lexical = [0.9, 0.5, 0.7]
    category = [0, 1, 0]
    lengths = [2000, 500, 1800]
    assert loader.rank(lexical, category, lengths, 3) == \
        loader.py_rank(lexical, category, lengths, 3)


def test_rank_respects_k() -> None:
    assert len(loader.rank([0.1] * 10, [0] * 10, [100] * 10, 3)) == 3
    assert len(loader.rank([0.1] * 2, [0] * 2, [100] * 2, 9)) == 2


def test_rank_handles_empty() -> None:
    assert loader.rank([], [], [], 5) == []
    assert loader.rank([0.5], [0], [100], 0) == []


def test_rank_ties_break_toward_lower_index() -> None:
    """Deterministic ordering matters: the demo must not reshuffle between runs."""
    out = loader.rank([0.5, 0.5, 0.5], [0, 0, 0], [900, 900, 900], 3)
    assert out == [0, 1, 2]
    assert out == loader.py_rank([0.5, 0.5, 0.5], [0, 0, 0], [900, 900, 900], 3)


@pytest.mark.parametrize("seed", range(30))
def test_rank_parity_on_random_input(seed: int) -> None:
    rng = random.Random(seed + 1000)
    n = rng.randint(1, 60)
    lexical = [rng.random() for _ in range(n)]
    category = [rng.randint(0, 1) for _ in range(n)]
    lengths = [rng.randint(50, 4000) for _ in range(n)]
    k = rng.randint(1, n)
    assert loader.rank(lexical, category, lengths, k) == \
        loader.py_rank(lexical, category, lengths, k)


# ---------------------------------------------------------------- memory scoring


def _memory_args(rng: random.Random, n: int):
    terms = sorted({rng.choice(WORDS) for _ in range(rng.randint(1, 8))})
    texts = [" ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 14)))
             for _ in range(n)]
    ints: list[int] = []
    doubles: list[float] = []
    for _ in range(n):
        ints += [rng.randint(1, 5), rng.randint(0, 1), rng.randint(0, 1),
                 rng.randint(0, 2), rng.randint(0, 1)]
        doubles += [rng.random(), rng.random() * 500]
    return terms, texts, ints, doubles


def test_memory_scoring_handles_empty() -> None:
    assert loader.score_memories([], [], [], []) == []
    assert loader.py_score_memories([], [], [], []) == []


def test_memory_scoring_rewards_a_term_match() -> None:
    args = (["climbing"], ["user likes climbing", "user dislikes coriander"],
            [3, 0, 0, 0, 0, 3, 0, 0, 0, 0], [0.9, 1.0, 0.9, 1.0])
    scores = loader.score_memories(*args)
    assert scores[0] > scores[1]


def test_special_category_is_penalised_more_than_personal() -> None:
    base = ([], ["x", "x", "x"],
            [3, 0, 0, 0, 0,  3, 0, 0, 1, 0,  3, 0, 0, 2, 0],
            [0.9, 1.0] * 3)
    normal, personal, special = loader.score_memories(*base)
    assert normal > personal > special


def test_a_locked_memory_outranks_an_otherwise_identical_one() -> None:
    args = ([], ["x", "x"], [3, 0, 0, 0, 0, 3, 1, 0, 0, 0], [0.9, 1.0, 0.9, 1.0])
    unlocked, locked = loader.score_memories(*args)
    assert locked > unlocked


@pytest.mark.parametrize("seed", range(30))
def test_memory_scoring_parity_on_random_input(seed: int) -> None:
    rng = random.Random(seed + 5000)
    args = _memory_args(rng, rng.randint(1, 40))
    native_scores = loader.score_memories(*args)
    python_scores = loader.py_score_memories(*args)
    assert len(native_scores) == len(python_scores)
    for a, b in zip(native_scores, python_scores):
        assert abs(a - b) < 1e-9, (a, b)


# ------------------------------------------------------------------------- probe


def test_physical_ram_is_plausible() -> None:
    ram = loader.physical_ram()
    assert ram == 0 or 1e9 < ram < 2e12, f"implausible RAM reading: {ram}"


# --------------------------------------------------- ragged and hostile input

def test_ragged_arrays_do_not_read_out_of_bounds() -> None:
    """The native function reads ints[i*5+4] and doubles[i*2+1] for every i below the
    record count. It used to take that count on trust, so a caller whose numeric arrays
    were shorter than the text list caused an out-of-bounds heap read: not a wrong score,
    memory corruption. Both paths now clamp to what all three structures agree on.
    """
    terms = ["climb"]
    texts = ["a climb", "b", "c", "d"]   # implies four records
    ints = [3, 0, 0, 0, 0, 3, 0, 0, 0, 0]  # holds two
    doubles = [0.9, 1.0, 0.9, 1.0]         # holds two

    native_scores = loader.score_memories(terms, texts, ints, doubles)
    python_scores = loader.py_score_memories(terms, texts, ints, doubles)

    assert len(native_scores) == 2, native_scores
    assert len(python_scores) == 2, python_scores
    for a, b in zip(native_scores, python_scores):
        assert abs(a - b) < 1e-9


def test_a_newline_in_a_value_does_not_shift_later_records() -> None:
    """Newline is the record separator inside the blob passed to C++, so an unescaped one
    in a value silently moved every following record onto the wrong numbers. The binding
    strips them now, at the boundary that owns the encoding.
    """
    terms = ["climb"]
    texts = ["a climb", "has\na newline", "c"]
    ints = [5, 0, 0, 0, 0, 1, 0, 0, 0, 0, 3, 0, 0, 0, 0]
    doubles = [0.9, 1.0, 0.1, 1.0, 0.5, 1.0]

    native_scores = loader.score_memories(terms, texts, ints, doubles)
    python_scores = loader.py_score_memories(terms, texts, ints, doubles)

    assert len(native_scores) == 3
    for a, b in zip(native_scores, python_scores):
        assert abs(a - b) < 1e-9
    # The record that actually matches the query must still rank first.
    assert native_scores[0] == max(native_scores)


def test_empty_and_degenerate_memory_input() -> None:
    assert loader.score_memories([], [], [], []) == []
    assert loader.score_memories(["x"], [], [], []) == []
    # Texts present but no numbers at all: nothing can be scored.
    assert loader.score_memories(["x"], ["a", "b"], [], []) == []

# ------------------------------------------------------------------ stale libraries


def test_a_stale_library_falls_back_instead_of_crashing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A library built before a function was added must not take the application down.

    This is the ordinary state of a working tree after a pull that touched the C++, because
    the launcher only builds when the file is absent. Such a library loads perfectly well
    and then raises AttributeError at the first call to the symbol it does not have. The
    Python twin exists so the native path is never load-bearing, and that guarantee is only
    real if the loader treats an incomplete library as an absent one.
    """

    class Incomplete:
        """Loads cleanly, but predates `ollie_score_memories`."""

        def __getattr__(self, name: str):
            if name == "ollie_score_memories":
                raise AttributeError(f"dlsym(0x0, {name}): symbol not found")
            return types.SimpleNamespace(restype=None, argtypes=None)

    monkeypatch.setattr(loader, "_lib", None)
    monkeypatch.setattr(loader, "_library_path", lambda: Path(__file__))
    monkeypatch.setattr(loader.ctypes, "CDLL", lambda _path: Incomplete())

    assert loader._load() is None, "an incomplete library was accepted as usable"
    assert not loader.available()
    assert "stale" in loader.status(), loader.status()

    # And the point of all that: the function still returns the right answer.
    args = _memory_args(random.Random(1), 6)
    assert loader.score_memories(*args) == loader.py_score_memories(*args)
