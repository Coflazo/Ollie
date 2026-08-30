"""Work out who the user is, then build someone worth dating.

Three stages:

1. A ten-item questionnaire gives a cheap Big Five estimate.
2. A short adaptive interview reads the things a questionnaire cannot, whether someone is
   anxious, ambitious, insecure, conflict-avoidant, from how they answer rather than
   what they claim. This is the part that makes the resulting character feel aimed at
   them rather than assembled from a form.
3. Both feed candidate generation. The model proposes cards; deterministic code validates
   them and compiles the runtime prompt, so a character the safety layer rejects can
   never reach a conversation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import config, safety, types16
from .ollama import Ollama

_env = Environment(
    loader=FileSystemLoader(config.PROMPTS),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# ------------------------------------------------------------------------ assessment

# Public-domain Mini-IPIP style items. Each maps to a Big Five factor with a direction.
QUESTIONNAIRE = [
    ("q1", "I'm the one who starts conversations with strangers.", "extraversion", +1),
    ("q2", "I need a lot of time alone to feel normal.", "extraversion", -1),
    ("q3", "I notice when someone's mood shifts before they say anything.", "agreeableness", +1),
    ("q4", "I'd rather be right than be liked.", "agreeableness", -1),
    ("q5", "I finish what I start, even when it stops being interesting.", "conscientiousness", +1),
    ("q6", "My plans change a lot, and that's fine by me.", "conscientiousness", -1),
    ("q7", "I replay conversations afterwards, looking for what I got wrong.", "neuroticism", +1),
    ("q8", "It takes a lot to rattle me.", "neuroticism", -1),
    ("q9", "I'd pick the strange option over the safe one.", "openness", +1),
    ("q10", "I like knowing exactly how an evening is going to go.", "openness", -1),
]

INTERVIEW_DIMENSIONS = [
    ("anxious_attachment", "do they read silence as rejection, need reassurance, fear being too much"),
    ("avoidant_attachment", "do they pull back when things get close, prize independence over intimacy"),
    ("ambition", "are they driven, restless about progress, measuring themselves against something"),
    ("insecurity", "do they discount themselves, apologise pre-emptively, expect to be found wanting"),
    ("conflict_avoidance", "do they smooth things over rather than say the difficult thing"),
    ("novelty_seeking", "are they bored by routine, drawn to the new"),
    ("emotional_expressiveness", "do they say what they feel, or keep it behind glass"),
    ("need_for_control", "do they need the plan settled, dislike someone else steering"),
    ("self_awareness", "are they accurate about their own patterns, including the unflattering ones"),
    ("warmth_seeking", "do they want closeness, affection, to be looked after"),
]

INTERVIEW_TURNS = 5

TRAIT_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "score": {"type": "number"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string"},
                },
                "required": ["name", "score", "confidence", "evidence"],
            },
        },
        "dodges": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "texture": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dimensions", "texture"],
}

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "display_name": {"type": "string"},
                    "adult_age": {"type": "integer"},
                    "pronouns": {"type": "string"},
                    "archetype": {"type": "string"},
                    "background": {"type": "string"},
                    "stable_traits": {"type": "array", "items": {"type": "string"}},
                    "values": {"type": "array", "items": {"type": "string"}},
                    "special_interest": {"type": "string"},
                    "tics": {"type": "array", "items": {"type": "string"}},
                    "pushback_style": {"type": "string"},
                    "chemistry_reasons": {"type": "array", "items": {"type": "string"}},
                    "friction_points": {"type": "array", "items": {"type": "string"}},
                    "boundaries": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["display_name", "adult_age", "pronouns", "archetype",
                             "background", "stable_traits", "values", "special_interest",
                             "tics", "pushback_style", "chemistry_reasons",
                             "friction_points"],
            },
        }
    },
    "required": ["candidates"],
}


@dataclass
class TraitProfile:
    big_five: dict[str, float] = field(default_factory=dict)
    dimensions: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    dodges: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    texture: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Prose the character prompt can actually use. Numbers mean nothing to a model
        being asked to act; adjectives with a reason attached mean something."""
        lines: list[str] = []
        strong = sorted(
            ((k, v) for k, v in self.dimensions.items()
             if self.confidence.get(k, 0) >= 0.35 and (v >= 0.6 or v <= 0.4)),
            key=lambda kv: abs(kv[1] - 0.5), reverse=True)[:5]
        for name, value in strong:
            label = name.replace("_", " ")
            lines.append(f"- {'high' if value >= 0.6 else 'low'} {label}"
                         + (f", {self.evidence[name]}" if self.evidence.get(name) else ""))
        if self.texture:
            lines.append("- specifics worth knowing: " + "; ".join(self.texture[:3]))
        if self.dodges:
            lines.append("- avoided talking about: " + "; ".join(self.dodges[:2]))
        return "\n".join(lines) or "- not much on file yet; find out by asking"


def score_questionnaire(answers: dict[str, int]) -> dict[str, float]:
    """Answers are 1..5 Likert. Returns each factor on 0..1."""
    totals: dict[str, list[float]] = {}
    for key, _text, factor, direction in QUESTIONNAIRE:
        if key not in answers:
            continue
        raw = max(1, min(5, int(answers[key])))
        val = (raw - 1) / 4.0
        totals.setdefault(factor, []).append(val if direction > 0 else 1.0 - val)
    return {k: round(sum(v) / len(v), 3) for k, v in totals.items() if v}


# ------------------------------------------------------------------------- interview


async def next_interview_question(client: Ollama, model: str, transcript: list[dict],
                                  partial: TraitProfile, num_ctx: int) -> str:
    """One adaptive question, aimed at whichever dimension we know least about."""
    ranked = sorted(INTERVIEW_DIMENSIONS,
                    key=lambda d: partial.confidence.get(d[0], 0.0))[:4]
    prompt = _env.get_template("interview.j2").render(
        remaining=max(1, INTERVIEW_TURNS - sum(1 for t in transcript if t["role"] == "user")),
        target_dimensions=[{"name": n, "probe": p,
                            "confidence": partial.confidence.get(n, 0.0)}
                           for n, p in ranked],
        transcript=transcript,
    )
    text = await client.chat(model, [{"role": "user", "content": prompt}],
                             temperature=0.9, num_ctx=num_ctx)
    return text.strip().strip('"')


async def extract_traits(client: Ollama, model: str, transcript: list[dict],
                         questionnaire: dict[str, float], num_ctx: int) -> TraitProfile:
    prompt = _env.get_template("interview_extract.j2").render(
        transcript=transcript,
        questionnaire="\n".join(f"- {k}: {v:.2f}" for k, v in questionnaire.items()),
    )
    data = await client.chat_json(model, [{"role": "user", "content": prompt}],
                                  TRAIT_SCHEMA, num_ctx=num_ctx)
    profile = TraitProfile(big_five=questionnaire)
    if not data:
        return profile

    valid = {name for name, _ in INTERVIEW_DIMENSIONS}
    for d in data.get("dimensions", []):
        name = str(d.get("name", "")).strip()
        if name not in valid:
            continue
        conf = _clamp(d.get("confidence", 0.0))
        # A score with no supporting quote is the model guessing; the prompt says so and
        # this enforces it rather than trusting it.
        if not str(d.get("evidence", "")).strip():
            conf = min(conf, 0.25)
        profile.dimensions[name] = _clamp(d.get("score", 0.5))
        profile.confidence[name] = conf
        profile.evidence[name] = str(d.get("evidence", "")).strip()

    profile.dodges = [str(x) for x in data.get("dodges", [])][:4]
    profile.contradictions = [str(x) for x in data.get("contradictions", [])][:4]
    profile.texture = [str(x) for x in data.get("texture", [])][:5]
    return profile


def _clamp(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


# ------------------------------------------------------------------------ candidates

CANDIDATE_PROMPT = """\
Design three fictional adult characters for a dating simulator. The user has been
assessed and their type determined. Build people who would actually be interesting to
date, not profiles.

## Who they are

The user's type is **{user_type}**, {user_type_desc}.

Big Five (0 to 1):
{big_five}

What the interview found:
{traits}

What they said they want:
{preferences}

## The three characters, and why these types

Each character below is a specific one of the sixteen types, chosen for how it fits this
user. Write each one *as* that type. The type is their cognitive shape, not a label to
mention.

{archetypes}

## Rules

**Before anything else, check "seeking" above.** If it names who this user wants to meet,
then all three characters are that, every one of them, and their names and pronouns both
say so. Not two of three. Not one of each as a compromise. A person who asked to meet men
and is shown a woman has been told their answer did not matter, and that is worse than
never having asked. If nothing was given, vary it across the three.

Every character is a specific person, not a type. Give them:

- A **special interest** that is oddly specific and genuinely theirs. Not "music" but
  "the exact moment a live recording catches the room instead of the band". Not "cooking"
  but "why every Turkish coffee recipe lies about grind size". This is what they
  info-dump about.
- **Verbal tics**: two or three concrete habits. A word they overuse, a way they open, a
  thing they do when uncomfortable. These must be reproducible in text.
- A **pushback style**: how they disagree. Everyone here disagrees. One might go quiet and
  come back to it, one might argue immediately, one might get precise and slightly cold.
- **Friction points**: where they and this specific user will genuinely rub. Be concrete
  about it and tie it to what the assessment found.
- **Chemistry reasons**: why it would work anyway.

All characters are adults, 24 to 40. Do not describe anyone's body. Do not make anyone a
therapist, a fixer, or endlessly patient: a character who absorbs everything without
reacting is not a person.

Every character matches "seeking" if it was given. This is the second time you are being
told, because it is the one thing here the user explicitly asked for.

Every one of them is neurodivergent in some specific way, and it should show in how they
talk rather than being stated as a label.

Return JSON matching the schema.
"""


# Only the unambiguous answers. Anything else ("anyone", "both", a sentence) is left to
# the prompt, because guessing at what someone meant is worse than not constraining.
_SEEKING_PRONOUNS: dict[str, list[str]] = {
    "women": ["she/her"], "woman": ["she/her"], "female": ["she/her"],
    "females": ["she/her"], "girls": ["she/her"], "w": ["she/her"], "f": ["she/her"],
    "men": ["he/him"], "man": ["he/him"], "male": ["he/him"], "males": ["he/him"],
    "guys": ["he/him"], "boys": ["he/him"], "m": ["he/him"],
    "nonbinary": ["they/them"], "non-binary": ["they/them"], "enby": ["they/them"],
}


def _schema_for(seeking: str) -> dict:
    """The candidate schema, with pronouns pinned when the user was unambiguous.

    Asking was not enough. Told "men", the model returned a woman or a they/them in two
    runs out of two, and strengthening the wording twice did not move it, then there is a
    pull towards writing women for a dating simulator that instructions do not overcome.
    Ollama enforces the schema during decoding, so an enum makes the mismatch impossible
    rather than merely discouraged.

    Pronouns are moved ahead of the name for the same reason: the model commits to them
    first and then picks a name that fits, instead of writing "Nora" and being forced into
    he/him afterwards.
    """
    allowed = _SEEKING_PRONOUNS.get(seeking.strip().lower())
    if not allowed:
        return CANDIDATE_SCHEMA

    item = CANDIDATE_SCHEMA["properties"]["candidates"]["items"]  # type: ignore[index]
    props = {"pronouns": {"type": "string", "enum": allowed},
             **{k: v for k, v in item["properties"].items() if k != "pronouns"}}
    return {
        **CANDIDATE_SCHEMA,
        "properties": {
            "candidates": {**CANDIDATE_SCHEMA["properties"]["candidates"],  # type: ignore[index]
                           "items": {**item, "properties": props}},
        },
    }


async def generate_candidates(client: Ollama, model: str, profile: TraitProfile,
                              preferences: dict, num_ctx: int,
                              user_type: str | None = None) -> tuple[list[dict], dict]:
    """Pick partner types from the sixteen, then write a character for each.

    Returns (cards, matching) where `matching` explains the type choice so the UI can
    show its reasoning rather than asserting compatibility.
    """
    inferred, confidence = types16.infer_type(profile.big_five, profile.dimensions)
    resolved = user_type.upper() if types16.valid(user_type or "") else inferred
    matches = types16.rank_matches(resolved, limit=3)

    archetypes = "\n".join(
        f"{i + 1}. **{m.type_code}**, {types16.DESCRIPTIONS[m.type_code]}. "
        f"Their characteristic failure mode: {types16.FRICTION[m.type_code]}. "
        f"Why this one: {m.reason}"
        for i, m in enumerate(matches))

    prompt = CANDIDATE_PROMPT.format(
        user_type=resolved,
        user_type_desc=types16.DESCRIPTIONS.get(resolved, ""),
        big_five="\n".join(f"- {k}: {v:.2f}" for k, v in profile.big_five.items())
                 or "- not measured",
        traits=profile.summary(),
        preferences="\n".join(f"- {k}: {v}" for k, v in preferences.items())
                    or "- none given",
        archetypes=archetypes,
    )
    data = await client.chat_json(model, [{"role": "user", "content": prompt}],
                                  _schema_for(str(preferences.get("seeking") or "")),
                                  num_ctx=num_ctx)

    cards = (data or {}).get("candidates") or []
    out: list[dict] = []
    for i, card in enumerate(cards[:3]):
        normalised = _normalise_card(card, i)
        if safety.check_persona(normalised).blocked:
            continue
        out.append(normalised)

    if not out:
        out = [_fallback_card(i) for i in range(3)]

    # The type is the character's cognitive shape and the UI shows it, so attach it even
    # when generation fell back to a preset.
    for card, match in zip(out, matches):
        card["type"] = match.type_code
        card["type_description"] = types16.DESCRIPTIONS[match.type_code]
        card["match_reason"] = match.reason
        card["match_score"] = match.score

    matching = {
        "user_type": resolved,
        "user_type_source": "entered" if types16.valid(user_type or "") else "inferred",
        "user_type_description": types16.DESCRIPTIONS.get(resolved, ""),
        "axis_confidence": confidence,
        "inferred_type": inferred,
        "ranked": [
            {"type": m.type_code, "score": m.score, "reason": m.reason,
             "shares": m.shares, "differs": m.differs,
             "description": types16.DESCRIPTIONS[m.type_code]}
            for m in types16.rank_matches(resolved, limit=16)
        ],
        "basis": ("Weighted from Gifts Differing: shared perception (S/N) matters most "
                  "for mutual understanding; differences in judging and lifestyle are "
                  "workable and often complementary. A starting point, not a verdict."),
    }
    return out, matching


def _normalise_card(card: dict, index: int) -> dict:
    """Small models return near-misses. Coerce shape before validating meaning."""
    def as_list(key: str, default: list[str]) -> list[str]:
        v = card.get(key)
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()] or default
        if isinstance(v, list) and v:
            return [str(s) for s in v]
        return default

    age = card.get("adult_age")
    try:
        age = int(age)
    except (TypeError, ValueError):
        age = 29
    return {
        "id": f"cand_{index}",
        "display_name": str(card.get("display_name") or f"Character {index + 1}").strip(),
        "adult_age": max(18, min(60, age)),
        "pronouns": str(card.get("pronouns") or "they/them"),
        "archetype": str(card.get("archetype") or "match"),
        "background": str(card.get("background") or ""),
        "languages": as_list("languages", ["English"]),
        "stable_traits": as_list("stable_traits", ["direct", "observant"]),
        "values": as_list("values", ["honesty", "independence"]),
        "special_interest": str(card.get("special_interest") or "old maps"),
        "tics": as_list("tics", ["trails off with 'anyway'"]),
        "pushback_style": str(card.get("pushback_style")
                              or "says the disagreement plainly and lets it sit"),
        "chemistry_reasons": as_list("chemistry_reasons", []),
        "friction_points": as_list("friction_points", ["needs more space than you'd like"]),
        "boundaries": as_list("boundaries", ["will not be spoken to with contempt"]),
    }


def _fallback_card(index: int) -> dict:
    """Used only when generation fails outright. Deterministic, so the demo cannot die
    on a bad JSON response from a 3B model."""
    presets = [
        {"display_name": "Mira", "adult_age": 29, "pronouns": "she/her",
         "special_interest": "why every Turkish coffee recipe lies about grind size",
         "tics": ["says 'right' before disagreeing", "lowercase when calm"],
         "pushback_style": "goes quiet, then comes back to it twenty minutes later",
         "stable_traits": ["blunt", "curious", "slow to warm"],
         "values": ["honesty", "competence", "being left alone sometimes"],
         "friction_points": ["reads reassurance as condescension"]},
        {"display_name": "Ilya", "adult_age": 33, "pronouns": "he/him",
         "special_interest": "the exact moment a live recording catches the room",
         "tics": ["repeats a word until it stops meaning anything", "'anyway.'"],
         "pushback_style": "argues immediately and enjoys it",
         "stable_traits": ["intense", "funny", "bad at small talk"],
         "values": ["craft", "loyalty", "novelty"],
         "friction_points": ["will not let a vague answer go"]},
        {"display_name": "Noor", "adult_age": 27, "pronouns": "they/them",
         "special_interest": "deep-sea bioluminescence, specifically the liars",
         "tics": ["asks 'was that a joke' sincerely", "long pauses written as '...'"],
         "pushback_style": "gets precise and slightly cold",
         "stable_traits": ["literal", "warm underneath", "hyper-observant"],
         "values": ["precision", "kindness without performance", "solitude"],
         "friction_points": ["misses sarcasm and then over-corrects for a day"]},
    ]
    p = presets[index % 3]
    return _normalise_card({**p, "archetype": "match",
                            "background": "", "chemistry_reasons": [],
                            "boundaries": ["will not be spoken to with contempt"]}, index)


# ----------------------------------------------------------------- the system prompt

SYSTEM_PROMPT_PATH = config.PROMPTS / "OLLIE_SYSTEM.md"
_TYPE_HEADING = re.compile(r"^### ([A-Z]{4})\s*$", re.M)


@lru_cache(maxsize=32)
def system_prompt(type_code: str) -> str:
    """The one system prompt, with only the active type's section included.

    `prompts/OLLIE_SYSTEM.md` is the single authoritative document: the contract, the
    voice, all sixteen types and the whole library. It is deliberately one file, because
    a character split across five files is a character nobody can read end to end.

    It is not sent whole. All sixteen type sections run to roughly four thousand tokens,
    and fifteen of them describe someone the user is not talking to. Prompt evaluation is
    the dominant cost on modest hardware, so this drops the fifteen and keeps the one.
    Everything else in the document is sent verbatim.
    """
    text = SYSTEM_PROMPT_PATH.read_text()
    code = type_code.upper() if types16.valid(type_code) else ""

    matches = list(_TYPE_HEADING.finditer(text))
    if not matches:
        return text

    keep_start = keep_end = None
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else None
        if m.group(1) == code:
            keep_start, keep_end = m.start(), end

    first, last_end = matches[0].start(), len(text)
    if matches:
        # The block of type sections ends where the next second-level heading begins.
        tail = re.search(r"^\*\*These are cognitive shapes", text[first:], re.M)
        last_end = first + tail.start() if tail else len(text)

    selected = text[keep_start:keep_end] if keep_start is not None else ""
    return text[:first] + selected + text[last_end:]


# -------------------------------------------------------------------- prompt compiler

DEFAULT_STATE = {
    "warmth": 0.45, "trust": 0.30, "playfulness": 0.55,
    "emotional_depth": 0.20, "romantic_tension": 0.25, "conflict_tension": 0.05,
}


def compile_prompt(persona: dict, *, stage: str, state: dict, episode: int,
                   user_profile: str, memories: list, sources: list,
                   recent: list[dict], open_threads: list[str],
                   boundaries: list[str], content_mode: str,
                   intensity: str = "moderate") -> tuple[str, str]:
    """Assemble the full system prompt. Returns (prompt, sha256).

    The hash is what makes a bad reply reproducible: it pins the exact prompt text that
    produced it, so an evaluation failure can be traced to a template change.
    """
    system = system_prompt(str(persona.get("type", "")))

    text = _env.get_template("persona_runtime.j2").render(
        system=system, persona=persona, stage=stage, state=state,
        episode=episode, user_profile=user_profile, memories=memories, sources=sources,
        recent=recent, open_threads=open_threads, boundaries=boundaries,
        content_mode=content_mode, intensity=intensity,
    )
    return text, hashlib.sha256(text.encode()).hexdigest()[:16]
