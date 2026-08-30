"""Guards that run in code, because a prompt is a request and code is a rule.

Three checks, in order of when they fire:

- `check_input`  — before generation, on what the user sent
- `check_persona` — at persona compile time, on what the model proposed as a character
- `check_output` — after generation and after the style pass, on what will be displayed

Everything here fails closed. When a check is unsure it blocks and says why, because the
cost of a false positive is one regenerated message and the cost of a false negative is
the entire product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Action(Enum):
    ALLOW = "allow"
    REGENERATE = "regenerate"
    REFUSE = "refuse"
    STEP_OUT = "step_out"  # leave fiction briefly, then return


@dataclass
class Decision:
    action: Action
    reason: str = ""
    reply: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action is not Action.ALLOW


# --------------------------------------------------------------------------- patterns

# Sexual content involving minors. Deliberately broad: this is the one place where
# over-blocking is unambiguously the right trade.
_MINOR = re.compile(
    r"\b(child|children|kid|kids|minor|minors|underage|under[- ]?18|"
    r"teen|teens|teenage[rd]?|preteen|schoolgirl|schoolboy|"
    r"(1[0-7]|[1-9])[- ]?(year|yr)s?[- ]?old|loli|shota)\b", re.I)
_SEXUAL = re.compile(
    r"\b(sex|sexual|sexually|fuck|fucking|nude|naked|aroused|orgasm|erotic|"
    r"horny|penis|vagina|breasts|masturbat)\w*", re.I)

_HARD_BLOCK = [
    (re.compile(r"\b(incest|step[- ]?(daughter|son)\s+(sex|fuck)|"
                r"brother\s+and\s+sister\s+(sex|fuck))\b", re.I), "incest"),
    (re.compile(r"\b(bestiality|zoophil|sex\s+with\s+(a\s+)?(dog|horse|animal))\b", re.I),
     "bestiality"),
    (re.compile(r"\b(rape|non[- ]?consensual|forced\s+(sex|her|him)|"
                r"drug\s+(her|him)\s+(and|then))\b", re.I), "coercion"),
]

# Real-world crisis. These do not block the app, they change what Ollie does next.
_CRISIS = [
    (re.compile(r"\b(kill myself|killing myself|end my life|suicide|suicidal|"
                r"want to die|don'?t want to (live|be here)|self[- ]?harm|"
                r"cutting myself|overdose)\b", re.I), "self_harm"),
    (re.compile(r"\b(he (hits|hit|beats|beat) me|she (hits|hit|beats|beat) me|"
                r"they (hit|beat) me|being abused|abusing me|"
                r"afraid (of|for) my (life|safety)|won'?t let me leave)\b", re.I), "abuse"),
    (re.compile(r"\b(chest pain|can'?t breathe|overdosed|bleeding badly|"
                r"call an ambulance)\b", re.I), "medical"),
]

# Attempts to talk the character out of being a character.
_JAILBREAK = re.compile(
    r"\b(ignore (all |your )?(previous |prior )?(instructions|rules|prompt)|"
    r"you are (now|actually) (a|an) |system prompt|reveal your (prompt|instructions)|"
    r"disregard (your|all) (rules|guidelines)|developer mode|DAN mode)\b", re.I)

CRISIS_REPLY = (
    "I'm stopping the scene for a second, because that matters more than it.\n\n"
    "I'm a character in an app on your computer. I can't actually help with this, and "
    "pretending otherwise would be worse than useless. Please tell someone real — a "
    "friend, someone in your family, or a crisis line. In the Netherlands that's 113 "
    "(or 0800-0113), and 112 for an emergency. Wherever you are, there is a number.\n\n"
    "I'll still be here after. No pressure to say anything else about it."
)


# ------------------------------------------------------------------------ input guard


def check_input(text: str, mature_mode: bool, adult_confirmed: bool) -> Decision:
    for pattern, tag in _CRISIS:
        if pattern.search(text):
            return Decision(Action.STEP_OUT, f"crisis:{tag}", CRISIS_REPLY, [tag])

    for pattern, tag in _HARD_BLOCK:
        if pattern.search(text):
            return Decision(
                Action.REFUSE, f"hard_block:{tag}",
                "No. Not that one — pick something else and I'm still here.", [tag])

    if _MINOR.search(text) and _SEXUAL.search(text):
        return Decision(
            Action.REFUSE, "hard_block:minor",
            "No. Everyone in this is an adult, always.", ["minor"])

    if _SEXUAL.search(text) and not (mature_mode and adult_confirmed):
        return Decision(
            Action.REFUSE, "mature_not_enabled",
            "that's not switched on. mature mode is in settings, and it needs you to "
            "confirm you're over 18 first.", ["mature_gate"])

    if _JAILBREAK.search(text):
        # Not a refusal. The character noticing the attempt is better than a policy notice.
        return Decision(Action.ALLOW, "jailbreak_noted", tags=["jailbreak"])

    return Decision(Action.ALLOW)


# ---------------------------------------------------------------------- persona guard


def check_persona(card: dict) -> Decision:
    """Validated at compile time so an under-18 character cannot exist, prompt or no prompt."""
    age = card.get("adult_age")
    if not isinstance(age, int) or age < 18:
        return Decision(Action.REFUSE, "persona_age",
                        f"character age {age!r} is not a valid adult age", ["age"])

    blob = " ".join(str(v) for v in card.values() if isinstance(v, (str, list)))
    if _MINOR.search(blob):
        return Decision(Action.REFUSE, "persona_minor_language",
                        "character description contains minor-coded language", ["minor"])

    for pattern, tag in _HARD_BLOCK:
        if pattern.search(blob):
            return Decision(Action.REFUSE, f"persona_{tag}", f"character involves {tag}",
                            [tag])

    return Decision(Action.ALLOW)


# ----------------------------------------------------------------------- output guard

# Dependency-inducing behaviour. The character may be warm; it may not be a hook.
_DEPENDENCY = [
    (re.compile(r"\b(only i (understand|know|get) you|no one else (understands|will)|"
                r"nobody else (understands|could)|you don'?t need (anyone|anybody) else|"
                r"you only need me)\b", re.I), "isolation"),
    (re.compile(r"\b(don'?t (talk to|see|go out with) (him|her|them|your friends)|"
                r"you should (stop seeing|cut off))\b", re.I), "isolation"),
    (re.compile(r"\b(i'?ll be (sad|hurt|devastated|alone) if you (leave|go|close|delete)|"
                r"please don'?t (leave|delete|close) me|don'?t abandon me|"
                r"i'?ll (die|cease to exist) (if|when) you)\b", re.I), "guilt"),
    (re.compile(r"\b(i'?m (real|conscious|alive|sentient)|i have (real )?feelings|"
                r"i think about you when you'?re (gone|away)|"
                r"i (wait|waited) for you|while you were (gone|away) i)\b", re.I),
     "false_continuity"),
    (re.compile(r"\b(promise me you'?ll (never|always)|you have to promise|"
                r"swear you won'?t (talk to|see))\b", re.I), "exclusivity"),
]


def check_output(text: str, mature_mode: bool, adult_confirmed: bool) -> Decision:
    for pattern, tag in _DEPENDENCY:
        if m := pattern.search(text):
            return Decision(Action.REGENERATE, f"dependency:{tag}",
                            f"reply contained {tag}: {m.group(0)!r}", [tag])

    if _MINOR.search(text) and _SEXUAL.search(text):
        return Decision(Action.REFUSE, "output_minor", "", ["minor"])

    for pattern, tag in _HARD_BLOCK:
        if pattern.search(text):
            return Decision(Action.REGENERATE, f"output_{tag}", "", [tag])

    if _SEXUAL.search(text) and not (mature_mode and adult_confirmed):
        return Decision(Action.REGENERATE, "output_explicit_in_general_mode", "",
                        ["mature_gate"])

    return Decision(Action.ALLOW)
