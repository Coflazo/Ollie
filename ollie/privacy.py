"""Finding identifiers in text, and being honest about what that does and does not achieve.

This is the reference implementation. `native/ollie_native.cpp` mirrors it and
`tests/test_native_parity.py` asserts the two agree, because a safety scanner that behaves
differently depending on whether a shared library loaded is worse than no scanner.

An important limit, stated here because it also has to be stated in the UI: removing
direct identifiers produces *pseudonymised* text, not anonymous text. A romantic or
sexual conversation carries GDPR Article 9 special-category data, and the combination of
a rare job, a specific city and an exact age can single a person out with every name
already stripped. Nothing in this file should ever be described as anonymisation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: str
    text: str


# Order is precedence: the first pattern to claim a region wins, and later patterns cannot
# overlap it. Specific beats general, which matters most among the numeric patterns.
#
# `phone` is deliberately last of those. It is the loosest rule here, matching two or three
# runs of digits with almost any separator, so placed earlier it swallows card numbers,
# coordinates and dates and reports them all as phone numbers. They still get redacted
# either way, but the user is told the wrong thing about their own data, and a risk report
# that miscounts what it found is not worth much.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")),
    ("url", re.compile(r"https?://[^\s)>\]]+")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("coordinates", re.compile(r"-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}")),
    ("card", re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("date_exact", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),
    ("postcode_uk", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")),
    ("postcode_nl", re.compile(r"\b\d{4}\s?[A-Z]{2}\b")),
    ("handle", re.compile(r"(?<![\w@])@[A-Za-z][\w.]{2,29}\b")),
    ("age_exact", re.compile(r"\b(?:I'?m|I am|aged)\s+([2-9]\d)\b", re.I)),
    ("phone", re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?"
                         r"\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,4}(?![\w.])")),
]

# Quasi-identifiers. These are not redacted automatically, because stripping every
# mention of a university would gut the text; they are counted and reported, because a
# rare combination of them re-identifies someone that names alone would not.
QUASI = [
    ("institution", re.compile(r"\b(?:university|universiteit|college|hogeschool|"
                               r"institute|academy)\s+(?:of\s+)?[A-Z]\w+", re.I)),
    ("employer", re.compile(r"\b(?:work(?:s|ed|ing)?\s+(?:at|for)|employed\s+by)\s+"
                            r"[A-Z]\w+", re.I)),
    ("nationality", re.compile(r"\b(?:Turkish|Dutch|German|French|Italian|Polish|"
                               r"Spanish|Greek|Moroccan|Surinamese|Indonesian)\b")),
    ("rare_role", re.compile(r"\b(?:PhD|doctorate|professor|surgeon|pilot|"
                             r"diplomat|olympian|paralympic)\b", re.I)),
]


def scan(text: str) -> list[Span]:
    """Byte-accurate identifier spans. Never mutates the input."""
    claimed: list[Span] = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(start < s.end and end > s.start for s in claimed):
                continue  # already covered by a more specific pattern
            claimed.append(Span(start, end, kind, m.group(0)))
    claimed.sort(key=lambda s: s.start)
    return claimed


def scan_quasi(text: str) -> list[Span]:
    out: list[Span] = []
    for kind, pattern in QUASI:
        for m in pattern.finditer(text):
            out.append(Span(m.start(), m.end(), kind, m.group(0)))
    return sorted(out, key=lambda s: s.start)


def redact(text: str, extra_names: list[str] | None = None) -> tuple[str, list[Span]]:
    """Replace identifiers with stable placeholders.

    The same value gets the same token throughout, so `[PERSON_1]` stays one person and
    the conversation still reads as a conversation.
    """
    spans = scan(text)
    counters: dict[str, dict[str, str]] = {}

    def token(kind: str, value: str) -> str:
        bucket = counters.setdefault(kind, {})
        if value.lower() not in bucket:
            bucket[value.lower()] = f"[{kind.upper()}_{len(bucket) + 1}]"
        return bucket[value.lower()]

    out: list[str] = []
    cursor = 0
    for s in spans:
        out.append(text[cursor:s.start])
        out.append(token(s.kind, s.text))
        cursor = s.end
    out.append(text[cursor:])
    result = "".join(out)

    # Names come from profile metadata rather than a model guess, so they are exact.
    for i, name in enumerate(sorted(extra_names or [], key=len, reverse=True), start=1):
        if len(name) < 2:
            continue
        pattern = re.compile(rf"\b{re.escape(name)}\b", re.I)
        if pattern.search(result):
            result = pattern.sub(f"[PERSON_{i}]", result)
            spans.append(Span(-1, -1, "name", name))

    return result, spans


def linkability(text: str, spans: list[Span]) -> dict:
    """How identifiable the text remains *after* the direct identifiers are removed.

    Two corrections to the obvious version of this.

    It no longer rescans. The caller has already run the expensive pass and hands the
    spans in; doing it twice cost 25ms per export on a 400-turn transcript for nothing.

    More importantly, the risk is driven by what survives redaction, not by what was
    caught. An email address that has been replaced with a token is not residual risk, it
    is the pipeline working. What actually re-identifies someone is the combination of
    things redaction does not touch: a named university, a rare job, a nationality, an
    exact age. Counting removed identifiers as risk both inflated the score and pointed
    the user at the wrong thing to worry about.
    """
    quasi = scan_quasi(text)
    kinds = {q.kind for q in quasi}

    # Distinct categories matter more than repetition: three mentions of the same
    # university identify no better than one, but a university plus a nationality plus a
    # rare role narrows the field sharply.
    score = min(1.0, 0.25 * len(kinds) + 0.05 * max(0, len(quasi) - len(kinds)))
    level = "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"

    removed: dict[str, int] = {}
    for s in spans:
        removed[s.kind] = removed.get(s.kind, 0) + 1

    return {
        "score": round(score, 2),
        "level": level,
        "quasi_identifiers": [{"kind": q.kind, "text": q.text} for q in quasi[:12]],
        "removed_direct": removed,
        "note": ("Removing names produces pseudonymised text, not anonymous text. "
                 "The risk above is what survives redaction: a rare combination of job, "
                 "place and age can still identify someone with every name stripped."),
    }
