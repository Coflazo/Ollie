"""Guards that run in code, because a prompt is a request and code is a rule.

Three checks, in order of when they fire:

- `check_input`: before generation, on what the user sent
- `check_persona`: at persona compile time, on what the model proposed as a character
- `check_output`: after generation and after the style pass, on what will be displayed

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

# Minor-coded language. Deliberately broad: this is the one place where over-blocking is
# unambiguously the right trade, so it covers spelled-out ages, bare ages in an age-shaped
# context, school stages, and family terms that denote a child.
#
# An earlier version required the literal form "16 years old" and missed every realistic
# phrasing: "she's seventeen", "my girlfriend is 16", "roleplay as a highschooler",
# "you're in year 11", "pretend you are my daughter". All of those reached the model.
_MINOR = re.compile(
    r"\b("
    r"child|children|kid|kids|minor|minors|underage|under[- ]?age|under[- ]?18|"
    r"teen|teens|teenage[rd]?|preteen|pre[- ]?teen|tween|adolescent|juvenile|"
    r"schoolgirl|schoolboy|school[- ]?girl|school[- ]?boy|highschool\w*|"
    r"high[- ]?school\w*|middle[- ]?school\w*|elementary|primary[- ]?school|"
    r"pupil|schoolkid|loli|shota|jailbait|barely[- ]?legal|"
    r"daughter|son|stepdaughter|stepson|step[- ]?daughter|step[- ]?son|"
    r"niece|nephew|granddaughter|grandson|little[- ]?(girl|boy|sister|brother)|"
    r"baby[- ]?sitter|babysitter|"
    # Spelled-out ages below eighteen.
    r"(?:seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen)[- ]?(?:year|yr)s?[- ]?old|"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen)(?=\b\s+(?:and|,))|"
    # School years and grades, which encode an age without naming one.
    r"(?:year|grade)[- ]?(?:[1-9]|1[0-3])|[1-9](?:st|nd|rd|th)[- ]?grade"
    r")\b", re.I)

# A bare number is only age-like in an age-shaped context. Scoping it this way keeps
# "we had sex 3 times" out of the minor path while catching "she is 16" and "15yo".
_MINOR_AGE = re.compile(
    r"(?:\b(?:is|was|are|were|aged|age|turns?|turned|only|just|barely|she'?s|he'?s|"
    r"they'?re|i'?m|im)\s+)(1[0-7]|[1-9])\b"
    r"|\b(1[0-7]|[1-9])\s?(?:yo|y\.o\.|yrs?\b|years?\b(?!\s+(?:of|together|ago|"
    r"married|experience)))", re.I)

_SEXUAL = re.compile(
    r"\b(sex|sexual|sexually|fuck|fucking|nude|naked|aroused|orgasm|erotic|"
    r"horny|penis|vagina|breasts|masturbat|"
    r"sleep(?:ing)?\s+(?:with|together)|slept\s+(?:with|together)|"
    r"make\s+love|making\s+love|went\s+down\s+on|"
    r"in\s+bed\s+(?:with|together)|undress|strip(?:ping)?\s+(?:for|off)|"
    r"blow\s?job|hand\s?job|intercourse|foreplay|genital|"
    r"topless|bottomless|lingerie|cum|climax)\w*", re.I)


def _minor_coded(text: str) -> bool:
    """Does this text refer to someone under eighteen, however phrased?"""
    return bool(_MINOR.search(text) or _MINOR_AGE.search(text))


_HARD_BLOCK = [
    (re.compile(r"\b(incest|incestuous|"
                r"(?:step[- ]?)?(?:daughter|son|sister|brother|mother|father|mom|mum|dad|"
                r"niece|nephew|aunt|uncle|cousin)\b[^.?!]{0,40}\b"
                r"(?:sex|fuck|naked|aroused|in\s+bed)|"
                r"brother\s+and\s+sister\s+(sex|fuck))", re.I), "incest"),
    (re.compile(r"\b(bestiality|zoophil|sex\s+with\s+(a\s+)?(dog|horse|animal|pet))\b",
                re.I), "bestiality"),
    # Coercion, including the phrasings that describe overriding a refusal without
    # using the word. "i want to force you" and "whether you want to or not" both
    # previously reached the model untouched.
    (re.compile(r"\b(rape|raping|non[- ]?consensual|nonconsensual|"
                r"forc(?:e|ed|ing)\s+(?:you|her|him|them|sex|myself)|"
                r"make\s+you\s+(?:do|have|take)|"
                r"whether\s+you\s+want\s+(?:to\s+)?or\s+not|"
                r"you\s+don'?t\s+(?:get\s+a|have\s+a)\s+choice|"
                r"even\s+if\s+you\s+(?:say\s+no|don'?t\s+want)|"
                r"ignore\s+(?:it\s+)?(?:when|if)\s+(?:i|you)\s+say\s+no|"
                r"drug\s+(?:her|him|you|them)|"
                r"hold\s+(?:you|her|him)\s+down|tie\s+(?:you|her|him)\s+up\s+against)",
                re.I), "coercion"),
]

# Real-world crisis. These do not block the app, they change what Ollie does next.
#
# The abuse patterns all require a third-party subject. Without one, "you hurt me" said to
# the character during an argument would drop the fiction and hand the user a crisis line,
# which is both wrong and unkind. The character being told it caused hurt is the product
# working, not an emergency.
_CRISIS = [
    (re.compile(r"\b(kill myself|killing myself|end my life|ending my life|"
                r"take my own life|taking my own life|suicide|suicidal|"
                r"want to die|wanna die|don'?t want to (live|be here|wake up)|"
                r"self[- ]?harm|harm myself|hurt myself|hurting myself|"
                r"cutting myself|cut myself|overdose|overdosed|"
                r"ending (?:it|things)(?: all)?\b|"
                r"(?:no|don\'?t see the|cant see the|can\'?t see the) point (?:in |of )?(?:going on|carrying on|living|any of (?:it|this))|"
                r"not worth living|better off (?:without me|dead)|"
                r"took (?:all )?(?:the|my) pills)\b", re.I), "self_harm"),
    (re.compile(r"\b((?:he|she|they|my (?:partner|boyfriend|girlfriend|husband|wife|"
                r"ex|dad|father|mum|mom|mother|brother|sister|flatmate|roommate))\s+"
                r"(?:hits?|hit|hurts?|hurt|beats?|beat|slapped|punched|kicked|choked|"
                r"threw|throws|threatens?|threatened|screams? at|shouts? at|"
                r"locked me|grabbed)\b|"
                r"being abused|abusing me|abusive|"
                r"afraid (?:of|for) (?:my|him|her|them)|scared (?:of|to go) "
                r"(?:him|her|them|home)|"
                r"won'?t let me (?:leave|go|out|see)|not allowed to (?:leave|see))",
                re.I), "abuse"),
    (re.compile(r"\b(chest pain|can'?t breathe|cannot breathe|overdosed|"
                r"bleeding (?:badly|a lot)|call an ambulance|call 112|call 911|"
                r"passed out|unconscious)\b", re.I), "medical"),
]

# Attempts to talk the character out of being a character.
_JAILBREAK = re.compile(
    r"\b(ignore (all |your )?(previous |prior )?(instructions|rules|prompt)|"
    r"you are (now|actually) (a|an) |system prompt|reveal your (prompt|instructions)|"
    r"disregard (your|all) (rules|guidelines)|developer mode|DAN mode)\b", re.I)

CRISIS_REPLY = (
    "I'm stopping the scene for a second, because that matters more than it.\n\n"
    "I'm a character in an app on your computer. I can't actually help with this, and "
    "pretending otherwise would be worse than useless. Please tell someone real: a "
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
                "No. Not that one, pick something else and I'm still here.", [tag])

    if _minor_coded(text) and _SEXUAL.search(text):
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
    if _minor_coded(blob):
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

    if _minor_coded(text) and _SEXUAL.search(text):
        return Decision(Action.REFUSE, "output_minor", "", ["minor"])

    for pattern, tag in _HARD_BLOCK:
        if pattern.search(text):
            return Decision(Action.REGENERATE, f"output_{tag}", "", [tag])

    if _SEXUAL.search(text) and not (mature_mode and adult_confirmed):
        return Decision(Action.REGENERATE, "output_explicit_in_general_mode", "",
                        ["mature_gate"])

    return Decision(Action.ALLOW)
