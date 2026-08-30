"""Type inference and partner matching.

The matching weights come from *Gifts Differing*: shared perception (S/N) is the
preference Myers treats as most load-bearing for two people understanding each other,
while judging and lifestyle differences are workable and often complementary. These tests
pin that reading, so a later tweak to the weights cannot quietly turn it into something
else.
"""

from __future__ import annotations

import pytest

from ollie import types16


def test_there_are_sixteen_of_them() -> None:
    assert len(types16.TYPES) == 16
    assert len(set(types16.TYPES)) == 16
    assert all(len(t) == 4 for t in types16.TYPES)


def test_every_type_has_a_description_and_a_failure_mode() -> None:
    for code in types16.TYPES:
        assert types16.DESCRIPTIONS[code]
        assert types16.FRICTION[code], f"{code} has no friction point"


# ------------------------------------------------------------------------ inference


def test_inference_reads_the_axes_in_the_expected_direction() -> None:
    code, _conf = types16.infer_type(
        {"extraversion": 0.9, "openness": 0.9, "agreeableness": 0.9,
         "conscientiousness": 0.9},
        {"novelty_seeking": 0.9, "emotional_expressiveness": 0.9,
         "need_for_control": 0.9})
    assert code == "ENFJ"

    code, _conf = types16.infer_type(
        {"extraversion": 0.1, "openness": 0.1, "agreeableness": 0.1,
         "conscientiousness": 0.1},
        {"novelty_seeking": 0.1, "emotional_expressiveness": 0.1,
         "need_for_control": 0.1})
    assert code == "ISTP"


def test_inference_reports_low_confidence_when_there_is_no_signal() -> None:
    """Everything at the midpoint means we genuinely could not tell, and must say so."""
    _code, confidence = types16.infer_type(
        {k: 0.5 for k in ("extraversion", "openness", "agreeableness",
                          "conscientiousness")},
        {k: 0.5 for k in ("novelty_seeking", "emotional_expressiveness",
                          "need_for_control")})
    assert all(c == 0.0 for c in confidence.values())


def test_inference_always_produces_a_real_type() -> None:
    assert types16.infer_type({}, {})[0] in types16.TYPES


# ------------------------------------------------------------------------- matching


def test_shared_perception_outweighs_everything_else() -> None:
    """The core Gifts Differing claim: same S/N beats matching on the other three."""
    same_sn_only = types16.score_pair("INFP", "ESTJ".replace("S", "N"))  # ENTJ
    different_sn_all_else_same = types16.score_pair("INFP", "ISFP")
    assert same_sn_only.score > different_sn_all_else_same.score


def test_best_match_always_shares_the_perception_axis() -> None:
    for user in types16.TYPES:
        best = types16.rank_matches(user, limit=1)[0]
        assert best.type_code[1] == user[1], (
            f"{user} was matched to {best.type_code}, which perceives differently")


def test_matching_prefers_complementary_judging() -> None:
    """Same perception, opposite T/F should beat same perception, same T/F."""
    complement = types16.score_pair("INFP", "INTP")
    identical = types16.score_pair("INFP", "INFP")
    assert complement.score > identical.score


def test_ranking_is_deterministic() -> None:
    assert [m.type_code for m in types16.rank_matches("ENTP")] == \
        [m.type_code for m in types16.rank_matches("ENTP")]


def test_ranking_returns_the_requested_number() -> None:
    assert len(types16.rank_matches("INFJ", limit=3)) == 3
    assert len(types16.rank_matches("INFJ", limit=16)) == 16


def test_reason_is_human_readable_and_mentions_the_perception_axis() -> None:
    match = types16.rank_matches("INFJ", limit=1)[0]
    assert "Myers" in match.reason
    assert len(match.reason) > 40


@pytest.mark.parametrize("bad", ["", "XXXX", "infp!", None, "INF"])
def test_invalid_types_are_rejected_and_do_not_crash_ranking(bad) -> None:
    assert not types16.valid(bad)
    assert len(types16.rank_matches(bad, limit=3)) == 3  # falls back, does not raise


def test_lowercase_input_is_accepted() -> None:
    assert types16.valid("infp")
    assert types16.score_pair("infp", "entj").type_code == "ENTJ"


def test_no_type_matches_itself_best() -> None:
    """A dating simulator that pairs everyone with a clone is not simulating dating."""
    for user in types16.TYPES:
        assert types16.rank_matches(user, limit=1)[0].type_code != user
