"""`python -m ollie` — start the whole thing, or run a maintenance command.

Deliberately not a CLI framework. There are four verbs and argparse handles four verbs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import webbrowser

from . import config, hardware
from .ollama import Ollama, OllamaDown, select_model
from .store import Store

DEFAULT_PORT = 8765


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from . import api

    probe = hardware.probe()
    tier = config.tier_for(probe.ram_gb)
    print(f"\n  Ollie\n  {hardware.describe(probe, tier)}")

    async def preflight() -> str | None:
        """Uses its own client and closes it. The server's client is built later, inside
        uvicorn's loop, because an httpx pool cannot outlive the loop it was made in."""
        client = Ollama()
        try:
            version = await client.version()
        except OllamaDown:
            print("\n  Ollama is not running. Start it and try again:\n"
                  "      ollama serve\n", file=sys.stderr)
            return None
        try:
            model, _installed = await select_model(client, tier, args.model)
            print(f"  ollama {version}")
            if model:
                print(f"  model  {model}")
            else:
                print(f"  no suitable model installed. closest fit for this machine:\n"
                      f"      ollama pull {tier.candidates[0]}")
            return model
        finally:
            await client.aclose()

    chosen = asyncio.run(preflight())
    if chosen is None and not args.force:
        return 1
    # Hand the decision to the app without touching its client.
    api.S.model = chosen or args.model

    stats = Store().corpus_stats()
    print(f"  corpus {stats['sources']} sources, {stats['chunks']} passages")

    url = f"http://127.0.0.1:{args.port}"
    print(f"  ready  {url}\n")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_probe(_args: argparse.Namespace) -> int:
    probe = hardware.probe()
    tier = config.tier_for(probe.ram_gb)
    print(json.dumps({**probe.as_dict(), "tier": tier.name,
                      "context_cap": tier.context_cap,
                      "model_candidates": tier.candidates}, indent=2))
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    """Decrypt local records for debugging. Encryption should not make the database
    opaque to the person who owns it."""
    store = Store()
    if args.what == "corpus":
        print(json.dumps(store.corpus_stats(), indent=2))
        for row in store.db.execute(
                "SELECT title, category, chunk_count FROM sources ORDER BY title"):
            print(f"  {row['chunk_count']:5d}  {row['title']}")
        return 0

    rows = store.db.execute("SELECT id FROM profiles ORDER BY created_at DESC "
                            "LIMIT 1").fetchone()
    if not rows:
        print("no profile yet")
        return 0
    for m in store.memories(rows["id"]):
        flag = "!" if m["sensitivity"] != "normal" else " "
        print(f"{flag} [{m['kind']:<14}] {m['subject']} {m['predicate']} "
              f"{m['value']}  (conf {m['confidence']:.2f})")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .ingest import main as ingest_main

    sys.argv = ["ollie.ingest", "--books", str(Path(args.books)), "--tier", args.tier]
    return ingest_main()


def cmd_reset(args: argparse.Namespace) -> int:
    """Delete conversations and memories. Leaves the book index alone, since rebuilding
    it takes far longer than anything it protects."""
    if not args.yes:
        print("this deletes every profile, conversation and memory on this machine.")
        if input("type 'delete' to confirm: ").strip() != "delete":
            print("cancelled")
            return 1
    store = Store()
    with store.tx() as db:
        for table in ("messages", "memories", "memory_sources", "open_threads",
                      "capsules", "consent_receipts", "sessions", "personas", "profiles"):
            db.execute(f"DELETE FROM {table}")
    print("done. the book index is untouched.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="ollie", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    serve = sub.add_parser("serve", help="start Ollie (default)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--model", help="override the model tag")
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--force", action="store_true",
                       help="start even if Ollama is unreachable")
    serve.set_defaults(func=cmd_serve)

    sub.add_parser("probe", help="print hardware and tier").set_defaults(func=cmd_probe)

    dump = sub.add_parser("dump", help="decrypt local records for debugging")
    dump.add_argument("what", nargs="?", choices=["memories", "corpus"],
                      default="memories")
    dump.set_defaults(func=cmd_dump)

    reset = sub.add_parser("reset", help="delete all conversations and memories")
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_reset)

    ingest = sub.add_parser("ingest", help="index PDFs and EPUBs you already own")
    ingest.add_argument("--books", default=str(config.BOOKS))
    ingest.add_argument("--tier", choices=["a", "all"], default="all")
    ingest.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    if not args.cmd:
        args = parser.parse_args(["serve"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
