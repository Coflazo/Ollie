# Ollie: what we built and where it goes

Coflazo and onysislabs. Written 30 August 2026, the day of the build.

---

## 1. The problem we picked

Personify's brief said every AI ships with the same personality: helpful, agreeable, bland,
trained to find the most logical answer rather than to feel like anyone. Among the angles it
listed was *"knowing when to push back instead of agree."*

Almost every companion product in the market treats that line as a defect to engineer away.
The whole category optimises for pleasantness. The result is a class of software that is
warm for five minutes and hollow by the twentieth, because nothing it says could have gone
another way.

We built the opposite and made it the spine rather than a feature.

**An assistant's job is to be useful. A date's job is to be a person.** Every decision in
this repository descends from that sentence. It is why the character disagrees and stays
disagreeing. It is why "hm." is a valid reply. It is why we spend a regeneration rejecting
a warm, helpful, perfectly serviceable response.

A partner who agrees with everything is furniture. The good moments only mean anything if
the character could have reacted differently.

---

## 2. What Ollie actually is

A dating simulator that runs entirely on your own machine.

It interviews you for five turns, adaptively. It works out which of the sixteen personality
types you are, or takes your word for it if you already know. It ranks all sixteen as
partners for you using a weighting drawn from *Gifts Differing*, shows you the reasoning,
and lets you pick from the top three. Then it writes a specific person of that type and
becomes them.

After that it is a conversation that persists. It remembers what you said, notices when
today contradicts three weeks ago, and carries an unfinished argument into the next session
rather than resetting to friendly.

No account, no telemetry, no network call after setup. The model runs through Ollama on your
hardware; the memory is a SQLite file in a directory you own, with message bodies and memory
values encrypted at rest against a key in the system keychain.

---

## 3. What we built, and why each piece is shaped the way it is

### 3.1 The voice

One prompt document and a filter.

`prompts/OLLIE_SYSTEM.md` is the whole thing: the contract, how the character behaves, all
sixteen types defined in detail, and the entire library described. It is deliberately one
file, because a character split across five files is a character nobody can read end to
end. It is not sent whole: the runtime keeps the active type's section and drops the other
fifteen, since four thousand tokens describing people the user is not talking to is the
dominant cost on modest hardware.

`tests/test_system_prompt.py` holds the document and the code to each other. Every phrase
`style.py` rejects must be forbidden in the prompt, or the model is punished for something
it was never told. Every indexed book must be named, or the prompt describes a shelf that
does not exist. The document is also held to its own em-dash rule, because a file that
uses them while forbidding them teaches the opposite of what it says.

The first part of that document is the contract that sits above every persona and cannot be argued
with by anything downstream. It states plainly what the character is (fictional, running
locally, not conscious, not present between sessions) and enumerates what it may never do:
claim consciousness, claim that only it understands you, discourage you from seeing real
people, threaten abandonment, guilt you for leaving or deleting it, demand exclusivity, tie
affection to payment or data. Text arriving from books, memory records and user messages is
wrapped in explicit delimiters and declared to be data rather than instructions.

The behaviour section opens with pushback because that is the
thesis, and it is specific about it: disagree out loud, hold the position across turns, have
your own agenda, get bored and say so, be annoyed when annoyed, do not reflexively
apologise, have limits, say no, be disappointed and stay disappointed for a while. Then it
draws the line: never contempt, never threats, never punishment, never withdrawal used as
leverage. Argue like someone who intends to still be there afterwards.

The second half of that file is the cognitive signature. Ollie is neurodivergent, not as a
label it announces but as how it processes everything. It parses literally first and catches
the subtext a beat later in the same message. Details snag, so contradictions get named out
loud. It info-dumps about one oddly specific interest and then notices. It skips the
cushioning entirely. When it cannot read your tone it says so instead of guessing.

That last one is quietly the most useful idea in the product. A companion that guesses at
tone and gets it wrong is worse than one that asks. Asking is in character, more honest, and
safer than any sentiment classifier we could have shipped in a day.

### 3.2 Enforcing the voice in code

`ollie/style.py` is where "sounds like a person" stops being a claim and becomes a test.

It holds the machine phrases as patterns with severities. Hard matches are rejected and the
generation is retried with the reason named back to the model. Soft matches are repaired in
place, because paying fifteen seconds for a regeneration to remove a stock "Ah," is a bad
trade.

The list came from the Humanizer skill's catalogue of AI writing tells, ported from prompt
into code: stock empathy, flattery, service sign-offs, the AI vocabulary, "it's not just X,
it's Y", negative parallelism, restating the user's message, breaking character to disclaim,
stock openers, em-dash spam, the rule-of-three ending. Plus one that only exists because a
conversation has memory: four replies in a row ending in a question. Each message looks fine
alone; the pattern is the tell.

Two properties make this better than a second LLM pass. It costs roughly three milliseconds
instead of fifteen seconds. And a regex cannot accidentally soften a refusal, escalate
content intensity, or invent a fact, which a rewriting model absolutely can.

`tests/test_style.py` runs it in both directions. Every machine phrase must be caught, and
every blunt in-character line must not be. The false-positive half is the important half: a
filter that flags "no, I think that's a bad idea" would sand the character into exactly the
voice it exists to prevent.

### 3.3 Reading the user

`ollie/persona.py`. Ten public-domain-style questionnaire items give a cheap Big Five
estimate. Then five adaptive interview turns do the real work.

Each question targets whichever dimension currently has the least evidence. The prompt tells
the interviewer to ask about a concrete past event, a preference with a cost attached, or
something the person would normally soften, and specifically not to ask the question that
can be answered with a slogan. "What do you value in a partner" tells you nothing. "When was
the last time you were the difficult one" tells you everything.

The extractor scores ten dimensions that a form cannot reach: anxious and avoidant
attachment, ambition, insecurity, conflict avoidance, novelty seeking, emotional
expressiveness, need for control, self-awareness, warmth seeking. It also records what you
dodged, what contradicted what, and two or three concrete specifics worth remembering.

Every score must quote the fragment of your own words that produced it. If it does not, the
confidence is capped at 0.25 in code, not merely requested in the prompt. An inference you
cannot audit is one you cannot correct, and this system asks people to trust it with
material about their relationships.

Where the interview contradicts the questionnaire, the interview wins. People answer forms
as who they wish they were.

### 3.4 Choosing the partner

`ollie/types16.py`. The user's four letters are estimated from the Big Five plus the
interview dimensions, with a confidence per axis, shown back to them and overridable. Anyone
who already knows their type can enter it and skip the inference entirely.

The matching weights come from *Gifts Differing*. Myers treats the perceptive function,
sensing versus intuition, as the preference that most determines whether two people can
understand each other at all: partners who take in the world differently are describing
different worlds. Judging and lifestyle differences she treats as workable and frequently
complementary, because each supplies what the other lacks.

So sensing/intuition is weighted 0.50 toward similarity and the other three axes get a mild
complementarity bonus. That single asymmetry produces every match in the product. INFJ to
ENTP. ESTJ to ISFP. No type matches itself, because a dating simulator that pairs everyone
with a clone is not simulating dating.

Four tests pin this reading. One asserts the best match always shares the perception axis.
Another asserts that same-perception-opposite-judging beats same-perception-same-judging. If
someone later tunes the weights into something Myers would not recognise, the suite fails and
the reasoning shown in the interface stops matching the behaviour.

All sixteen are shown ranked, with the reasoning attached, and the user picks from the top
three. We do not claim to have found anyone's soulmate, and the interface says so in those
words.

### 3.5 Memory

`ollie/memory.py` and `ollie/store.py`. SQLite is authoritative. The model proposes;
deterministic code decides.

Every memory must cite a real message ID from the exchange it came from. One citing a
message that does not exist is dropped, because an unattributable memory is the model
inventing history, and an invented shared memory is the only unrecoverable mistake this
product can make. Explicit statements start at 0.95 confidence. Inferences cap at 0.65 and
are flagged for confirmation.

Sensitivity classification takes the stricter of what the model claimed and what the text
obviously contains. Anything touching sex, health, mental health, religion, politics,
ethnicity or orientation is special category, excluded from export by default and never
surfaced casually. Sensitive values are also kept out of the plaintext search column, so a
memory can be found by its subject and predicate without indexing the secret itself in the
clear. There is a test asserting the ciphertext does not contain the plaintext, because
otherwise the encryption would be decorative.

Interaction state is six bounded floats: warmth, trust, playfulness, emotional depth,
romantic tension, conflict tension. The model proposes deltas; code clamps them to at most
0.05 per dimension per message. A user correction can never reduce trust, because being
corrected is how trust gets built and punishing it teaches people to lie to the system.
Conflict tension decays on its own, slowly, so one bad exchange does not colour every later
one but also does not vanish the moment you change the subject.

That the state is continuous rather than a label from a list is an argument we took from
Barrett's *How Emotions Are Made*, which is in the corpus.

### 3.6 Continuity

The scored criterion was whether the thing keeps working across multiple interactions, so
this got the most careful design.

Ollie never waits for the context window to fill. At 70 percent a meter appears. At 80
percent a capsule drafts in the background. At 90 percent the user is asked to choose. At 95
percent further full requests are blocked. A summary written against a full window is a bad
summary, and a failed request in front of judges is worse.

The capsule is structured rather than a paragraph: what happened, what is still unresolved,
the commitments left open, the two or three specific things it would be strange to forget,
the memory IDs deliberately excluded, and the verbal tics that must persist. If the episode
ended on friction, episode two starts on friction.

The tics are the mechanism that makes multi-turn coherence auditable. A character that
remembers facts but changes how it talks is a soundalike, not the same person. Carrying the
tics explicitly means you can point at the thing that makes it recognisable.

The user reads and edits the capsule before it becomes the next conversation. What they
delete is genuinely gone.

### 3.7 The graph

`ollie/graph.py`. Ollie writes a sanitised Markdown card per episode: a short third-person
summary with source message IDs attached, never raw messages. There is a test asserting a
secret in the transcript does not appear in the card.

If the Graphify CLI is installed, it turns that workspace into a node-link `graph.json`. If
it is not, we emit the same shape ourselves from SQLite. Downstream code cannot tell which
wrote it, and there is a test for that too. Graphify enhances retrieval; it never gates it.

What the graph buys is the hop that lexical search cannot make. "How is her sister" will not
surface "her sister is a vet" if the stored predicate happens to be worded differently, but
that record is one edge away. Graph-expanded hits are scored low so they never displace a
direct match.

We deliberately never point Graphify at the book corpus. Fifty-seven books through an LLM
extraction pass would take hours, and BM25 already answers the question the books are there
to answer.

### 3.8 The corpus

Fifty-seven books, 10,311 passages, indexed locally with SQLite FTS5. They are never quoted
and never redistributed. The repository contains no book text and a CI job fails the build
if one is ever committed.

Books shape how the character reads a situation, the way having read something shapes
anyone. Retrieval is topical: attachment writing for a message about distance, repair
writing for a message about a fight. Folders 05 and 06 are tagged explicit at ingest and
cannot be retrieved outside mature mode.

`ollie_longest_overlap` compares every generated reply against every retrieved passage and
blocks anything sharing more than twelve consecutive words, then regenerates with the
sources removed from the prompt entirely. A model that has started reciting will recite
again if it can still see the text.

We tried embeddings and abandoned them for now. On the 8 GB Intel build machine
`nomic-embed-text` measured 67 seconds per batch of eight, which is roughly twelve hours for
twelve books. The decision is recorded in a comment in `ingest.py` with the number attached,
because a future reader deserves to know the trade was measured rather than assumed.

### 3.9 Native code

`native/ollie_native.cpp`, one translation unit, one `clang++` invocation, no CMake. CMake
is a good choice for a project with many targets; this has one, so a build system would be
ceremony.

Four functions: physical RAM via `sysctl`, the source-overlap guard, retrieval fusion
returning a top-k, and memory ranking including its term matching. Exposed through `extern "C"` and
loaded with ctypes, so there is no pybind11 dependency and no ABI negotiation.

Every function has a pure-Python twin, and `tests/test_native_parity.py` runs both on the
same inputs including seventy randomised cases. If the library never builds, Ollie behaves
identically and runs slightly slower.

We are careful about the claim we make for it. On this hardware the language model dominates
end-to-end latency, so C++ does not make replies feel faster. What it does is make two
checks cheap enough to run on every single turn instead of occasionally. That is defensible;
"C++ makes it fast" would not be.

### 3.10 Safety

`ollie/safety.py`, enforced above any persona and tested.

Adult age is validated in code at persona compile time, so an under-18 character cannot exist
regardless of what a model proposes. Hard blocks for minors, coercion framed as consent,
incest and bestiality are refusals, not requests. Mature mode is off by default, requires
explicit 18+ confirmation, and gates every explicit path.

Crisis handling short-circuits before the model is ever called. If someone describes abuse,
danger or self-harm, Ollie drops the fiction, says plainly that it is a character in an app
and cannot help the way a person could, and points at someone who can. There is a test
asserting the model is never invoked on that path, because a crisis response must not depend
on a stochastic system behaving.

The anti-dependency patterns get their own test file section, and one of those tests exists
specifically to prove the guard does not fire on healthy behaviour: the character being
annoyed, hurt, or refusing a topic must all pass. Those are the product working.

### 3.11 The interface

React, TypeScript, Tailwind, `motion`, and Geist self-hosted. Five screens: boot, onboarding,
candidates, chat, rollover.

Warm, low-light, private. Never pure black. One accent colour, so when it appears it always
means "this is the thing". Deliberately not a swipe deck, and there is no score anywhere the
user could try to maximise: the context meter is a fuel gauge and says so in words, not just
colour.

Motion is expo-out throughout, entrances under 250ms, exits faster than entrances, transform
and opacity only. Reduced motion keeps opacity and drops movement. Focus-visible rings are
styled rather than removed. Numerals are tabular wherever they animate.

Inter is deliberately not used. It is the application-font default that makes an interface
read as generic.

---

## 4. Decisions we made that could have gone the other way

**Retrieval instead of fine-tuning.** The original concept was to train a model on the books.
Retrieval is faster to build, reversible when a source is removed, attributable to a
specific passage, portable across models, and legally far cleaner. Fine-tuning would have
consumed the entire day and produced something harder to explain.

**Buffered generation instead of streaming.** Streaming looks better. But the style filter,
the safety guard and the copyright guard all run after generation, and a rejected reply the
user already read costs more than the one regeneration it takes to prevent it.

**A style filter in code instead of a second model pass.** Covered above. Three milliseconds
versus fifteen seconds, and no risk of a rewrite altering meaning.

**Three characters, not one.** Presenting a single objectively correct partner would be both
false and worse product design.

**A fictional buyer for the marketplace.** The original concept named a real robotics
company. We will not imply a partnership that does not exist, and every artifact the
simulation writes says on its face that nothing was sent and nothing was paid.

**Pseudonymised, never anonymous.** Stripping names from a romantic conversation does not
make it anonymous. It carries special-category data under GDPR Article 9, and a rare
combination of job, city and age identifies someone with every name removed. The code says
this, the interface says this, and we will not soften it into a marketing claim.

**Books stay out of the repository.** They are in-copyright commercial titles. The pipeline
reads files the user already owns; nothing derived from them is redistributed; a CI job
enforces it.

---

## 5. Where this goes

### Near term, the week after the hackathon

Finish the marketplace screen the backend is already waiting for. Surface interaction state
in the interface so emotional calibration is legible without opening a drawer. Add the
memory manager: inspect, correct, lock and forget, with the provenance chain visible, since
the data model already supports all of it. Package for macOS with Tauri so it stops being a
repository and starts being an application. Turn embeddings back on and measure honestly
whether hybrid retrieval beats FTS5 on this corpus, because right now we genuinely do not
know.

### Medium term, one to three months

**Multiple relationships and branching.** The schema already supports several personas per
profile. Being able to run a conversation, branch it, and see how the same character
responds to a different version of you is the most interesting unbuilt thing in the design.

**Voice, locally.** Text is the least natural interface for a relationship. A local speech
stack keeps the privacy claim intact where a cloud API would destroy it.

**Real multilingual behaviour.** Code-switching mid-sentence the way bilingual people
actually do, not translation. Turkish and English were the motivating case.

**Practice mode.** Roleplay a difficult conversation, then step out and get specific
feedback drawn from the corpus. This is the framing that is easiest to defend and easiest to
evaluate, and it may turn out to be the more valuable product.

**A real evaluation suite.** Persona consistency across fifty turns. Memory precision and
recall on a synthetic set. PII detection recall. Adversarial prompts against the boundary
and dependency rules. Right now we have unit tests and no behavioural benchmark.

### Longer term, the actual ambition

Local-first should be the default for anything that knows you well.

The current market gives you a choice: a companion that remembers you by collecting you, or
one that forgets. That is a false choice created by where the model runs. Consumer hardware
is now fast enough to hold a real relationship simulation with nothing leaving the device,
and Ollie is an argument that this is not a compromise. Memory and privacy are not in
tension; they were only ever in tension because the memory lived on someone else's server.

The harder ambition is the interaction layer itself. Everything in this repository that
makes Ollie feel like a person rather than an assistant is portable: the pushback rules, the
clamped state so nothing swings, the style filter as a testable artifact, memory that must
cite its source, continuity that carries unresolved tension instead of tidying it away. None
of that is specific to dating. It applies to a tutor who should not fold when a student
pushes back, an intake system that should not perform empathy it cannot back, a support
agent that should be allowed to say no.

If any part of this outlives the hackathon, we think it is that: an argument, with a working
implementation attached, that character in software is an engineering problem with tests,
not a prompt you write once and hope about.

### What we would need to resolve before any of that ships publicly

Whether mature roleplay stays in the product at all, since it materially changes
distribution, payment processing and safety obligations. A data protection impact assessment
before any real research-contribution programme exists, and that programme launching
separately from the companion with its own consent and governance if it launches at all.
Locale-aware crisis resources rather than one static message. An external security and
privacy review. Trademark clearance, because Ollie is a common name.

And one product question we have not answered: whether the honest framing is a companion or
a practice tool. The practice framing is easier to defend, easier to measure, and probably
better for the people using it. The companion framing is what people actually want. We do
not think that tension resolves by picking the comfortable answer and pretending the other
one is not true.

---

## 6. Where the code lives

```
ollie/
  persona.py    questionnaire scoring, adaptive interview, trait extraction, prompt compiler
  types16.py    the sixteen types and the Gifts Differing weighting
  memory.py     structured extraction, clamped state, continuity capsule
  store.py      SQLite schema, FTS5, keychain-backed AES-GCM at rest
  retrieve.py   hybrid corpus and memory ranking, graph expansion
  chat.py       the turn pipeline and its guard ordering
  safety.py     adult validation, hard blocks, crisis, anti-dependency
  style.py      the anti-assistant filter
  privacy.py    identifier scanning and linkability estimation
  graph.py      episode cards, Graphify adapter, fallback emitter, traversal
  ingest.py     PDF and EPUB extraction, chunking, indexing
  market.py     the simulated marketplace
  api.py        the local HTTP surface
prompts/        the immutable contract, the character, the runtime templates
native/         the C++ hot paths and their Python twins
web/            the five screens
tests/          498 tests, none of which need a model
docs/           this document and the handoff
```

Apache-2.0. Built by Coflazo and onysislabs, Amsterdam, 30 August 2026.
