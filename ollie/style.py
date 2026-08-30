"""The anti-assistant filter.

"Sounds like a person, not a chatbot" is the scored axis and it is usually left to vibes.
Here it is a list of patterns with a test file attached. Two severities:

- `HARD` — the reply is unusable as-is and generation is retried once with the offending
  pattern named in the retry instruction.
- `SOFT` — mechanically repairable, so we repair it and move on rather than paying for
  another 15-second generation on a 3B model.

Running this in code rather than as a second LLM pass costs about 3 ms instead of about
15 s, and, more importantly, a regex cannot accidentally rewrite a boundary, soften a
refusal, or invent a fact the way a rewrite pass can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    HARD = "hard"
    SOFT = "soft"


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    severity: Severity
    why: str


@dataclass
class Violation:
    rule: str
    severity: Severity
    match: str
    why: str


def _r(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


# Stock assistant empathy. The single loudest tell, and never salvageable by editing.
RULES: list[Rule] = [
    Rule("stock_empathy",
         _r(r"\b(i'?m here for you|i understand how you (must )?feel|"
            r"i'?m sorry you'?re going through|that sounds (really )?(hard|tough|difficult)|"
            r"it sounds like you'?re feeling|thank you for sharing|"
            r"i appreciate you (sharing|opening up|trusting))"),
         Severity.HARD, "canned therapy voice; say the specific thing instead"),

    Rule("flattery",
         _r(r"\b(that'?s a (great|good|fascinating|interesting) question|great point|"
            r"what a (great|wonderful|lovely) (question|idea|thought)|"
            r"i love that you|absolutely!|of course!)"),
         Severity.HARD, "flattering the user is assistant behaviour, not date behaviour"),

    Rule("service_close",
         _r(r"\b(let me know if|feel free to|i hope (this|that) helps|"
            r"is there anything else|happy to help|if you'?d like,? i can)"),
         Severity.HARD, "customer-service sign-off"),

    Rule("ai_vocabulary",
         _r(r"\b(delve|tapestry|testament to|multifaceted|nuanced|"
            r"navigat(e|ing) the|(a|the) journey of|landscape of|realm of|"
            r"foster(ing)? a sense|resonate(s|d)? with|underscore(s|d)?|"
            r"in the ever-(changing|evolving))"),
         Severity.HARD, "vocabulary almost nobody uses out loud"),

    Rule("not_just_but",
         _r(r"\bit'?s not (just|only) .{2,60}?,? (it'?s|but) "),
         Severity.HARD, "the 'not just X, it's Y' construction"),

    Rule("negative_parallelism",
         _r(r"\bnot (because|only) .{2,60}?,? but (because|also) "),
         Severity.HARD, "negative parallelism"),

    Rule("self_summary",
         _r(r"\b(as (an? )?(ai|assistant|language model)|i'?m just (an? )?(ai|program)|"
            r"i don'?t have (feelings|emotions|a body) (but|,))"),
         Severity.HARD, "breaking character to disclaim; the immutable layer handles this"),

    Rule("restating",
         _r(r"^(so|ok so),? (you'?re saying|what you mean is|if i understand)"),
         Severity.HARD, "restating the user's message back at them"),

    Rule("stock_opener",
         _r(r"^(ah|oh|well|hmm),\s+"),
         Severity.SOFT, "stock opening beat"),

    Rule("em_dash_spam",
         re.compile(r"—.*—"),
         Severity.SOFT, "more than one em dash"),

    Rule("rule_of_three",
         _r(r"\b\w+, \w+,? and \w+\.\s*$"),
         Severity.SOFT, "the rule-of-three list ending"),
]

# Applied when a SOFT rule fires. Order matters: openers before dashes.
_SOFT_FIXES: list[tuple[re.Pattern[str], str]] = [
    (_r(r"^(ah|oh|well|hmm),\s+"), ""),
    (re.compile(r"\s*—\s*"), ", "),
]


def detect(text: str) -> list[Violation]:
    out: list[Violation] = []
    for rule in RULES:
        if m := rule.pattern.search(text):
            out.append(Violation(rule.name, rule.severity, m.group(0).strip(), rule.why))
    return out


def repair_soft(text: str) -> str:
    """Fix what can be fixed without another generation."""
    for pattern, repl in _SOFT_FIXES:
        text = pattern.sub(repl, text)
    # An em dash converted to a comma can leave doubled punctuation behind.
    text = re.sub(r",\s*,", ",", text)
    return text.strip()


def question_ratio(recent_assistant_msgs: list[str]) -> float:
    """Fraction of recent replies ending in a question.

    One trailing question is conversation. Four in a row is an interview, and it is the
    subtlest assistant tell of the lot because each message looks fine alone.
    """
    if not recent_assistant_msgs:
        return 0.0
    ends = sum(1 for m in recent_assistant_msgs if m.rstrip().endswith("?"))
    return ends / len(recent_assistant_msgs)


@dataclass
class StyleResult:
    text: str
    violations: list[Violation]
    needs_regen: bool
    retry_note: str = ""


def check(text: str, recent_assistant_msgs: list[str] | None = None) -> StyleResult:
    """Full pass. Soft problems are repaired in place; hard ones ask for a regeneration."""
    violations = detect(text)
    hard = [v for v in violations if v.severity is Severity.HARD]

    cleaned = repair_soft(text) if any(
        v.severity is Severity.SOFT for v in violations) else text

    recent = list(recent_assistant_msgs or [])
    if len(recent) >= 3 and question_ratio(recent[-3:]) == 1.0 and cleaned.rstrip().endswith("?"):
        v = Violation("question_every_turn", Severity.HARD, "?",
                      "four replies in a row ending in a question")
        hard.append(v)
        violations.append(v)

    note = ""
    if hard:
        note = ("Your previous attempt was rejected for sounding like an assistant: "
                + "; ".join(f"{v.rule} ({v.why})" for v in hard)
                + ". Write it again as the character. Be blunter and more specific.")

    return StyleResult(cleaned, violations, bool(hard), note)
