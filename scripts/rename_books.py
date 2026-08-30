#!/usr/bin/env python3
"""Normalise the four loose Anna's Archive filenames in Books/ to the catalog convention.

The catalog convention is `Title - Author (Year or Edition).ext`. Four files sit at the
Books/ root with the exporter's raw metadata string as their filename; they also have no
category folder. This moves them into `10 - Emotion and Personality` under proper names.

Dry run by default. Pass --apply to actually move anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BOOKS = Path(__file__).resolve().parent.parent / "Books"
TARGET_DIR = "10 - Emotion and Personality"

# Matched on the leading fragment of the current filename, which is unique per file.
# The Duygular Sözlüğü attribution is recovered from its ISBN (9781781251294 is
# The Book of Human Emotions, Tiffany Watt Smith, Profile Books / Wellcome 2015); the
# exporter recorded it as "Bilinmeyen yazar", unknown author.
RENAMES = {
    "Duygular Sözlüğü": "Duygular Sözlüğü (The Book of Human Emotions) - Tiffany Watt Smith (2015).epub",
    "Gifts Differing": "Gifts Differing - Isabel Briggs Myers and Peter Myers (Revised Edition).epub",
    "How Emotions Are Made": "How Emotions Are Made - Lisa Feldman Barrett (2017).pdf",
    "Human Emotions": "Human Emotions - Jonathan H. Turner (2011).epub",
}


def plan() -> list[tuple[Path, Path]]:
    moves = []
    for src in sorted(BOOKS.glob("*")):
        if not src.is_file() or src.suffix.lower() not in {".epub", ".pdf"}:
            continue
        for prefix, new_name in RENAMES.items():
            if src.name.startswith(prefix):
                moves.append((src, BOOKS / TARGET_DIR / new_name))
                break
    return moves


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="perform the moves")
    args = ap.parse_args()

    moves = plan()
    if not moves:
        print("Nothing to rename; the four loose files are already normalised.")
        return 0

    for src, dst in moves:
        print(f"{'MOVE' if args.apply else 'DRY '}  {src.name}\n   -> {TARGET_DIR}/{dst.name}\n")

    if not args.apply:
        print(f"{len(moves)} file(s) would move. Re-run with --apply.")
        return 0

    (BOOKS / TARGET_DIR).mkdir(exist_ok=True)
    for src, dst in moves:
        if dst.exists():
            print(f"refusing to overwrite existing {dst.name}", file=sys.stderr)
            return 1
        src.rename(dst)
    print(f"Moved {len(moves)} file(s) into {TARGET_DIR}/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
