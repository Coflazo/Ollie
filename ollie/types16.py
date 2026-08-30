"""The sixteen types, and how Ollie chooses which one to become.

The user's own copy of *Gifts Differing* (Isabel Briggs Myers with Peter Myers) is the
source for the matching rules below. Two things in that book drive the weights:

- Myers treats the perceptive function, sensing versus intuition, as the preference that
  most affects whether two people can understand each other at all. Partners who take in
  the world differently are describing different worlds, and she reports that sharing it
  matters more than sharing the others.
- She treats judging-function and lifestyle differences as workable, and sometimes
  valuable, because they supply what the other person lacks. Difference there is
  complementary rather than corrosive, provided the perception is shared.

So S/N is weighted for similarity far above everything else, T/F and J/P get a mild
complementarity bonus, and E/I gets a small one. This is a heuristic drawn from a book,
presented to the user as a starting point they can override — not a scientific claim, and
the UI says so.

Type is also never forced: a user who already knows their type can enter it, and a user
who does not gets an inference they can correct.
"""

from __future__ import annotations

from dataclasses import dataclass

AXES = ("EI", "SN", "TF", "JP")

TYPES: tuple[str, ...] = (
    "ISTJ", "ISFJ", "INFJ", "INTJ",
    "ISTP", "ISFP", "INFP", "INTP",
    "ESTP", "ESFP", "ENFP", "ENTP",
    "ESTJ", "ESFJ", "ENFJ", "ENTJ",
)

# One line each, written to be usable inside a character prompt rather than as a horoscope.
DESCRIPTIONS: dict[str, str] = {
    "ISTJ": "precise, dependable, remembers what was agreed and expects it kept",
    "ISFJ": "quietly attentive, notices what you need before you ask, dislikes fuss",
    "INFJ": "reads people fast, holds a private conviction about how things should be",
    "INTJ": "systems-minded, blunt about flaws, uninterested in reassurance",
    "ISTP": "practical, unbothered, solves the thing rather than discussing it",
    "ISFP": "sensory and private, shows care through doing rather than saying",
    "INFP": "idealistic, deeply particular about meaning, resists being managed",
    "INTP": "precise about ideas, follows an argument past where it was comfortable",
    "ESTP": "immediate, physical, allergic to overthinking a decision",
    "ESFP": "warm and present, pulls other people into the moment",
    "ENFP": "enthusiastic and scattered, connects things nobody asked to connect",
    "ENTP": "argues for sport, tests an idea by attacking it, hard to offend",
    "ESTJ": "organises everything, says the decision out loud, expects follow-through",
    "ESFJ": "keeps everyone fed and included, feels the room's temperature",
    "ENFJ": "draws people out, invested in who you are becoming, can over-give",
    "ENTJ": "decisive and direct, impatient with vagueness, argues to a conclusion",
}

# What each type finds hard, which is where friction with a partner actually comes from.
FRICTION: dict[str, str] = {
    "ISTJ": "reads spontaneity as unreliability",
    "ISFJ": "absorbs resentment rather than voicing it",
    "INFJ": "decides what you meant and defends the conclusion",
    "INTJ": "corrects instead of comforting",
    "ISTP": "goes silent instead of negotiating",
    "ISFP": "withdraws when pushed to explain a feeling",
    "INFP": "takes disagreement as a verdict on their values",
    "INTP": "keeps debating after the other person has stopped enjoying it",
    "ESTP": "moves on before the thing was finished",
    "ESFP": "changes the subject away from anything heavy",
    "ENFP": "starts more than they finish and takes it personally when noted",
    "ENTP": "argues a position they do not hold and forgets to say so",
    "ESTJ": "decides for both of you and calls it efficiency",
    "ESFJ": "keeps score of what they gave",
    "ENFJ": "manages you instead of just being with you",
    "ENTJ": "treats a feeling as a problem to be resolved",
}


@dataclass
class Match:
    type_code: str
    score: float
    shares: list[str]
    differs: list[str]
    reason: str


def infer_type(big_five: dict[str, float], dimensions: dict[str, float]) -> tuple[str, dict[str, float]]:
    """Estimate a four-letter type from the questionnaire and the interview.

    Returns the code plus a per-axis confidence, because an inference the user cannot see
    the strength of is an inference they cannot sensibly correct. Values near 0.5 mean
    "we genuinely could not tell", and the UI shows those as unresolved rather than
    guessing confidently.
    """
    def bf(key: str, default: float = 0.5) -> float:
        return big_five.get(key, default)

    def dim(key: str, default: float = 0.5) -> float:
        return dimensions.get(key, default)

    # Extraversion is the one axis the questionnaire measures almost directly.
    ei = bf("extraversion")

    # Intuition tracks openness, nudged by a taste for novelty over routine.
    sn = 0.7 * bf("openness") + 0.3 * dim("novelty_seeking")

    # Feeling tracks agreeableness and how openly the person expresses emotion.
    tf = 0.6 * bf("agreeableness") + 0.4 * dim("emotional_expressiveness")

    # Judging tracks conscientiousness and a need for the plan to be settled.
    jp = 0.65 * bf("conscientiousness") + 0.35 * dim("need_for_control")

    code = (
        ("E" if ei >= 0.5 else "I")
        + ("N" if sn >= 0.5 else "S")
        + ("F" if tf >= 0.5 else "T")
        + ("J" if jp >= 0.5 else "P")
    )
    # Distance from the midpoint is the confidence; 0.5 exactly means no signal.
    confidence = {axis: round(abs(v - 0.5) * 2, 3)
                  for axis, v in zip(AXES, (ei, sn, tf, jp))}
    return code, confidence


def valid(code: str) -> bool:
    return isinstance(code, str) and code.strip().upper() in TYPES


# Axis weights. The large SN number is the whole argument of this module.
_WEIGHTS = {
    "EI": (0.10, "complement"),   # some difference is restful, not decisive
    "SN": (0.50, "same"),         # Myers: shared perception is what makes understanding possible
    "TF": (0.22, "complement"),   # different judging functions supply what the other lacks
    "JP": (0.18, "complement"),   # workable difference, and often useful
}

_AXIS_LABEL = {
    "EI": ("outward energy", "inward energy"),
    "SN": ("concrete perception", "pattern perception"),
    "TF": ("decides by logic", "decides by values"),
    "JP": ("wants it settled", "wants it open"),
}


def score_pair(user: str, other: str) -> Match:
    """How well `other` suits `user`, with the reasoning kept legible."""
    user, other = user.upper(), other.upper()
    shares: list[str] = []
    differs: list[str] = []
    total = 0.0

    for i, axis in enumerate(AXES):
        same = user[i] == other[i]
        weight, prefers = _WEIGHTS[axis]
        if prefers == "same":
            total += weight if same else 0.0
        else:
            # A mild preference for difference: matching still scores, just less.
            total += weight if not same else weight * 0.55
        (shares if same else differs).append(axis)

    if user[1] == other[1]:
        why = (f"You both take the world in the same way "
               f"({_AXIS_LABEL['SN'][0] if user[1] == 'S' else _AXIS_LABEL['SN'][1]}), "
               f"which is the thing Myers thought mattered most for understanding "
               f"each other.")
    else:
        why = ("You notice different things about the same situation, which Myers "
               "flagged as the hardest difference to bridge. Interesting, but work.")

    if differs:
        names = ", ".join(_AXIS_LABEL[a][0 if other[AXES.index(a)] in "ESTJ" else 1]
                          for a in differs if a != "SN")
        if names:
            why += f" They differ from you on: {names}."

    return Match(other, round(total, 4), shares, differs, why)


def rank_matches(user_type: str, limit: int = 3) -> list[Match]:
    """Best partner types for this user, best first.

    Returns several rather than one. Declaring a single objectively correct partner would
    be both false and worse product design: the user picks.
    """
    if not valid(user_type):
        user_type = "INFP"
    ranked = sorted((score_pair(user_type, t) for t in TYPES),
                    key=lambda m: (-m.score, m.type_code))
    return ranked[:limit]


def profile(code: str) -> dict:
    code = code.upper()
    return {
        "type": code,
        "description": DESCRIPTIONS.get(code, ""),
        "friction": FRICTION.get(code, ""),
    }
