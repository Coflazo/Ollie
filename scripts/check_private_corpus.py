#!/usr/bin/env python3
"""Fail if private books, corpora, user data, or model weights enter Git.

The default check covers both the current index and every object reachable from
local refs. That matters because deleting a file in a later commit does not
remove it from clones of a public repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath


FORBIDDEN_DIRECTORIES = {
    ".ollie",
    "books",
    "corpus",
    "data",
    "exports",
    "graphify-out",
    "graphify_ws",
}
FORBIDDEN_SUFFIXES = {
    ".azw",
    ".azw3",
    ".bin",
    ".db",
    ".djvu",
    ".epub",
    ".gguf",
    ".jsonl",
    ".mobi",
    ".parquet",
    ".pdf",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
}
MAX_SOURCE_BYTES = 5 * 1024 * 1024


def git(*args: str, input_text: str | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def forbidden(path: str) -> bool:
    normal = path.replace("\\", "/")
    candidate = PurePosixPath(normal)
    parts = {part.casefold() for part in candidate.parts}
    return bool(parts & FORBIDDEN_DIRECTORIES) or candidate.suffix.casefold() in FORBIDDEN_SUFFIXES


def history_objects() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in git("rev-list", "--objects", "--all").splitlines():
        object_id, separator, path = line.partition(" ")
        if separator and path:
            rows.append((object_id, path))
    return rows


def oversized_blobs(objects: list[tuple[str, str]]) -> list[tuple[int, str]]:
    paths_by_id: dict[str, set[str]] = {}
    for object_id, path in objects:
        paths_by_id.setdefault(object_id, set()).add(path)

    metadata = git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_text="\n".join(paths_by_id) + "\n",
    )
    large: list[tuple[int, str]] = []
    for line in metadata.splitlines():
        object_id, object_type, size_text = line.split()
        size = int(size_text)
        if object_type == "blob" and size > MAX_SOURCE_BYTES:
            large.extend((size, path) for path in sorted(paths_by_id[object_id]))
    return large


def main() -> int:
    current = git("ls-files", "-z").split("\0")
    current = [path for path in current if path]
    history = history_objects()

    current_private = sorted(path for path in current if forbidden(path))
    historical_private = sorted({path for _, path in history if forbidden(path)})
    large = oversized_blobs(history)

    if not current_private and not historical_private and not large:
        print(
            f"clean: {len(current)} tracked paths and {len(history)} reachable named objects; "
            "no private corpus artifacts or oversized blobs"
        )
        return 0

    if current_private:
        print("private artifacts tracked now:", file=sys.stderr)
        for path in current_private:
            print(f"  {path}", file=sys.stderr)
    if historical_private:
        print("private artifacts reachable in Git history:", file=sys.stderr)
        for path in historical_private:
            print(f"  {path}", file=sys.stderr)
    if large:
        print("oversized blobs reachable in Git history:", file=sys.stderr)
        for size, path in sorted(large, reverse=True):
            print(f"  {size} bytes  {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
