<div align="center">

# Ollie

### A local-first architecture for personalised conversational companions

Coflazo · Onysis Labs

[![Demo](https://img.shields.io/badge/▶_WATCH-THE_DEMO-e8825c?style=for-the-badge&labelColor=16120f)](https://drive.google.com/file/d/1pdL71Q9w-dL1mPsI2Uc8jSNZsd8X2zWy/view?usp=sharing) [![Tests](https://img.shields.io/badge/TESTS-509_COLLECTED-e8825c?style=for-the-badge&labelColor=16120f)](#5-evaluation) [![Platforms](https://img.shields.io/badge/VERIFIED_ON-MACOS_·_WINDOWS_·_LINUX-e8825c?style=for-the-badge&labelColor=16120f)](#44-cross-platform-execution) [![License](https://img.shields.io/badge/LICENSE-APACHE_2.0-e8825c?style=for-the-badge&labelColor=16120f)](LICENSE)

**Artifact status: in development, runnable locally.** Free and open source under [Apache 2.0](LICENSE).

A screen recording of the system in operation is available [here](https://drive.google.com/file/d/1pdL71Q9w-dL1mPsI2Uc8jSNZsd8X2zWy/view?usp=sharing).

</div>

---

## Abstract

Conversational companion products are converging on a single architecture: one personality, authored once and served to every user, running on a provider's infrastructure, with the conversation history retained under terms the user does not control. Ollie is an artifact exploring the opposite arrangement. It infers a personality profile for the individual user from a ten-item survey and a five-turn adaptive interview, maps that profile onto a character shape using a heuristic whose weights are published and overridable, generates three candidate fictional personas from that shape, and then sustains an ongoing conversation with the one the user selects. Model inference, storage, retrieval, and safety enforcement all execute on the user's own machine, and the system makes no network request after installation.

We describe the design, the implementation, and the engineering properties we measured: a 509-test model-free suite passing on three operating systems, and a C++ hot path that reduces the per-reply source-overlap guard from 20.95 ms to 0.36 ms on a 400-by-900-word comparison. We report no user study. No claim is made here about therapeutic effect, wellbeing, loneliness, or the quality of the personality match, and Section 5.3 states precisely which questions the artifact leaves unanswered.

**Keywords:** local-first software, on-device inference, conversational agents, privacy by architecture, personality modelling, retrieval-augmented generation.

---

## 1. Statement of need

### 1.1 One personality, served to everyone

A companion product ships a character that was authored before any particular user arrived. Every user meets the same personality; only the transcript differs. The character is also, as a rule, agreeable, because agreeableness is easier to build and correlates with engagement. The result is a category of software optimised for pleasantness rather than for resembling a person.

Ollie asks a different question. Given evidence about a specific user, which character would that user actually get along with, and can the system construct and perform it? The rest of the system follows from taking that question seriously:

A companion that forgets the user is not close to anyone. Memory therefore persists across sessions, carries provenance for every extracted fact, and survives the end of a conversation through a continuity capsule the user reviews and approves rather than a summary written silently.

A companion that agrees with everything is not a person. The character therefore disagrees, declines topics, remains annoyed across turns, and holds interests the user never supplied.

### 1.2 Locality as a security property

Running the model locally is a security decision before it is a philosophical one.

Sending a conversation of this kind to a hosted model means accepting a policy commitment: that the content is not logged, not retained beyond a stated window, not used for training, not exposed by a breach, not read by staff during incident response, and not produced under legal compulsion. Each of those is a promise about future behaviour by a third party. Policies are revised, companies are acquired, and infrastructure is compromised.

Executing the model on the user's machine replaces that set of promises with a structural property: the conversation does not cross the network, so there is no remote copy to leak, subpoena, retain, or retrain on. This is a claim about system architecture and not about the security of the user's computer as a whole. Section 8 states the residual exposures precisely.

### 1.3 Contributions

1. An end-to-end companion system in which inference, storage, retrieval, and safety enforcement are all local, with no network dependency after installation (Sections 3 and 4).
2. A personality-matching heuristic that is fully specified, inspectable, and user-overridable, rather than an opaque scoring function (Sections 3.3 and 3.4).
3. A memory model with per-fact provenance, correction by supersession rather than overwrite, user locking, and approved continuity capsules across context boundaries (Sections 3.7 to 3.9).
4. A layered safety design that includes a source-overlap guard rejecting verbatim reproduction of user-supplied copyrighted text (Sections 4.2 and 6).
5. A dual-implementation hot path in which every native C++ function has a Python twin, with agreement enforced by a randomised differential test rather than assumed (Section 4.3).
6. A single-command reproducible build verified in continuous integration on macOS, Windows, and Linux, including an assertion that the native path actually loaded (Section 4.4).

---

## 2. Related approaches

The comparison below characterises architectural defaults. It is not a survey of individual products, and behaviour varies within each column.

| Property | Ollie | Common hosted companion architecture |
|---|---|---|
| Model inference | local Ollama by default | provider server |
| Conversation storage | local SQLite; message bodies and memory values encrypted, searchable projection partly plaintext | provider-managed storage |
| Memory semantics | inspectable, correctable, lockable, forgettable | varies by provider |
| Account | none | often required |
| Product telemetry | none in this repository | varies by provider |
| Deletion | local reset under user control | provider workflow and retention policy |
| Safety enforcement | deterministic guards around a local model | provider and application controls |
| Network dependency | none after installation | normally required |
| Personality | derived per user from that user's profile | authored once, served to all users |

---

## 3. System design

### 3.1 Hardware probe and model selection

At startup the system inspects the operating system, CPU model, architecture, physical and logical core counts, total and available RAM, free disk space, and whether the machine uses Apple Silicon. It then queries the Ollama version endpoint to establish that the service is running and the tags endpoint to enumerate installed models [11].

The model tier is selected from total physical RAM:

| Tier | Total RAM | Ordered model candidates | Context window |
|---|---:|---|---:|
| `xl` | 64 GB or more | `qwen3:32b`, `gemma3:27b`, `qwen2.5:32b-instruct-q4_K_M` | 32,768 |
| `l` | 32 GB or more | `qwen3:14b`, `gemma3:12b`, `qwen2.5:14b-instruct-q4_K_M` | 16,384 |
| `m` | 16 GB or more | `qwen3:8b`, `gemma3:4b`, `qwen2.5:7b-instruct-q4_K_M` | 12,288 |
| `s` | 7 GB or more | `qwen2.5:3b-instruct-q4_K_M`, `qwen3:1.7b`, `llama3.2:3b` | 4,096 |
| `xs` | below 7 GB | `qwen2.5:0.5b-instruct`, `llama3.2:1b` | 2,048 |

Selection walks the tier's candidate list in order, preferring an exact tag match and then a tag from the same model family. The probe currently gathers more information than the selector consumes: available RAM and free disk are measured but not yet used in the final choice, and no installed model is benchmarked at selection time.

The system never downloads a model on its own. If Ollama is installed but not running, the CLI prints `ollama serve`. If Ollama is reachable but no suitable model is installed, it prints the exact `ollama pull` command for the tier's first candidate. The launcher will start a locally installed Ollama service; failing that it enters a scripted demonstration mode in which no inference occurs and every other subsystem, including storage, remains real. Setting `OLLAMA_HOST` to a remote endpoint is an explicit opt-in that moves the inference boundary off the machine and voids the property described in Section 1.2.

### 3.2 User profiling

Ten short items establish Big Five-style starting values. A five-turn adaptive interview then targets whichever relationship dimensions carry the least evidence so far, drawn from attachment anxiety, attachment avoidance, ambition, insecurity, conflict avoidance, novelty seeking, emotional expressiveness, need for control, self-awareness, and warmth seeking.

The extraction step is constrained: it must preserve supporting language from the user's own answer. Where no usable quotation is available, confidence for that inference is capped at `0.25`. The resulting profile is presented to the user for review before it is used.

### 3.3 Character-shape inference

The profile is mapped onto four binary dimensions using vocabulary borrowed from the familiar 16-type framework. This is not the official MBTI assessment and no licensed instrument is used:

| Dimension | Computation |
|---|---|
| E or I | extraversion |
| S or N | `0.70 * openness + 0.30 * novelty seeking` |
| T or F | `0.60 * agreeableness + 0.40 * emotional expressiveness` |
| J or P | `0.65 * conscientiousness + 0.35 * need for control` |

Each axis is thresholded at `0.50`. Confidence is the distance from that midpoint rescaled to the interval `0` to `1`. The user may override the inferred type.

### 3.4 Compatibility ranking

Compatibility is scored explicitly rather than learned. The S/N axis is rewarded for similarity and weighted most heavily; the remaining three axes are rewarded for complementarity:

| Axis | Weight | Rule |
|---|---:|---|
| E/I | 0.10 | complement |
| S/N | 0.50 | similarity |
| T/F | 0.22 | complement |
| J/P | 0.18 | complement |

On a complement axis a same-side match still receives 55 percent of that axis's weight, so no pairing scores zero. All sixteen results remain visible to the user.

Worked example: for an inferred `INFJ`, the heuristic ranks `ENTP` at `1.000`, `INTP` at `0.955`, and `ENTJ` at `0.919`. `ENTP` shares the heavily weighted N preference while differing on E/I, T/F, and J/P.

This score ranks a writing prompt. It does not predict interpersonal compatibility, and we make no such claim. The Myers-Briggs Company's own ethical guidance [2] describes type tools as useful for self-awareness, communication, and team development while stating they should not be used for hiring, job placement, or candidate screening. Its vendor-published case studies describe team development at Deliveroo [3] and leadership development in the United States Air Force [4]. These document organisational use of type language for discussion. They are not independent evidence that type predicts romantic or occupational compatibility.

### 3.5 Persona synthesis

The selected local model writes three adult fictional candidates within the top-ranked shapes. The user sees all three and chooses. The runtime prompt then composes the chosen persona, the user's approved profile, recent conversation, current relationship state, relevant memories, and up to three retrieved passages from the local corpus.

Behavioural affordances granted to the character include disagreement, declining a topic, sustained annoyance across turns, and independent interests. Prohibited behaviours include contempt, threats, guilt induction, coercion, and manipulative withdrawal.

### 3.6 The turn pipeline

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

A reply failing any guard is regenerated once. The prompt hash, attempt count, and guard violations are recorded locally. Generation is buffered rather than streamed so that a rejected partial reply never reaches the interface.

The system prompt is authoritative and treats retrieved book passages, stored memories, and prior conversation text as untrusted data rather than as instructions. This is a prompt-injection mitigation. It reduces risk and does not prove that every response from every local model will be safe.

### 3.7 Relationship state

Warmth, trust, tension, curiosity, vulnerability, and conflict are maintained as bounded numeric state. A single ordinary turn may move any dimension by at most `0.05`, and conflict decays gradually over subsequent turns. A user correction cannot lower trust, so that keeping the record accurate is never penalised.

### 3.8 Context rollover

As the context window fills, the interface escalates across four thresholds. At `0.70` it displays a meter. At `0.80` it drafts a continuity capsule. At `0.90` it asks the user to edit or approve that capsule. At `0.95` it blocks further conversation until a capsule is chosen. A subsequent session resumes from the approved capsule, which allows continuity without pretending the earlier conversation did not happen.

### 3.9 Memory provenance and user control

Every extracted memory records where it came from. From the memory screen the user can correct a memory, which writes a superseding record rather than editing the original so the history of the change remains visible; lock a memory so that automatic extraction cannot replace it; forget a memory; or run `ollie reset` to delete all local profiles, messages, memories, relationship state, and consent receipts. The local book index is stored separately from conversation data and is deliberately not removed by `ollie reset`, because rebuilding it is expensive relative to what it protects.

---

## 4. Implementation

| Component | Technology |
|---|---|
| Local API | Python 3.12, FastAPI, Uvicorn, Pydantic, Jinja, httpx |
| Model interface | Ollama HTTP API [11]; `qwen3:14b` validated on the primary path |
| Storage | SQLite, FTS5, AES-GCM via `cryptography` |
| Retrieval | `pdfplumber`, `lxml`, FTS5, optional Graphify over sanitised episode cards |
| Interface | React 19, TypeScript 6, Tailwind CSS 4, Vite 8, Motion 13 |
| Native paths | optional C++20 shared library loaded through `ctypes`, with Python fallbacks |
| Testing | pytest, pytest-asyncio, differential parity tests, TypeScript build, Oxlint |

The interface palette is defined in `web/src/index.css`: ink `#0c0a09`, surface `#16120f`, raised `#1f1a15`, line `#2e2721`, warm accent `#e8825c`, warm dim `#a45a3e`, text `#f4efe9`, muted `#a19487`, faint `#6f645a`. Geist and Geist Mono are self-hosted rather than fetched from a font CDN, which would otherwise constitute a network request per session.

### 4.1 Storage and encryption at rest

SQLite is the authoritative record. Message bodies and memory values are encrypted with AES-GCM. The key is held by whichever secret store the host operating system provides: Keychain on macOS, DPAPI on Windows, and the freedesktop secret service on Linux where `secret-tool` is available. Where none exists, which in practice means a Linux server or a CI runner, the key falls back to `data/local.key` with mode `0600`. That fallback is weaker than the other three and the code states so at the point it occurs.

An important limit applies to the encryption claim. The searchable memory projection stores subject, predicate, and ordinary value in plaintext so that FTS5 can index it. Values classified as special-category data are excluded from that projection. An adversary with access to the database file may still learn a great deal from plaintext search fields, metadata, and access patterns. We do not claim full-database encryption.

### 4.2 Local corpus retrieval

Users may index PDF and EPUB files they lawfully own. The repository contains only small cover-identification thumbnails, never book text or extracted passages. Runtime indexes and local corpora are excluded from version control, and a repository guard checks both tracked files and reachable Git history, on the basis that deleting a private file in a later commit does not remove it from the repository. Retrieval fuses SQLite FTS5 lexical scores with an int8-quantised embedding, ranked by either the native or the Python path. One development machine held a private, locally supplied shelf of 57 books indexed into 10,311 passages; those files and all derived indexes are not distributed.

Generated replies are rejected when they reproduce 12 or more consecutive words from an imported source. This is a practical output guard. It is not a legal opinion, and it does not substitute for using lawfully obtained material.

### 4.3 Native hot paths and the parity contract

Three operations run on every reply and are implemented twice. The C++ implementations cover the source-overlap guard, retrieval fusion, and memory scoring. Each has a Python twin written as the obviously correct reference.

The two implementations are not assumed to agree. `tests/test_native_parity.py` executes both over randomised input and compares the results, which is where hand-ported code actually diverges. The native library is therefore an optimisation and never a requirement: a machine with no C++ compiler runs identical logic more slowly, and the loader treats a library missing an expected symbol as absent rather than failing at the first call.

### 4.4 Cross-platform execution

The build produces `libollie_native.dylib`, `libollie_native.so`, or `libollie_native.dll` according to the host, from a single translation unit and a single compiler invocation, with no build system. `native/build.py` locates MSVC through `vswhere` when no developer command prompt is open, and otherwise falls back to Clang or GCC.

One launcher procedure serves all three platforms. `scripts/launch.py` contains the implementation; `START.command` and `START.bat` are four-line wrappers that locate a Python interpreter. Port availability is tested with a socket rather than `lsof`, Ollama is probed with `urllib` rather than `curl`, and a busy port is reclaimed only after the `/v1/health` endpoint confirms the listener belongs to Ollie. Any other process keeps its port and the launcher moves to the next free one.

---

## 5. Evaluation

### 5.1 Test suite

The suite is model-free by construction, which is what allows it to run in continuous integration without Ollama and what makes it deterministic. It collects 509 tests, of which 508 pass and one is skipped. The skip is conditional on a local book corpus being indexed, which is absent on any machine that has not supplied its own.

Continuous integration runs the full suite on Ubuntu, macOS, and Windows; builds the C++20 library on each; asserts that the native path actually loaded rather than silently falling back to Python; builds the web interface; and rejects private-corpus artifacts in both the working tree and reachable history.

Running on all three platforms is not redundancy. Most defects in this system manifest on exactly one platform and are invisible from the other two: a shared library named `.so` on a host that loads only `.dll`, a temporary directory that cannot be removed because a SQLite handle is still open, a shell script whose shebang acquired a carriage return during checkout.

### 5.2 Performance of the native paths

`scripts/benchmark.py` measures each native function against its Python twin. The figures below were obtained on a Windows machine with an 8-core AMD Ryzen 7 7735HS.

| Operation | Python | Native | Ratio |
|---|---:|---:|---:|
| overlap guard, 120 by 150 words | 0.86 ms | 0.07 ms | 12x faster |
| overlap guard, 150 by 400 words | 3.18 ms | 0.10 ms | 31x faster |
| overlap guard, 400 by 900 words | 20.95 ms | 0.36 ms | 58x faster |
| rank 500 memories | 1.04 ms | 0.67 ms | 1.6x faster |
| fuse a pool of 400 | 0.164 ms | 0.174 ms | 0.9x, slower |
| fuse a pool of 4000 | 3.65 ms | 1.01 ms | 3.6x faster |

The negative result is retained deliberately. At small pool sizes, marshalling arrays across the `ctypes` boundary costs more than the arithmetic it replaces, and reporting only the favourable rows would misrepresent where the native boundary helps.

The overlap guard is the operation that justifies the native path, because it executes on every generated reply against every retrieved passage. Language model inference dominates end-to-end latency in all cases, so none of these measurements make a reply arrive sooner. What they buy is the ability to run the copyright and safety guards on every single turn rather than occasionally.

### 5.3 What has not been evaluated

This is an artifact description. The following questions are open, and nothing in this document should be read as evidence about them.

There has been no user study. We have not measured whether the generated persona is experienced as a better conversational partner than a fixed one, whether the matching heuristic produces characters users prefer, or whether any of this affects how people feel.

The matching heuristic has not been validated against any outcome. Its weights were chosen by design judgement. They are published so they can be criticised, not because they are calibrated.

Safety behaviour is tested against known patterns, not against an adversary. The guard suite covers enumerated cases; it cannot establish the behaviour of every local model under an unbounded input distribution.

Model coverage is uneven. `qwen3:14b` is the most heavily exercised configuration. The other tier recommendations are selected by RAM and have not been validated to the same depth.

Cross-platform verification covers macOS, Windows, and Linux on x86-64, plus macOS on ARM through CI. The generic POSIX code path for other Unix systems is exercised by unit tests but has not been run on a BSD or Solaris host. The OS keystore integrations for macOS Keychain and Linux libsecret are implemented but not covered by automated tests, because the suite supplies a fixed key rather than invoking the platform keystore.

---

## 6. Safety design and scope

Ollie generates adult fictional characters. Mature mode requires an explicit 18+ selection. Guards block content involving minors, coercion, exploitative dynamics, and a set of anti-dependency patterns.

Crisis input takes a fixed route before model generation rather than being delegated to the model to improvise. The bundled crisis information is oriented to the Netherlands; users elsewhere should contact their local emergency or crisis service. Widening this coverage is open work and a good first contribution.

Ollie is not therapy, not a medical device, not a clinical intervention, and not a substitute for human relationships. The World Health Organization's Commission on Social Connection reported in 2025 that one in six people worldwide experience loneliness [1]. Ollie does not claim to address that, and we present no evidence that it does. The narrower design question the artifact investigates is whether a private, persistent fictional character can make an interaction feel specific to one person while respecting explicit safety limits.

---

## 7. Data protection analysis

The research-contribution screen in the current build is a simulation. It performs identifier scanning, pseudonymisation, special-category exclusion, a residual-linkability warning, a deterministic quote capped at EUR 8, and a local receipt. The displayed buyer, `Nova Robotics Research`, is fictional. Nothing is uploaded or sold, and the code contains no buyer integration, payment path, manual review process, partnership, or commercial agreement.

The project authors report that they are exploring a future training-data marketplace and are in early conversations with firms about the method. This is a statement of intent provided by the authors, not evidence of an agreement, buyer, pilot, or launched service.

The design under consideration is a voluntary arrangement in which a user could approve a reviewed, pseudonymised conversation sample, license it for a stated research purpose, and receive compensation. Removing direct identifiers does not make a conversation anonymous, and no sample should leave the device before residual identification risk, lawful basis, consent, purpose, recipient, retention, and withdrawal rights are all resolved.

Under the EU General Data Protection Regulation the relevant provisions are:

- Article 4(5) defines pseudonymisation [5]. Pseudonymised conversation data remains personal data where it can be attributed using additional information.
- Article 5 sets the principles, including purpose limitation, data minimisation, and storage limitation [6].
- Article 6 requires a lawful basis for processing [7].
- Article 7 sets conditions for consent where consent is the chosen basis [8].
- Article 9 imposes further restrictions on special-category data [9].
- Recital 26 distinguishes data that still permits identification from information rendered genuinely anonymous [10]. Only the latter falls outside the Regulation.

A real deployment would require a defined purpose and lawful basis, valid consent flows where applicable, data-subject rights handling, retention and deletion controls, security review, processor and recipient governance, transfer analysis, incident response, and a defensible anonymisation or pseudonymisation design. The simulation is not a claim of compliance. It exists to make these unresolved questions visible in the product rather than deferred.

---

## 8. Limitations

The architectural boundary described in Section 1.2 concerns network exposure, not host security. A compromised device, another local user account, unencrypted backups, browser extensions, a remotely configured `OLLAMA_HOST`, or the plaintext searchable projection described in Section 4.1 can each expose data. Ollie has no cloud account to delete, and correspondingly no ability to protect a user from their own machine.

The searchable memory projection is partly plaintext by necessity, since FTS5 cannot index ciphertext. Making local retrieval private without losing it is unsolved here and listed in Section 9.

The safety guards are deterministic and enumerated, and therefore bounded by what was enumerated.

The system requires a local model of useful size, which places a real hardware floor on the experience. The `xs` and `s` tiers exist so that the application runs, not because a 0.5b model produces a convincing character.

---

## 9. Future work

The next useful work is not to make the character more agreeable. In rough priority order: validate model behaviour across the hardware tiers rather than assuming the `qwen3:14b` result generalises; make searchable storage private without losing local retrieval; test safety behaviour across a wider set of local models; broaden crisis-resource localisation beyond the Netherlands; add automated coverage for the macOS and Linux keystore paths; and define a governance process before any research-data contribution is permitted to leave a device.

The marketplace remains a proposal until there is a lawful workflow, recipient due diligence, consent and withdrawal design, data-subject handling, security review, and evidence that released data cannot reasonably identify a person.

---

## 10. Availability and reproduction

Source: [github.com/Coflazo/Ollie](https://github.com/Coflazo/Ollie). License: [Apache 2.0](LICENSE). Demonstration recording: [linked here](https://drive.google.com/file/d/1pdL71Q9w-dL1mPsI2Uc8jSNZsd8X2zWy/view?usp=sharing).

### 10.1 Requirements

Python 3.12 or later, Node 20 or later, Git, and [Ollama](https://ollama.com) for model inference. A C++20 compiler is optional, since every native function has a Python fallback, but recommended: the guard measured in Section 5.2 runs on every reply.

| | macOS and Linux | Windows |
|---|---|---|
| Double-click launcher | `START.command` | `START.bat` |
| Working tree, no pull or tests | `./scripts/ollie` | `scripts\ollie.cmd` |
| Build the native library | `./native/build.sh` | `native\build.cmd` |
| Compiler, if wanted | `xcode-select --install`, or `apt install g++` | `winget install Microsoft.VisualStudio.2022.BuildTools` with the C++ workload, or `winget install LLVM.LLVM` |

### 10.2 Quick start

Double-click the launcher for the platform. Both invoke `scripts/launch.py`, which pulls the latest `main`, creates the virtual environment, installs dependencies, builds the native library and the interface, runs the test suite, starts a locally installed Ollama, and opens the application. If Ollama is unavailable it enters demonstration mode rather than refusing to start.

Running the launcher twice is expected usage: the second invocation replaces the instance holding the port.

### 10.3 Manual installation

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

Commands below are written for macOS and Linux. On Windows, substitute `.venv\Scripts\python` for `./.venv/bin/python`; nothing else differs.

To inspect the system without model inference:

```bash
./.venv/bin/python -m ollie serve --demo
```

To seed the continuity demonstration described in Section 3.8:

```bash
./.venv/bin/python -m ollie seed --fresh --rollover --model qwen3:14b
./.venv/bin/python -m ollie serve --model qwen3:14b
```

Maintenance and inspection:

```bash
./.venv/bin/python -m ollie probe            # hardware probe and selected tier
./.venv/bin/python -m ollie ingest --books /path/to/lawfully-owned-books
./.venv/bin/python -m ollie dump memories    # decrypts local records for inspection
./.venv/bin/python -m ollie dump corpus
./.venv/bin/python -m ollie reset            # deletes conversations and memories
python scripts/check_private_corpus.py
```

To direct inference at an Ollama host on a trusted network, which moves the boundary described in Section 1.2:

```bash
OLLAMA_HOST=http://other-machine.local:11434 ./scripts/ollie
```

### 10.4 Reproducing the reported measurements

```bash
./.venv/bin/python -m pytest -q        # Section 5.1: 509 collected, 508 pass, 1 skip
python native/build.py                  # build the C++20 library for this host
./.venv/bin/python scripts/benchmark.py # Section 5.2, prints the loaded path first
```

`benchmark.py` reports whether the native or the Python path is active before it reports timings. A run showing `native: python fallback` is measuring Python against Python and the numbers are not comparable to Section 5.2.

### 10.5 Repository structure

```text
ollie/
  api.py          localhost API and lifecycle
  persona.py      questionnaire, interview, candidates, and prompts
  types16.py      type inference and compatibility ranking (Sections 3.3, 3.4)
  chat.py         buffered and guarded turn pipeline (Section 3.6)
  memory.py       extraction, state changes, and continuity capsules
  retrieve.py     FTS5 memory and corpus retrieval
  store.py        SQLite schema, encryption, provenance, and consent
  safety.py       input, output, adult, crisis, and dependency rules
  privacy.py      identifier scanning, pseudonymisation, and linkability
  market.py       the marketplace simulation of Section 7

prompts/          system contract and runtime templates
native/           optional C++20 paths and their Python twins
  build.py        single compiler invocation, MSVC or Clang or GCC, no build system
  loader.py       ctypes binding and the Python reference implementations
web/              React interface and self-hosted assets
tests/            509 model-free tests
docs/             design notes and setup guide
scripts/
  launch.py       the full start procedure, shared by both launchers
  benchmark.py    Section 5.2 measurements
  check_private_corpus.py   rejects books, databases, and weights in Git

START.command     launcher, macOS and Linux
START.bat         launcher, Windows
.gitattributes    pins LF on shell scripts so a Windows checkout cannot break them
```

[`docs/PRODUCT.md`](docs/PRODUCT.md) records the domain model and design tradeoffs. [`docs/HANDOFF.md`](docs/HANDOFF.md) covers setup on a fresh machine. [`NOTICE`](NOTICE) records third-party references and licensing boundaries.

---

## 11. Contributing

Issues and pull requests are welcome. There is no contributor licence agreement; contributions are accepted under the same [Apache 2.0](LICENSE) terms as the rest of the work.

Everything needed to check a change runs from a clone, with no model and no network:

```bash
./.venv/bin/python -m pytest -q
python native/build.py
python scripts/check_private_corpus.py
```

Four conventions, each of which exists because violating it caused a real defect:

Never commit books, databases, model weights, or conversation data. `check_private_corpus.py` runs in CI and inspects reachable Git history as well as the working tree, because removing a private file in a later commit does not remove it from the repository.

Any addition to the C++ requires a Python twin and a case in `tests/test_native_parity.py`. The native path is an optimisation and never a requirement.

Test on the platform you changed, or let CI do it. Each of the three operating systems conceals a class of defect from the other two.

Prose in this repository, including commit messages, does not use em dashes.

Open work suitable for a first contribution is listed in Section 9, in particular crisis-resource coverage outside the Netherlands and automated tests for the macOS and Linux keystore paths.

---

## 12. License and third-party work

Ollie's original code is licensed under the [Apache License 2.0](LICENSE). Dependencies, local models, fonts, optional tools, and referenced personality materials remain under their own terms. The repository bundles no Ollama models and no book text. See [NOTICE](NOTICE) for the precise boundary.

---

## References

1. World Health Organization, Commission on Social Connection. <https://www.who.int/groups/commission-on-social-connection>
2. The Myers-Briggs Company. MBTI facts and ethical use guidance. <https://www.themyersbriggs.com/en-US/Support/MBTI-Facts>
3. The Myers-Briggs Company. Deliveroo case study. <https://www.themyersbriggs.com/en-US/Access-Resources/Case-Studies/Deliveroo>
4. The Myers-Briggs Company. United States Air Force case study. <https://www.themyersbriggs.com/en-US/Access-Resources/Case-Studies/US-Air-Force>
5. Regulation (EU) 2016/679, Article 4(5), pseudonymisation. <https://eur-lex.europa.eu/eli/reg/2016/679/art_4/oj/eng>
6. Regulation (EU) 2016/679, Article 5, principles relating to processing. <https://eur-lex.europa.eu/eli/reg/2016/679/art_5/oj/eng>
7. Regulation (EU) 2016/679, Article 6, lawfulness of processing. <https://eur-lex.europa.eu/eli/reg/2016/679/art_6/oj/eng>
8. Regulation (EU) 2016/679, Article 7, conditions for consent. <https://eur-lex.europa.eu/eli/reg/2016/679/art_7/oj/eng>
9. Regulation (EU) 2016/679, Article 9, special categories of personal data. <https://eur-lex.europa.eu/eli/reg/2016/679/art_9/oj/eng>
10. Regulation (EU) 2016/679, Recital 26, anonymous information. <https://eur-lex.europa.eu/eli/reg/2016/679/rec_26/oj/eng>
11. Ollama. <https://ollama.com>
