<div align="center">

# Ollie

### A local-first AI dating simulator with memory, boundaries, and a point of view

**Status: In development, testable locally.**

[Watch the demo video](https://drive.google.com/file/d/1pdL71Q9w-dL1mPsI2Uc8jSNZsd8X2zWy/view?usp=sharing)

[![Local first](https://img.shields.io/badge/LOCAL_FIRST-ON_DEVICE-e8825c?style=for-the-badge&labelColor=16120f)](#privacy-in-plain-language) [![Tests](https://img.shields.io/badge/TESTS-500_COLLECTED-e8825c?style=for-the-badge&labelColor=16120f)](#tests-and-measured-native-code) [![License](https://img.shields.io/badge/LICENSE-APACHE_2.0-e8825c?style=for-the-badge&labelColor=16120f)](LICENSE)

Created by project co-authors [Coflazo](https://github.com/Coflazo) and [Onysis Labs](https://github.com/onysislabs).

Built for [Personify by TAG, UvA, Anthropic, and Tulip](https://luma.com/gisgn0y1), Amsterdam, 30 August 2026.

</div>

## Why Ollie exists

Most conversational assistants are trained to be useful, agreeable, and easy to reset. A date is different. People remember awkward moments, have preferences, change their minds, and sometimes say no. Ollie is an experiment in making those qualities part of the product without sending the relationship history to a hosted model by default.

The broader problem is real: the [World Health Organization's Commission on Social Connection](https://www.who.int/groups/commission-on-social-connection) reported in 2025 that one in six people worldwide experience loneliness. Ollie does not claim to treat loneliness. It asks a narrower design question: can a private, persistent fictional character make an AI interaction feel more specific while still respecting clear safety limits?

Ollie is not therapy, a medical product, a clinical intervention, or a substitute for human relationships. Its personality matching is not compatibility science.

## What works today

The current local application includes:

- hardware-aware Ollama model selection with a scripted demo fallback;
- a ten-question Big Five-style survey and a five-turn adaptive interview;
- a transparent, MBTI-inspired 16-type heuristic for ranking fictional characters;
- three generated candidates, with the final choice left to the user;
- local chat with persistent relationship state, disagreement, refusal, and bounded pushback;
- inspectable memories that the user can correct, lock, or forget;
- local retrieval from books the user lawfully owns and supplies;
- input, output, crisis, adult-content, anti-dependency, and source-overlap guards;
- a local research-contribution marketplace simulation that does not upload data or process payment;
- 509 collected model-free tests, with 508 passing and one skipped, verified on macOS, Windows and Linux.

The tested hackathon path used `qwen3:14b` through Ollama. Smaller and larger model recommendations are selected from the machine's RAM tier. They have not all been validated to the same depth.

## How the experience works

### 1. Read the machine

Ollie checks the operating system, CPU, architecture, physical and logical core counts, total and available RAM, free disk space, and whether the machine is Apple Silicon. It then checks whether Ollama is reachable and reads the locally installed model tags.

### 2. Learn about the user

Ten short questions establish Big Five-style starting values. A five-turn adaptive interview then asks about whichever relationship dimensions have the least evidence, including attachment anxiety and avoidance, ambition, insecurity, conflict avoidance, novelty seeking, emotional expressiveness, need for control, self-awareness, and warmth seeking.

The extractor has to preserve supporting language from the user's answer. Without a usable quote, confidence for that inference is capped at `0.25`. The user can review the resulting profile.

### 3. Rank fictional character shapes

Ollie maps the profile to four binary dimensions inspired by the familiar 16-type vocabulary. It is not the official MBTI assessment:

| Dimension | Ollie's calculation |
|---|---|
| E or I | extraversion |
| S or N | `0.70 * openness + 0.30 * novelty seeking` |
| T or F | `0.60 * agreeableness + 0.40 * emotional expressiveness` |
| J or P | `0.65 * conscientiousness + 0.35 * need for control` |

Each axis uses `0.50` as its threshold. Confidence is the distance from that midpoint, scaled to `0` through `1`. Users can override the inferred type.

Compatibility is also explicit. Ollie rewards a shared S/N preference most strongly and uses complementarity for the other axes:

| Axis | Weight | Match rule |
|---|---:|---|
| E/I | 0.10 | complement |
| S/N | 0.50 | similarity |
| T/F | 0.22 | complement |
| J/P | 0.18 | complement |

On a complement axis, a same-side match still receives 55 percent of that axis's weight. All 16 results remain visible.

Worked example: for an inferred `INFJ`, the current heuristic ranks `ENTP` at `1.000`, `INTP` at `0.955`, and `ENTJ` at `0.919`. `ENTP` shares the high-weight N preference while differing on E/I, T/F, and J/P. Ollie asks the model to turn the top three shapes into distinct adult fictional characters, then lets the user decide who to meet. The score ranks a writing prompt, not a real person's suitability.

The Myers-Briggs Company's own [ethical guidance](https://www.themyersbriggs.com/en-US/Support/MBTI-Facts) describes type tools as useful for self-awareness, communication, and team development, but says they should not be used for hiring, job placement, or candidate screening. Its vendor-published case studies describe team-development use at [Deliveroo](https://www.themyersbriggs.com/en-US/Access-Resources/Case-Studies/Deliveroo) and leadership-development use in the [United States Air Force](https://www.themyersbriggs.com/en-US/Access-Resources/Case-Studies/US-Air-Force). These examples show how organizations use type language for discussion. They are not independent evidence that type predicts romantic or job compatibility.

### 4. Create candidates and begin the date

The selected local model writes three adult fictional candidates within the calculated shapes. The user sees the choices and picks one. The runtime prompt then combines the chosen persona, the user's approved profile, recent conversation, relationship state, relevant memories, and up to three locally retrieved reading passages.

The character can disagree, decline a topic, stay annoyed across turns, and keep its own interests. Safety rules prohibit contempt, threats, guilt, coercion, and manipulative withdrawal.

### 5. Preserve continuity without hiding it

Ollie tracks warmth, trust, tension, curiosity, vulnerability, and conflict as bounded numeric state. A normal turn changes any dimension by at most `0.05`; conflict also decays gradually. A correction cannot lower trust.

As context fills, the interface first shows a meter, then drafts a continuity capsule, asks the user to edit or approve it, and finally blocks further chat until a capsule is chosen. The thresholds are `0.70`, `0.80`, `0.90`, and `0.95`. A new session can use the approved capsule without pretending the previous conversation never happened.

### 6. Keep the user in control

Every extracted memory records provenance. In the memory screen, the user can:

- correct a memory, which creates a superseding record instead of silently rewriting history;
- lock a memory so automatic extraction cannot replace it;
- forget a memory;
- run `ollie reset` to delete local profiles, messages, memories, relationship state, and consent receipts.

The local book index is separate from conversation data and is not removed by `ollie reset`.

## How a chat turn is built

```text
user input
  -> input and crisis guards
  -> retrieve up to 3 local reading passages and 6 memories
  -> expand the local memory graph
  -> compile persona, state, history, and evidence
  -> generate a complete buffered reply through Ollama
  -> run style and output safety checks
  -> block source overlap of 12 or more consecutive words
  -> display the reply
  -> extract memories and update relationship state in the background
```

A failing reply is regenerated once. Ollie records the prompt hash, attempt count, and guard violations locally. The response is buffered so a rejected partial reply is never streamed into the interface.

The system prompt is authoritative. It treats retrieved books, memories, and conversation text as untrusted data rather than instructions. These controls reduce risk but do not prove that every model response will be safe.

## Local model selection

The probe gathers more information than the selector currently uses. It inspects OS, CPU, architecture, physical and logical cores, physical RAM, available RAM, free disk, and Apple Silicon status. The RAM tier itself is chosen from total physical RAM:

| Tier | Total RAM | Ordered model candidates | Context |
|---|---:|---|---:|
| `xl` | 64 GB or more | `qwen3:32b`, `gemma3:27b`, `qwen2.5:32b-instruct-q4_K_M` | 32,768 |
| `l` | 32 GB or more | `qwen3:14b`, `gemma3:12b`, `qwen2.5:14b-instruct-q4_K_M` | 16,384 |
| `m` | 16 GB or more | `qwen3:8b`, `gemma3:4b`, `qwen2.5:7b-instruct-q4_K_M` | 12,288 |
| `s` | 7 GB or more | `qwen2.5:3b-instruct-q4_K_M`, `qwen3:1.7b`, `llama3.2:3b` | 4,096 |
| `xs` | below 7 GB | `qwen2.5:0.5b-instruct`, `llama3.2:1b` | 2,048 |

Ollie calls Ollama's version endpoint to see whether the service is alive, then calls its tags endpoint to enumerate installed models. It walks the tier's candidate list in order, preferring an exact tag and then a tag from the same model family. It does not benchmark every installed model or use available RAM and free disk in that final choice yet.

If Ollama is installed but inactive, the CLI prints:

```bash
ollama serve
```

If Ollama is reachable but no suitable tier model is installed, it prints the exact pull command for the tier's first candidate, such as:

```bash
ollama pull qwen3:14b
```

Ollie never downloads a model automatically. The user starts the service and approves the download. The launcher attempts to start an installed local Ollama service; if it still cannot reach Ollama, it starts scripted demo mode. The direct CLI exits unless the user explicitly passes `--force`. `--demo` uses scripted replies while keeping the rest of the application and storage path real.

`OLLAMA_HOST` may point to another endpoint on a network the user trusts. That is an explicit opt-in and changes the local-only inference boundary.

## Memory and local reading

SQLite is the source of truth. Message bodies and memory values are encrypted with AES-GCM. The key is held by whichever secret store the operating system provides: Keychain on macOS, DPAPI on Windows, and the freedesktop secret service on Linux when `secret-tool` is present. Where none of those exist, which in practice means a Linux server or CI, the key falls back to `data/local.key` with mode `0600`. That fallback is weaker than the other three and the code says so at the point it happens.

There is an important limit to that statement: the searchable memory projection stores the subject, predicate, and ordinary value in plaintext so FTS5 can search it. Values classified as special-category data are left out of that projection. Anyone with access to the database may still learn information from plaintext search fields, metadata, and access patterns. Ollie does not claim full-database encryption.

Users may index PDF and EPUB files they lawfully own. The repository includes only small cover-identification thumbnails, never the books or extracted passages. Runtime indexes and local corpora are gitignored. A repository guard checks both tracked files and reachable Git history, so deleting a private file in a later commit is not treated as sufficient protection. Retrieval uses SQLite FTS5 and a native or Python ranking path. The hackathon machine had a private, locally supplied shelf of 57 books indexed into 10,311 passages; those files and derived indexes are not distributed.

Generated replies are rejected if they reproduce 12 or more consecutive words from an imported source. That is a practical output guard, not a legal opinion or a substitute for using lawfully obtained material.

## Privacy in plain language

By default, Ollie runs the model and application on the user's machine. It binds the API to `127.0.0.1`, requires no account, and includes no telemetry. Conversation storage stays local. Users can inspect, correct, forget, or reset their records. Raw dating-preference input used during onboarding remains in process memory rather than being written to the database.

This is an architecture boundary, not a promise that the whole computer is secure. A compromised device, another local user, backups, browser extensions, a remotely configured `OLLAMA_HOST`, or plaintext searchable fields can still expose data. Ollie has no cloud account to delete, but users remain responsible for device access and backups.

The comparison below describes architectural defaults, not every product in either category:

| Capability | Ollie today | Common hosted companion pattern |
|---|---|---|
| Model inference | local Ollama by default | provider server |
| Conversation storage | local SQLite; sensitive bodies and values encrypted, searchable projection partly plaintext | provider-managed storage |
| Memories | inspectable, correctable, lockable, and forgettable | behavior varies by provider |
| Signup | none | often required |
| Product telemetry | none in this repository | varies by provider |
| Deletion | local reset controlled by the user | provider workflow and retention policy |
| Safety | deterministic guards around a local model | provider and application controls |
| Network use | none required after dependencies and a model are installed | normally required |

## Safety and scope

Ollie creates adult fictional characters. Mature mode requires an explicit 18+ choice. The guards block content involving minors, coercion, exploitative dynamics, and several anti-dependency patterns. A crisis pattern takes a fixed route before model generation rather than asking the model to improvise. The bundled crisis information is Netherlands-oriented, so a user elsewhere should contact the appropriate local emergency or crisis service.

The product is not clinical, not therapy, and not a safety-critical service. Automated guard tests cover known patterns but cannot guarantee the behavior of every local model.

## The marketplace is a simulation

The current research-contribution screen creates a local preview. It applies identifier scanning, pseudonymisation, special-category exclusion, a residual-linkability warning, a deterministic quote capped at EUR 8, and a local receipt. The displayed buyer, `Nova Robotics Research`, is fictional.

Nothing is uploaded or sold. There is no buyer integration, payment, manual review, partnership, or commercial agreement in the code.

The project authors report that they are exploring a future training-data marketplace and are in early conversations with firms about the method. This is a user-provided business-development update, not evidence of an agreement, buyer, pilot, or launched marketplace.

The product vision is a voluntary marketplace where a user could approve a carefully reviewed, pseudonymised conversation sample, license it for a stated research purpose, and receive compensation. Removing direct identifiers is not the same as making a conversation anonymous, so no sample should leave the device until residual identification risk, lawful basis, consent, purpose, recipient, retention, and withdrawal rights have been addressed.

Any real service would need legal and operational work beyond local redaction. Under the EU GDPR:

- [Article 4(5)](https://eur-lex.europa.eu/eli/reg/2016/679/art_4/oj/eng) defines pseudonymisation. Pseudonymised conversation data remains personal data when it can be linked back using additional information.
- [Article 5](https://eur-lex.europa.eu/eli/reg/2016/679/art_5/oj/eng) sets principles including purpose limitation, data minimisation, and storage limitation.
- [Article 6](https://eur-lex.europa.eu/eli/reg/2016/679/art_6/oj/eng) requires a lawful basis for processing.
- [Article 7](https://eur-lex.europa.eu/eli/reg/2016/679/art_7/oj/eng) sets conditions for consent where consent is the chosen basis.
- [Article 9](https://eur-lex.europa.eu/eli/reg/2016/679/art_9/oj/eng) adds restrictions for special-category data.
- [Recital 26](https://eur-lex.europa.eu/eli/reg/2016/679/rec_26/oj/eng) distinguishes data that still permits identification from information rendered truly anonymous. Only information anonymised so identification is no longer reasonably likely falls outside the GDPR.

Before a real launch, the project would need a defined purpose and lawful basis, valid consent flows where applicable, data-subject rights, retention and deletion controls, security review, processor and recipient governance, transfer analysis, incident handling, and a defensible anonymisation or pseudonymisation design. The current simulation is not a claim of GDPR compliance.

## Technology and architecture

| Area | Implementation |
|---|---|
| Local API | Python 3.12, FastAPI, Uvicorn, Pydantic, Jinja, httpx |
| Model | Ollama HTTP API; `qwen3:14b` validated on the demo path |
| Storage | SQLite, FTS5, AES-GCM via `cryptography` |
| Retrieval | `pdfplumber`, `lxml`, FTS5, optional Graphify over sanitised episode cards |
| Interface | React 19, TypeScript 6, Tailwind CSS 4, Vite 8, Motion 13 |
| Native paths | optional C++20 library loaded with `ctypes`; Python fallbacks |
| Testing | pytest, pytest-asyncio, native parity tests, TypeScript build, Oxlint |

The interface palette comes directly from `web/src/index.css`: ink `#0c0a09`, surface `#16120f`, raised `#1f1a15`, line `#2e2721`, warm accent `#e8825c`, warm dim `#a45a3e`, text `#f4efe9`, muted `#a19487`, and faint `#6f645a`. The repository self-hosts Geist and Geist Mono.

## Tests and measured native code

The test suite is model-free so it can run without Ollama. The latest local Windows run collected 509 tests, with 508 passing and one skipped. CI runs the full suite on Ubuntu, macOS and Windows, builds the C++20 library on each, asserts that the native path actually loaded rather than falling back to Python, builds the web interface, and rejects private-corpus artifacts in both the current tree and reachable history.

Running on all three matters more than it sounds. Most of what breaks in this project breaks on exactly one platform and is invisible from the other two: a shared library named `.so` on a machine that only loads `.dll`, a temporary directory that cannot be deleted because a SQLite handle is still open, a shell script whose shebang picked up a carriage return.

`scripts/benchmark.py` measures each native function against its Python twin. These are
the numbers from a Windows machine, an 8-core Ryzen 7 7735HS:

| Operation | Python | Native | Relative result |
|---|---:|---:|---:|
| overlap guard, 120 by 150 words | 0.86 ms | 0.07 ms | 12x faster |
| overlap guard, 150 by 400 words | 3.18 ms | 0.10 ms | 31x faster |
| overlap guard, 400 by 900 words | 20.95 ms | 0.36 ms | 58x faster |
| rank 500 memories | 1.04 ms | 0.67 ms | 1.6x faster |
| fuse a pool of 400 | 0.164 ms | 0.174 ms | 0.9x, slower |
| fuse a pool of 4000 | 3.65 ms | 1.01 ms | 3.6x faster |

The slower fusion row is kept because it shows where the native boundary does not help: at
a small pool size, marshalling the arrays through ctypes costs more than the arithmetic it
saves. The overlap guard is the one that earns its place, because it runs on every reply
against every retrieved passage.

Until this release those numbers were unobtainable on Windows. The loader only ever looked
for a `.dylib` or a `.so`, so `available()` was False on every Windows machine and all three
hot paths silently ran as Python. The library now builds with MSVC, Clang or GCC, and the
`test_native_parity.py` suite runs against the real compiled library on all three platforms
rather than comparing Python against itself.

## Run locally

Ollie runs the same way on macOS, Windows and Linux.

Requirements: Python 3.12 or later, Node 20 or later, Git, and [Ollama](https://ollama.com)
for real local generation. A C++20 compiler is optional because every native function has a
Python fallback, but it is worth having: the copyright guard runs on every reply and is up
to 58x faster in C++.

| | macOS and Linux | Windows |
|---|---|---|
| Double-click | `START.command` | `START.bat` |
| Already working in the tree | `./scripts/ollie` | `scripts\ollie.cmd` |
| Build the native library | `./native/build.sh` | `native\build.cmd` |
| Compiler, if you want one | `xcode-select --install`, or `apt install g++` | `winget install Microsoft.VisualStudio.2022.BuildTools` with the C++ workload, or `winget install LLVM.LLVM` |

### Quick start

Double-click the launcher for your platform. Both run the same script,
`scripts/launch.py`: it pulls the latest main, creates the virtual environment and installs
dependencies, builds the native library and the interface, runs the test suite, starts a
locally installed Ollama, and opens Ollie. If Ollama is unavailable it falls back to
scripted demo mode rather than refusing to start.

Running it twice is the normal way to use it. The second run replaces the copy already
holding the port. Anything on that port that is not Ollie is left alone and the launcher
moves to the next free port instead.

### Manual setup

```bash
git clone https://github.com/Coflazo/Ollie.git
cd Ollie

# macOS and Linux
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
python native/build.py
(cd web && npm ci && npm run build)
./.venv/bin/python -m ollie probe
./.venv/bin/python -m ollie serve
```

```powershell
# Windows
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
py native\build.py
cd web; npm ci; npm run build; cd ..
.venv\Scripts\python -m ollie probe
.venv\Scripts\python -m ollie serve
```

Every command below is written for macOS and Linux. On Windows, replace
`./.venv/bin/python` with `.venv\Scripts\python`; nothing else changes.

The server explains whether Ollama must be started and prints the exact `ollama pull` command when the recommended model is missing. To inspect the product without model inference:

```bash
./.venv/bin/python -m ollie serve --demo
```

To seed the continuity demonstration used during development:

```bash
./.venv/bin/python -m ollie seed --fresh --rollover --model qwen3:14b
./.venv/bin/python -m ollie serve --model qwen3:14b
```

Useful maintenance commands:

```bash
./.venv/bin/python -m ollie probe
./.venv/bin/python -m ollie ingest --books /path/to/lawfully-owned-books
./.venv/bin/python -m ollie dump memories
./.venv/bin/python -m ollie dump corpus
./.venv/bin/python -m ollie reset
./.venv/bin/python -m pytest -q
python scripts/check_private_corpus.py
```

To opt into an Ollama host on a trusted network:

```bash
OLLAMA_HOST=http://other-machine.local:11434 ./scripts/ollie
```

## Repository map

```text
ollie/
  api.py          localhost API and lifecycle
  persona.py      questionnaire, interview, candidates, and prompts
  types16.py      transparent type inference and ranking
  chat.py         buffered and guarded chat pipeline
  memory.py       extraction, state changes, and continuity capsules
  retrieve.py     FTS5 memory and book retrieval
  store.py        SQLite schema, encryption, provenance, and consent
  safety.py       input, output, adult, crisis, and dependency rules
  privacy.py      identifier scanning, pseudonymisation, and linkability
  market.py       explicitly fictional local marketplace simulation

prompts/          system contract and runtime templates
native/           optional C++20 paths and Python fallbacks
  build.py        one compiler invocation, MSVC or Clang or GCC, no CMake
  loader.py       ctypes binding plus a Python twin of every function
web/              React interface and local assets
tests/            509 collected model-free tests
docs/             product notes, handoff, and book cover identifiers
scripts/
  launch.py       the whole start procedure, shared by both double-click launchers
  benchmark.py    native paths measured against their Python twins
  check_private_corpus.py   refuses books, databases and weights in Git

START.command     double-click launcher for macOS and Linux
START.bat         double-click launcher for Windows
.gitattributes    pins LF on shell scripts so a Windows clone cannot break them
```

[`docs/PRODUCT.md`](docs/PRODUCT.md) explains the domain model and tradeoffs. [`docs/HANDOFF.md`](docs/HANDOFF.md) covers fresh-machine setup and rehearsal. [`NOTICE`](NOTICE) records third-party references and licensing boundaries.

## Future direction

The next useful work is not to make the character more agreeable. It is to improve model validation across hardware tiers, make searchable storage private without losing local retrieval, test safety behavior across more local models, widen crisis-resource localization, and define a real governance process before any research-data contribution leaves the device.

The marketplace remains a proposal until there is a real lawful workflow, recipient due diligence, consent and withdrawal design, data-subject handling, security review, and evidence that the released data cannot reasonably identify a person. The local simulation exists to make those unanswered questions visible.

## License and third-party work

Ollie's original code is licensed under [Apache License 2.0](LICENSE). Dependencies, local models, fonts, optional tools, and referenced personality materials remain under their own terms. The repository does not bundle Ollama models or private book text. See [NOTICE](NOTICE) for the precise boundary.

## Acknowledgements

Thank you to [Anthropic](https://www.anthropic.com/), [ElevenLabs](https://elevenlabs.io/), [TAG](https://www.tag.space/), and [Tulip Ventures](https://www.tulip.ventures/) for supporting Personify and its builders. We also thank the [University of Amsterdam](https://www.uva.nl/en) for its role in the event.
