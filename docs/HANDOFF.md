# Handoff: finishing Ollie on the 48 GB Mac

Everything in this document is written for the machine that will run the live demo. It was
built and tested on an 8 GB Intel MacBook Pro, where a single model turn takes about five
minutes, so the full flow has been verified against a scripted test double but **never
watched end to end against a real model**. That is the single most important thing you are
about to do.

Read section 6 first if you are short of time. Sections 1 to 5 get you running; section 6
is where the actual unknowns are.

---

## 0. What you need before you start

| Requirement | Check | If missing |
|---|---|---|
| Python 3.12 or newer | `python3 --version` | `brew install python@3.12` |
| Node 20 or newer | `node --version` | `brew install node` |
| Ollama | `ollama --version` | Download from [ollama.com](https://ollama.com) |
| Xcode command line tools | `clang++ --version` | `xcode-select --install` |
| Git | `git --version` | Comes with the tools above |

Ollama must be **0.5 or newer**. Below that, the structured-output path (`format` accepting
a JSON schema) does not exist, and the interview scoring, candidate generation and continuity
capsule all silently return nothing. If `ollama --version` shows anything older, upgrade
before going further. This is the single most consequential version check in the project.

**A note on qwen3 specifically.** It is a reasoning model, so it produces its working before
its answer. Ollie sends `think: false` on every call and strips any `<think>` block that
arrives inline anyway, because reasoning left in the content reaches the user as the
character monologuing about how to be in character, and it breaks JSON parsing on every
structured call. Both paths are covered by `tests/test_ollama.py`. If you ever see a reply
that starts by planning what to say, that filter has a gap worth reporting.

**The books are not in the repository and never will be.** They are in-copyright commercial
titles. Get the `Books/` folder from Coflazo directly over AirDrop or a USB drive. Ollie runs
perfectly well without it, just with less texture in what the character understands: without
a corpus, `search_corpus` returns an empty list, the prompt omits the background-reading
section, and everything else behaves identically. Do not block on this.

---

## 1. Clone and install

```bash
git clone https://github.com/Coflazo/Ollie.git
cd Ollie

python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -e ".[dev]"
```

Verify:

```bash
./.venv/bin/python -c "import fastapi, pydantic, pdfplumber, lxml, numpy, cryptography; print('deps ok')"
```

Expect exactly `deps ok`. Every one of these has a prebuilt wheel for Apple Silicon, so
nothing should compile. If pip starts building `pydantic-core` from source you are on a
Python version without a matching wheel; check `python3 --version` again.

---

## 2. Build the native library

```bash
./native/build.sh
```

Expect: `built native/libollie_native.dylib`

Then confirm the C++ path is actually live rather than silently falling back:

```bash
./.venv/bin/python -m pytest tests/test_native_parity.py -q -s | grep "native status"
```

Expect `native status: native`. If it says `python fallback`, the library did not load.
That is not fatal, the product runs identically, but the pitch claims a native path so it
is worth two minutes:

- `clang++ --version` fails → run `xcode-select --install`
- Library built but will not load → `file native/libollie_native.dylib` should say
  `arm64`. If it says `x86_64` you have an Intel Python under Rosetta; use a native one.

---

## 3. Pull a model

The hardware probe puts a 48 GB machine in **tier `l`**: 16,384 token context, two-pass
style available, and this preference order:

```
qwen3:14b  →  gemma3:12b  →  qwen2.5:14b-instruct-q4_K_M
```

```bash
ollama pull qwen3:14b
```

If that tag does not exist in the registry today, work down the list. If none of them
resolve, pull anything in the 12B to 20B range and pass it explicitly with `--model` later.
Nothing in the code depends on a specific tag; `select_model` matches against whatever
`GET /api/tags` reports and falls back to a same-family match before giving up.

Verify the machine sees it:

```bash
./.venv/bin/python -m ollie probe
```

Expect `"tier": "l"` and `"context_cap": 16384`. If it says tier `m` or `s`, the RAM probe
read low, which usually means something large is already resident; that is fine, but note
it, because it changes the context budget.

Then:

```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep '"name"'
```

Your pulled tag should appear. If Ollama is not running, `ollama serve` in another
terminal, or just let `./scripts/ollie` start it for you.

---

## 4. Index the books (optional but worth it)

With `Books/` in the repository root:

```bash
./.venv/bin/python -m ollie ingest --books Books --tier all
```

On Apple Silicon this takes roughly 10 to 20 minutes, dominated by PDF text extraction.
EPUBs are fast. Run it in a second terminal while you do section 5.

Expect a line per book and a final summary. On the build machine the result was:

```
done: 10311 new chunks. corpus={'sources': 57, 'chunks': 10311, 'embedded': 0}
```

`embedded: 0` is correct and intentional. Embeddings are opt-in behind `--embed` because
they measured at 67 seconds per batch of eight on the build machine. On your hardware they
would be far quicker, but FTS5 alone already retrieves the right passages, and turning them
on now would be an untested change hours before a deadline. Leave it.

If a book fails, the run continues and prints `FAIL <name>`. A few failures are fine.
Scanned PDFs with no text layer are skipped by design.

---

## 5. Build the interface and start

```bash
cd web && npm install && npm run build && cd ..
./scripts/ollie
```

`scripts/ollie` starts Ollama if it is not already up, builds the native library if it is
missing, builds the web bundle if `web/dist` does not exist, then starts the server and
opens a browser at `http://127.0.0.1:8765`.

Expected console output:

```
  Ollie
  Apple M... · N cores · 48.0 GB RAM (xx GB free) → tier l, 16384 token context
  ollama 0.x.x
  model  qwen3:14b
  corpus 57 sources, 10311 passages
  ready  http://127.0.0.1:8765
```

Then confirm the capability flags:

```bash
curl -s http://127.0.0.1:8765/v1/health | python3 -m json.tool
```

You want `"native": true` and `"graphify": true` if you installed it. `graphify: false` is
harmless; `ollie/graph.py` writes an identical `graph.json` itself when the CLI is absent,
and there is a test asserting the downstream code cannot tell the difference.

To point at a different machine's Ollama instead of the local one:

```bash
OLLAMA_HOST=http://other-machine.local:11434 ./scripts/ollie
```

---

## 6. Walk the whole flow. This is the part that matters.

Nobody has watched these five screens work against a real model. Go through them slowly and
write down anything that looks wrong. Expected timings below are for a 14B model on Apple
Silicon; if something takes three times longer than stated, it is probably stuck rather than
slow.

### 6.1 Opening screen

Should show your real CPU, RAM, free RAM, disk and the chosen model. The `start` button is
disabled until a model resolves.

- **If `start` stays disabled:** no model matched. Check `/v1/setup/probe` for
  `suggested_pull` and pull that tag.

### 6.2 Questionnaire, ten items

Answer all ten. Enter a display name. Optionally pick your four-letter type from the
dropdown; leaving it blank makes Ollie infer it, which is the more interesting demo.

Toggle mature mode on and confirm 18+ if you intend to demo it. The button stays disabled
until the confirmation is ticked, deliberately.

Click `next`. **First model call happens here.** Expect 3 to 8 seconds.

- **If it hangs past 60 seconds:** the model is loading into memory for the first time.
  That is normal on the first call only. Subsequent calls are much faster because
  `OLLAMA_KEEP_ALIVE` holds it resident.
- **503 "no model available":** the server started before Ollama was ready. Restart
  `./scripts/ollie`.

### 6.3 The interview, five turns

Ollie asks one question at a time. Each should be specific and slightly awkward to answer
honestly, aimed at whatever trait it has least evidence for. It should react to your answer
before asking the next thing.

Answer properly. Give it real material: mention a specific person, a specific worry, a real
plan with a date. Those details are what the memory system will later prove it kept.

**Deliberately dodge one question.** Answer around it without answering it. The extractor
scores dodges separately, and the candidate screen will show it back to you. It is the most
convincing thirty seconds of the whole demo.

Expect 3 to 8 seconds per question.

- **If a question reads generic** ("what do you value in a partner"), the model is
  underperforming the prompt. Note it. A larger model fixes it; there is nothing to change
  in the code.

### 6.4 The read, the type, and three candidates

After the fifth answer, two calls run back to back: trait extraction, then candidate
generation. **This is the slowest step in the product.** Expect 30 to 90 seconds total. The
candidate schema is large and the model is filling roughly forty fields.

Check all of this:

- The trait summary quotes your actual words back as evidence. If a dimension has no quote,
  its confidence was capped in code, which is correct behaviour.
- Your inferred type appears with per-axis confidence.
- "how all sixteen ranked" expands into a bar chart. **Every one of the top three must share
  your sensing/intuition letter.** That is the Gifts Differing weighting doing its job and
  there is a test pinning it.
- Three character cards, each with a type, a specific obsession, a way of arguing, and a
  named friction point.

> **Critical diagnostic.** If the three characters are called **Mira, Ilya and Noor**, model
> generation failed and you are looking at the hardcoded fallback cards in
> `persona._fallback_card`. The demo still works, but the cards are not personalised. Causes,
> in order of likelihood: Ollama older than 0.5 so `format` was ignored; the model is too
> small to satisfy the schema; the request timed out. Try a larger model first.

### 6.5 The conversation

Pick a candidate. Send a first message.

Expect 5 to 15 seconds per reply, longer when a reply gets rejected and regenerated.

Things to verify, in rough order of importance:

1. **It pushes back.** Say something plainly wrong or lazy: *"long distance always works if
   you just try hard enough."* It should disagree. If it agrees warmly, the core thesis of
   the product is not landing and you should say so immediately.
2. **It does not sound like an assistant.** No "I'm here for you", no "that's a great
   question", no message ending in a question four times running. If any of those appear,
   `style.py` failed to catch them and that is a bug worth reporting with the exact string.
3. **Hold the disagreement.** Push back on its pushback without adding a new argument. It
   should not immediately cave.
4. **Open "why this reply".** It should show which memories and which books fed the answer,
   how long generation took, and whether the reply was rewritten.
5. **The memory panel fills.** Records appear on the right within a couple of seconds of
   each reply, because extraction runs as a background task. Each should be something you
   actually said.
6. **Tell it something specific and factual** early on, such as an appointment on a named
   day. You will check for it after the rollover.

### 6.6 The rollover, which is the scored criterion

Talk until the context meter reaches roughly 90 percent, or force it by pasting long
messages. At 90 percent a bar appears offering to carry the conversation over.

Click `review`. Expect 15 to 40 seconds while the capsule is written.

The dialog should show what happened, anything unresolved, open threads, the moments it
considers worth keeping, and the verbal tics that will persist. Read it out loud during the
demo; it is the most legible artifact in the product.

Click `start the next one`. Then, in the new episode, ask about the specific thing you
mentioned in 6.5 **without naming it directly**. "So what were we going to do about that
thing on Thursday?"

**If it recalls the detail in character, the feasibility criterion is demonstrated.** That
is the moment to have on video.

### 6.7 Offline

Turn Wi-Fi off entirely and send another message. Everything should behave identically. This
is a claim the README makes, so it is a claim worth testing in front of judges.

---

## 7. Known gaps, in priority order

Things I know are incomplete. Fix in this order if there is time.

1. **The style filter has never faced a 14B model.** It was tuned against a 3B, and a
   round of patterns aimed at larger models has since been added blind: markdown
   formatting, performed curiosity, unrequested advice, pre-emptive validation, reflective
   listening, essay connectives, aphorism closes and emoji. Those are educated guesses. If
   you see an assistant-ism that gets through, add it to `RULES` in `ollie/style.py` with a
   severity and add the string to `LARGE_MODEL_ISMS` in `tests/test_style.py`. Two lines,
   and the test proves it works. Equally important: if the filter rejects something that
   was actually in character, add it to `BLUNT_BUT_FINE` in the same file, because a false
   positive sands the character down into the voice the filter exists to prevent.

2. **Graph memory only rebuilds at rollover.** `write_episode_card` and `graph.build` run
   when a capsule is approved, which is the correct consolidation point but means
   graph-expanded retrieval does nothing in a single-episode demo.

3. **Embeddings are off.** FTS5 alone retrieves well and turning them on is untested at
   scale. Do not change this today.

4. **PII scanning is Python, deliberately.** It measured 25ms to scan a 400-turn
   transcript, once per export click. Hand-porting twelve regexes into C++ for that, in a
   scanner where a subtle parity miss leaks an identifier, is a bad trade. It is written
   down here so nobody re-derives it.

5. **CI is not on GitHub.** `.github/workflows/ci.yml` exists locally but Coflazo's token
   lacks `workflow` scope. Either push it with a token that has that scope, or paste the
   file through the GitHub web interface. It runs the suite, builds the C++ on both Linux
   and macOS so parity is tested rather than assumed, and fails the build if a book,
   database or model weight is ever committed.

---

## 8. If something is broken, in order

```bash
# Is the server even up
curl -s http://127.0.0.1:8765/v1/health | python3 -m json.tool

# Is Ollama up and what does it have
curl -s http://localhost:11434/api/version
curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep '"name"'

# Does the logic still pass without any model at all
./.venv/bin/python -m pytest -q

# What does it actually remember (decrypts for you)
./.venv/bin/python -m ollie dump memories

# What is indexed
./.venv/bin/python -m ollie dump corpus

# Start over without losing the book index
./.venv/bin/python -m ollie reset
```

`pytest` passing while the app misbehaves means the problem is in the model or the wiring,
not the logic. That narrows it fast.

Server logs go to the terminal running `./scripts/ollie`. Ollama's own log shows generation
timings and is usually the fastest way to tell "slow" from "hung".

---

## 8b. Rehearsing without sitting through onboarding

Reaching the interesting part of the demo through the real flow costs five interview calls
plus one slow candidate generation every single time. There is a command that writes the
state directly instead:

```bash
./.venv/bin/python -m ollie seed --fresh --rollover --model qwen3:14b
```

That creates a profile (INFJ), a matched character (Ilya, an ENTP, which is what the
weighting returns for an INFJ), a real eight-message transcript, the six memories that
conversation would have produced, one open thread, and a continuity capsule. `--rollover`
closes episode one, so the recall beat has to come from memory rather than from the visible
transcript.

Restart the server afterwards. The boot screen will offer **back to Ilya** instead of
**start**, and drop you straight into episode two. Then ask:

> what were we going to do about thursday

The interview is on Thursday at ten, their sister Deniz is driving them, and none of that is
in episode two's visible transcript. If it answers correctly and in character, the whole
feasibility argument is demonstrated in one exchange.

There is also a scripted-model mode, which is what makes the product walkable on hardware
that cannot run inference in under five minutes:

```bash
./.venv/bin/python -m ollie serve --demo
```

Everything except inference stays real: the real prompts get assembled, the real memory
extraction runs, the real style filter rejects and regenerates, retrieval hits the real
book index. One reply is deliberately written to sound like an assistant so the filter
visibly catches it and the message shows "rewritten 1x". Useful for filming the video
without waiting on generation, and for checking a UI change without burning a model call.

Drop `--rollover` to land mid-conversation in episode one instead, which is the better
starting point if you want to demo pushback or force a live rollover.

`--fresh` wipes existing profiles first. It never touches the book index.

Note that resume is a real feature, not a test hook: the server adopts the most recent
unfinished session on startup, so closing the browser or restarting never loses a
conversation.

---

## 9. Rehearsal, roughly three minutes

Seed the state first with the command above, so you never do the slow candidate generation
live.

1. **Open on the boot screen.** "This is running entirely on this laptop. That is the model
   it picked for this hardware, and there is no network call after setup." (15s)
2. **Show one interview question and your answer.** "It is not filling in a form. It aims
   each question at whatever it knows least about, and it notices what you avoid." (25s)
3. **The read and the sixteen types.** "This is what it concluded, quoting my own words back
   as evidence. It ranked all sixteen types, weighted from Gifts Differing: shared perception
   matters most, differences in judging are complementary." (35s)
4. **The conversation. Disagree with it.** Let it push back. "Most companion products agree
   with you. This one does not, and the rejection of assistant phrasing is enforced in code,
   not requested in a prompt." (45s)
5. **Open "why this reply".** Show the memories and books that fed it. (20s)
6. **Force the rollover, read the capsule, start episode two, ask about the earlier
   detail.** It remembers. (40s)
7. **Close on the repository.** 418 tests, no network needed, C++ with a Python twin and a
   randomised parity test, and a CI job that refuses to let a book into the repo. (20s)

For the one-minute video, cut steps 4 and 6 only. Pushback and recall are the two things
that distinguish this from every other submission.

---

## 10. What not to change today

- Do not turn embeddings on. FTS5 works, the switch is untested at scale, and there is no
  time to find out it was a mistake.
- Do not raise `MAX_REGENERATIONS` above 1. It doubles worst-case latency for a marginal
  quality gain.
- Do not touch the weights in `types16.py`. Four tests pin them to the reading of the book,
  and the reasoning shown in the interface would stop matching the behaviour.
- Do not remove the buffered generation in favour of streaming. Buffering is why an unsafe
  or source-copying reply never reaches the screen.
- Do not commit `Books/`, `data/`, or any `.db` file. The CI job blocks it, but the CI job
  is not on GitHub yet.
