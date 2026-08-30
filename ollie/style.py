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
from difflib import SequenceMatcher
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

    # Roleplay-tuned models narrate themselves. Nothing in the prompts asks for this, and a
    # person texting does not write their own stage directions. Soft because deleting the
    # aside leaves a sentence that is still the character's, so it is not worth a
    # regeneration. The alternation is kept tight on purpose: a parenthetical is usually a
    # real aside, and "*a title in italics*" must survive.
    Rule("stage_direction",
         _r(r"\(\s*(?:a\s+)?(?:long|brief|short|slight)?\s*"
            r"(?:pause[sd]?|beat|silence|sigh[s]?|laugh(?:s|ing)?|shrug[s]?|"
            r"smile[s]?|smiling|grin[s]?|nod(?:s|ding)?|exhales?|inhales?)\s*\)"
            r"|\*\s*(?:pause[sd]?|beat|sigh[s]?|laugh[s]?|shrug[s]?|smile[s]?|"
            r"grin[s]?|nod[s]?|exhales?|inhales?)\s*\*"),
         Severity.SOFT, "narrating itself with a stage direction"),

    Rule("em_dash_spam",
         re.compile(r"—.*—"),
         Severity.SOFT, "more than one em dash"),

    Rule("rule_of_three",
         _r(r"\b\w+, \w+,? and \w+\.\s*$"),
         Severity.SOFT, "the rule-of-three list ending"),

    # --- patterns that only show up on larger models -------------------------------
    #
    # The rules above were tuned against a 3B model. A 14B is more fluent, which mostly
    # means it is better at sounding like a well-trained assistant: it formats, it
    # structures, it performs curiosity, and it gives advice nobody asked for. None of
    # these appeared often enough on the small model to be worth a rule; all of them are
    # near-certain on a large one.

    Rule("markdown_formatting",
         re.compile(r"(^|\n)\s*(#{1,6}\s|[-*+]\s+\S|\d+\.\s+\S)|\*\*\S"),
         Severity.HARD,
         "bullet points, headers or bold in a chat message; people texting do not format"),

    Rule("performed_curiosity",
         _r(r"\b(i'?m (curious|wondering)(,| about| what| how| if)|"
            r"can i ask you something|if you don'?t mind me asking|"
            r"i'?d love to (hear|know) more)"),
         Severity.HARD, "curiosity announced instead of shown"),

    Rule("unrequested_advice",
         _r(r"\b(have you (considered|thought about|tried)|it might be worth|"
            r"one thing to keep in mind|what (i'?d|i would) suggest|"
            r"a good (first )?step (would be|is)|my advice would be)"),
         Severity.HARD, "advice nobody asked for, in the register of a self-help book"),

    Rule("validation_opener",
         _r(r"\b(it'?s (completely |totally |perfectly )?(understandable|natural|normal|"
            r"valid) (that|to)|you'?re not alone in|there'?s nothing wrong with feeling|"
            r"that'?s a lot to (carry|hold|deal with))"),
         Severity.HARD, "pre-emptive validation; the character reacts, it does not soothe"),

    Rule("reflective_listening",
         _r(r"\b(what i'?m hearing is|if i'?m understanding (you )?correctly|"
            r"let me make sure i understand|so what you'?re telling me)"),
         Severity.HARD, "counselling-textbook reflection"),

    # The trailing comma is load-bearing. Without it this fires on "that said nothing to
    # me", which is the character being blunt rather than the model writing an essay.
    Rule("essay_connectives",
         _r(r"(^|\n)\s*(with that (being )?said,|that said,|first and foremost|"
            r"more importantly,|on a deeper level|in many ways,|ultimately,)"),
         Severity.HARD, "essay scaffolding in a text message"),

    # No \b after the alternation: "remember," ends on punctuation, and a word boundary
    # cannot exist between a comma and a space, so requiring one matched nothing.
    Rule("aphorism_close",
         _r(r"\b(remember(,| that)|at the end of the day|the (important|main) thing is|"
            r"what matters (most )?is)[^.?!]{0,80}[.?!]\s*$"),
         Severity.HARD, "closing on a fridge magnet"),

    Rule("emoji",
         re.compile(
             "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"),
         Severity.SOFT, "emoji; the character types in words"),
]

# Applied when a SOFT rule fires. Order matters: stage directions first, because removing
# one can expose a stock opener behind it; then openers, then dashes.
_SOFT_FIXES: list[tuple[re.Pattern[str], str]] = [
    (next(r.pattern for r in RULES if r.name == "stage_direction"), ""),
    (_r(r"^(ah|oh|well|hmm),\s+"), ""),
    (re.compile(r"\s*—\s*"), ", "),
    (re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF"
                "\U0001F1E6-\U0001F1FF]"), ""),
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
    # An em dash converted to a comma can leave doubled punctuation behind, and a removed
    # stage direction leaves the space that was on either side of it.
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,.!?])", r"\1", text)
    return text.strip()


# How much of a reply may match a recent one before it counts as reciting rather than
# holding a position. Set from observed behaviour: a 14B model asked to hold a line
# reproduced its previous answer at well over 90%, while genuinely restating an argument in
# new words lands far below this.
REPETITION_THRESHOLD = 0.75
# Only paragraphs are judged. Conversational lines recur naturally — "right. and what
# happens when she says no." is a normal thing to land on twice — and the observed failure
# was a forty-five word answer reproduced whole, so the bar sits above any single beat.
_MIN_WORDS_FOR_REPETITION = 20

_WORDS = re.compile(r"[a-z0-9']+")


def repetition_ratio(text: str, recent: list[str]) -> float:
    """How close this reply is to the nearest recent one, 0 to 1.

    Short replies are exempt, and that exemption is the important half. "hm.", "go on
    then." and a character's verbal tics are *supposed* to recur — a filter that punished
    them would flatten exactly the voice this module exists to protect.

    What this catches is the failure that looks like the product working: pushed to hold a
    position, the model restates its last answer word for word instead of finding another
    way to say it. Holding the line is the thesis. Reciting it is the model giving up on
    the turn, and it reads as broken.
    """
    words = _WORDS.findall(text.lower())
    if len(words) < _MIN_WORDS_FOR_REPETITION:
        return 0.0
    best = 0.0
    for prior in recent:
        prior_words = _WORDS.findall(prior.lower())
        if len(prior_words) < _MIN_WORDS_FOR_REPETITION:
            continue
        best = max(best, SequenceMatcher(None, words, prior_words).ratio())
    return best


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

    if recent and (ratio := repetition_ratio(cleaned, recent)) >= REPETITION_THRESHOLD:
        v = Violation("self_repetition", Severity.HARD, f"{ratio:.0%} the same",
                      "repeating a previous reply almost word for word; hold the position "
                      "but find another way to say it")
        hard.append(v)
        violations.append(v)

    note = ""
    if hard:
        note = ("Your previous attempt was rejected for sounding like an assistant: "
                + "; ".join(f"{v.rule} ({v.why})" for v in hard)
                + ". Write it again as the character. Be blunter and more specific.")

    return StyleResult(cleaned, violations, bool(hard), note)
