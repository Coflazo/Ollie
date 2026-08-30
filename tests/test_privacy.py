"""Identifier detection, redaction, and the risk estimate.

The risk tests are the interesting ones. It is easy to build a privacy score that looks
reassuring and points at the wrong thing; these pin the intended meaning, which is that
risk comes from what survives redaction rather than from what redaction caught.
"""

from __future__ import annotations

import pytest

from ollie import privacy


# ------------------------------------------------------------------------ detection


@pytest.mark.parametrize("text,kind", [
    ("write to me at cagan.test@example.com", "email"),
    ("see https://example.com/private/thing", "url"),
    ("my iban is NL91ABNA0417164300", "iban"),
    ("the server is at 192.168.1.44", "ipv4"),
    ("card 4111 1111 1111 1111", "card"),
    ("i live at 1018 LL", "postcode_nl"),
    ("meet at 52.3702,4.8952", "coordinates"),
    ("born 12/04/1996", "date_exact"),
    ("i'm 29 by the way", "age_exact"),
    ("find me @cagan.oflazoglu online", "handle"),
])
def test_each_identifier_kind_is_found(text: str, kind: str) -> None:
    assert kind in {s.kind for s in privacy.scan(text)}, text


def test_scan_never_mutates_the_input() -> None:
    text = "mail me at a@b.co"
    before = text
    privacy.scan(text)
    assert text == before


def test_spans_do_not_overlap() -> None:
    """The first pattern to claim a region wins, so IBAN beats a generic digit run."""
    spans = privacy.scan("NL91ABNA0417164300 and a@b.co and 192.168.1.1")
    for a, b in zip(spans, spans[1:]):
        assert a.end <= b.start, (a, b)


def test_ordinary_prose_is_left_alone() -> None:
    text = "i finally sent that application i was nervous about"
    assert privacy.scan(text) == []


# ----------------------------------------------------------------------- redaction


def test_the_same_value_gets_the_same_token() -> None:
    """A conversation has to still read as a conversation after redaction."""
    text = "email a@b.co then follow up on a@b.co again"
    clean, _spans = privacy.redact(text)
    assert clean.count("[EMAIL_1]") == 2
    assert "a@b.co" not in clean


def test_different_values_get_different_tokens() -> None:
    clean, _ = privacy.redact("a@b.co and c@d.co")
    assert "[EMAIL_1]" in clean and "[EMAIL_2]" in clean


def test_names_are_replaced_case_insensitively() -> None:
    clean, _ = privacy.redact("Deniz drove me. deniz was late.", ["Deniz"])
    assert "eniz" not in clean


def test_redaction_preserves_surrounding_text() -> None:
    clean, _ = privacy.redact("call me on 06 12345678 tomorrow please")
    assert clean.startswith("call me on") and clean.endswith("tomorrow please")


# --------------------------------------------------------------------------- risk


def test_removed_identifiers_do_not_count_as_residual_risk() -> None:
    """The point of the whole pipeline. An email that has been replaced with a token is
    the system working, not a reason to warn the user."""
    text = "mail me at a@b.co or on 06 12345678 or at c@d.co"
    _clean, spans = privacy.redact(text)
    risk = privacy.linkability(text, spans)
    assert risk["level"] == "low"
    assert risk["removed_direct"].get("email") == 2


def test_surviving_quasi_identifiers_drive_the_risk() -> None:
    """None of these are redacted, and together they narrow the field sharply."""
    text = ("i studied at University Amsterdam, i'm Turkish, and i work as a surgeon")
    risk = privacy.linkability(text, [])
    assert risk["level"] in {"medium", "high"}
    assert len(risk["quasi_identifiers"]) >= 2


def test_more_distinct_categories_beat_more_repetition() -> None:
    """Three mentions of one university identify no better than one mention."""
    repeated = privacy.linkability(
        "University Amsterdam University Amsterdam University Amsterdam", [])
    varied = privacy.linkability(
        "University Amsterdam, i'm Dutch, i work as a pilot", [])
    assert varied["score"] > repeated["score"]


def test_risk_never_claims_anonymity() -> None:
    note = privacy.linkability("anything", [])["note"].lower()
    assert "pseudonymised" in note and "not anonymous" in note


def test_clean_text_scores_low() -> None:
    assert privacy.linkability("we talked about the weather", [])["level"] == "low"


def test_score_is_bounded() -> None:
    text = " ".join(["University Amsterdam i'm Turkish PhD works at Philips"] * 20)
    assert 0.0 <= privacy.linkability(text, [])["score"] <= 1.0


def test_linkability_does_not_rescan() -> None:
    """It must use the spans it was given. Rescanning cost 25ms per export for nothing,
    and would reintroduce counting removed identifiers as risk."""
    calls = {"n": 0}
    real_scan = privacy.scan

    def counting_scan(text: str):
        calls["n"] += 1
        return real_scan(text)

    privacy.scan = counting_scan  # type: ignore[assignment]
    try:
        privacy.linkability("mail a@b.co from University Amsterdam", [])
    finally:
        privacy.scan = real_scan  # type: ignore[assignment]
    assert calls["n"] == 0
