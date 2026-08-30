# Ollie

A dating simulator that runs entirely on your own machine.

Ollie interviews you, works out what you are actually like, picks which of the sixteen
personality types would suit you, and then becomes a specific person of that type. It
remembers what you tell it across conversations. Nothing you say leaves your computer.

Built for the Personify challenge, Amsterdam, 30 August 2026.

## What makes it different

Most companion apps produce a warm, agreeable assistant wearing a name. Ollie is built
around the opposite idea.

**It pushes back.** The character has opinions and keeps them when you disagree. It gets
bored, says so, and changes the subject. It can be disappointed in you and stay
disappointed for more than one message. It says no. A partner who agrees with everything
is furniture, and the good moments only mean something if the character could have
reacted differently.

**It is neurodivergent, specifically.** Not as a label it announces — as how it processes
everything. It parses you literally first and catches the subtext a beat later, in the
same message. Details snag, so it notices when today contradicts three weeks ago. It
info-dumps about one oddly specific interest and then catches itself. When it cannot read
your tone it says so instead of guessing, which is both more honest and safer than a
sentiment classifier.

**Sounding human is enforced, not hoped for.** `ollie/style.py` rejects the machine
phrases — "I'm here for you", "that's a great question", the rule of three, ending every
message with a question — and asks for a rewrite naming what was wrong. It is a list of
patterns with a test file attached, which is why "does not sound like a chatbot" is a
claim this repository can actually support.

**Memory is personality.** The character does not announce that it remembered something.
It just uses it, the way people do.

## How it works

```
you ──► input guard ──► retrieval ──► compiled prompt ──► local model
                                                              │
        you ◄── style filter ◄── safety guard ◄── copyright guard
                      │
                      └──► background: memory extraction, interaction state
```

- **Model**: any Ollama model. Ollie probes your hardware, picks a tier, and uses the best
  model you have installed. It never downloads anything without asking.
- **Memory**: SQLite is the authoritative store. Message bodies and memory values are
  encrypted with AES-GCM, keyed from the macOS Keychain.
- **Retrieval**: SQLite FTS5 over a locally imported corpus, fused with signals BM25
  cannot express.
- **Native**: `native/ollie_native.cpp` handles the copyright overlap check and retrieval
  fusion. Every function has a pure-Python twin and a parity test; if the library does not
  build, Ollie runs identically and slightly slower.

### The sixteen types

After the interview, Ollie estimates your four-letter type (or takes it directly if you
already know it), then ranks all sixteen as partners for you. The weights come from
*Gifts Differing*: Myers treats shared perception, sensing versus intuition, as the
preference that most determines whether two people can understand each other, while
differences in judging and lifestyle are workable and often complementary. So S/N is
weighted heavily for similarity and the rest get a mild complementarity bonus.

It is a heuristic drawn from a book, shown to you with its reasoning, and you pick from
the top three. It is not a claim about your real romantic life.

## What it is not

Not a therapist, not a substitute for people, not a scientific compatibility test, and
not a real person. The character never claims consciousness, never says only it
understands you, never discourages you from seeing anyone, and never guilts you for
closing the app. Those are enforced in `ollie/safety.py`, above any persona, and tested.

If you describe abuse, danger, or self-harm, Ollie drops the fiction, says plainly that it
cannot help, and points you at someone who can.

## Setup

Needs Python 3.12+, [Ollama](https://ollama.com), and Node 20+ for the interface.

```bash
git clone https://github.com/Coflazo/Ollie.git && cd Ollie
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install -e .

ollama pull qwen2.5:3b-instruct-q4_K_M   # or anything larger you can run
ollama pull nomic-embed-text

./native/build.sh          # optional; pure-Python fallbacks cover it
cd web && npm install && npm run build && cd ..

./scripts/ollie           # starts everything, opens the browser
```

To run the model on a different machine on your network:

```bash
OLLAMA_HOST=http://other-machine.local:11434 ./scripts/ollie
```

### Your own books

Ollie ships **no book content**. The corpus is whatever you import from your own legally
obtained files:

```bash
./.venv/bin/python -m ollie.ingest --books /path/to/your/books
```

PDFs and EPUBs are extracted, chunked and indexed locally. Nothing is uploaded, nothing is
redistributed, and `ollie_longest_overlap` blocks any reply that reproduces more than
twelve consecutive words from a source.

## Tests

```bash
./.venv/bin/python -m pytest
```

The suite covers the anti-assistant filter in both directions (catching machine phrases,
and *not* flagging blunt in-character text), the safety guards, native-versus-Python
parity on randomised inputs, and the memory round-trip: establish a fact in episode one,
roll the context over, and assert it survives into episode two.

## Privacy

Everything is local. There is no account, no telemetry, no analytics, and no network call
after setup — run it with Wi-Fi off and it behaves identically.

The research-contribution screen is a **simulation**. The buyer is fictional, no request
is made, no payment is processed, and every artifact it writes says so on its face. It
exists to make an argument about who should own this data, not to move any.

One thing it deliberately does not claim: removing names produces *pseudonymised* text,
not anonymous text. A romantic conversation carries special-category data under GDPR
Article 9, and a rare combination of job, city and age can identify someone with every
name already stripped. The interface says this too.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
