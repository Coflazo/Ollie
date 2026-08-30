"""Put the app into a mid-conversation state without waiting for onboarding.

Rehearsing the demo means reaching the interesting part repeatedly. Doing that through the
real flow costs five model calls for the interview plus one slow candidate generation, which
is a minute or two of dead air every single run, and it makes the memory payoff depend on
remembering to mention the right thing.

This writes the state directly: a profile, a persona, an episode with real messages, and the
memories that episode would have produced. Everything it writes goes through the same store
methods the running app uses, so nothing here is a special case the rest of the code does
not understand.

The seeded facts are chosen to set up the recall beat. `--rollover` closes the episode so
the next question about Thursday has to come from memory rather than from the visible
transcript.
"""

from __future__ import annotations

import time

from . import persona, types16
from .store import Store

# A user profile with enough shape that the character has something to react to.
PROFILE_TRAITS = {
    "anxious_attachment": 0.68,
    "ambition": 0.74,
    "insecurity": 0.61,
    "conflict_avoidance": 0.66,
    "emotional_expressiveness": 0.38,
    "self_awareness": 0.71,
}
PROFILE_EVIDENCE = {
    "anxious_attachment": "\"I reread the message about four times before sending it\"",
    "ambition": "\"I keep a list of the things I said I'd finish by thirty\"",
    "insecurity": "\"I assumed they'd already decided and were being polite\"",
    "conflict_avoidance": "\"I said it was fine. It wasn't fine.\"",
    "self_awareness": "\"I know I do this and I do it anyway\"",
}
BIG_FIVE = {"extraversion": 0.35, "agreeableness": 0.72,
            "conscientiousness": 0.78, "neuroticism": 0.64, "openness": 0.81}

# INFJ, which the matcher pairs with ENTP: shared intuition, complementary judging.
USER_TYPE = "INFJ"

TRANSCRIPT = [
    ("user", "i have that interview on thursday and i've been dreading it all week"),
    ("assistant", "thursday. ok. what's the job, or is that the part you're avoiding."),
    ("user", "research role. i'm underqualified for it honestly"),
    ("assistant", "you applied though. so some part of you disagrees with that.\n\n"
                  "what does underqualified mean here. missing a specific thing, or the "
                  "general feeling."),
    ("user", "the general feeling i guess. i keep thinking they'll realise"),
    ("assistant", "right, that one. it's not a fact about you, it's a fact about how you "
                  "read rooms.\n\nanyway. what time thursday."),
    ("user", "ten in the morning. my sister deniz is driving me there"),
    ("assistant", "good. tell her to not give you a pep talk in the car, you hate those."),
]

# Each record names the exact turns it came from, by index into TRANSCRIPT. The memory
# manager shows provenance, so a record pointing at a message that does not contain it
# undermines the one screen whose whole job is to be checkable.
#
#   kind, subject, predicate, value, confidence, importance, sensitivity, source turns
MEMORIES = [
    ("user_fact", "user", "has an interview on", "Thursday at 10am",
     0.95, 5, "normal", [0, 6]),
    ("user_fact", "user", "applied for", "a research role",
     0.95, 4, "normal", [2]),
    ("user_fact", "sister", "is called", "Deniz",
     0.95, 3, "personal", [6]),
    ("user_fact", "sister", "is driving them to", "the Thursday interview",
     0.9, 3, "personal", [6]),
    # The user never said this; the character asserted it and was not contradicted. That
    # is exactly the kind of record that should sit below the confirmation threshold, and
    # the manager labels it "inferred" so the user can correct or delete it.
    ("preference", "user", "dislikes", "pep talks before something stressful",
     0.6, 3, "normal", [7]),
    ("boundary", "user", "does not want", "reassurance that skips over the worry",
     0.9, 5, "normal", [4]),
]

THREADS = ["find out how the Thursday interview went"]

CAPSULE = {
    "persona_name": "",  # filled in below
    "recent_summary": (
        "They told me about a research job interview on Thursday at ten, and that they "
        "think they are underqualified. It turned out to be a general feeling rather than "
        "a missing skill. Their sister Deniz is driving them. We left it there, on a joke "
        "about pep talks."),
    "unresolved_tension": None,
    "open_threads": THREADS,
    "shared_moments": ["the pep talk in the car", "them saying they'd be found out"],
    "carried_tics": ["trails off with 'anyway.'", "says 'right,' before landing a point",
                     "lowercase when calm"],
    "excluded_memory_ids": [],
    "interaction_state": {"warmth": 0.58, "trust": 0.47, "playfulness": 0.61,
                          "emotional_depth": 0.44, "romantic_tension": 0.31,
                          "conflict_tension": 0.02},
}


def seed(store: Store, model_tag: str, context_cap: int, *,
         rollover: bool = False, mature: bool = False) -> dict:
    """Write a complete demo state. Returns the ids the caller needs to print."""
    settings = {
        "content_mode": "mature" if mature else "general",
        "adult_confirmed": mature,
        "intensity": "moderate",
        "languages": ["English", "Turkish"],
        "communication": "direct, and do not soften the difficult part",
    }
    profile_id = store.create_profile(settings, {"big_five": BIG_FIVE}, "Cagan")

    # An ENTP, which is what the matcher returns for an INFJ.
    match = types16.rank_matches(USER_TYPE, limit=1)[0]
    card = {
        "id": "cand_seed",
        "display_name": "Ilya",
        "adult_age": 33,
        "pronouns": "he/him",
        "archetype": "match",
        "type": match.type_code,
        "type_description": types16.DESCRIPTIONS[match.type_code],
        "match_reason": match.reason,
        "match_score": match.score,
        "background": ("Restores field recordings for a small archive. Grew up between "
                       "Rotterdam and Ankara and switches language mid-sentence when he is "
                       "excited, which he does not notice."),
        "languages": ["English", "Turkish"],
        "stable_traits": ["intense", "funny", "bad at small talk", "does not let a vague "
                          "answer go"],
        "values": ["craft", "loyalty", "saying the true thing"],
        "special_interest": ("the exact moment a live recording catches the room instead of "
                             "the band"),
        "tics": ["trails off with 'anyway.'", "says 'right,' before landing a point",
                 "lowercase when calm, capitals when not"],
        "pushback_style": "argues immediately and enjoys it, then checks he has not gone too far",
        "chemistry_reasons": ["takes your ambition seriously instead of soothing it",
                              "will not let you dismiss yourself in passing"],
        "friction_points": ["pushes on the thing you were hoping to leave alone",
                            "reads your politeness as evasion, because it usually is"],
        "boundaries": ["will not be spoken to with contempt",
                       "will not pretend to agree to end an argument"],
    }
    persona_id = store.create_persona(profile_id, card, "seed")

    state = {**persona.DEFAULT_STATE, **CAPSULE["interaction_state"],
             "stage": "third_date"}
    session_id = store.create_session(profile_id, persona_id, model_tag, context_cap,
                                      state, episode=1)

    message_ids: list[str] = []
    for role, text in TRANSCRIPT:
        message_ids.append(
            store.append_message(session_id, role, text, tokens=max(1, len(text) // 4)))

    for kind, subject, predicate, value, conf, importance, sensitivity, turns in MEMORIES:
        store.add_memory(profile_id, kind, subject, predicate, value, conf, importance,
                         sensitivity, [message_ids[t] for t in turns],
                         persona_id=persona_id,
                         requires_confirmation=conf < 0.7)

    for title in THREADS:
        store.add_thread(profile_id, session_id, title, message_ids[-1])

    result = {"profile_id": profile_id, "persona_id": persona_id,
              "session_id": session_id, "episode": 1,
              "persona_name": card["display_name"], "type": card["type"],
              "user_type": USER_TYPE}

    if rollover:
        capsule = {**CAPSULE, "persona_name": card["display_name"],
                   "source_message_range": [message_ids[0], message_ids[-1]],
                   "model_tag": model_tag}
        capsule_id = store.save_capsule(session_id, capsule)
        state2 = {**CAPSULE["interaction_state"], "stage": "third_date"}
        session2 = store.create_session(profile_id, persona_id, model_tag, context_cap,
                                        state2, episode=2)
        store.approve_capsule(capsule_id, capsule, session2)

        from .memory import capsule_to_opening_context

        opening = capsule_to_opening_context(capsule)
        store.append_message(session2, "system", opening, tokens=len(opening) // 4)
        store.db.execute("UPDATE sessions SET ended_at=? WHERE id=?",
                         (time.time(), session_id))
        store.db.commit()
        result.update({"session_id": session2, "episode": 2, "carried": opening})

    return result


def build_traits() -> persona.TraitProfile:
    """The trait profile the interview would have produced, so the candidate screen and
    the compiled prompt have the same material they would have had after a real run."""
    return persona.TraitProfile(
        big_five=BIG_FIVE,
        dimensions=PROFILE_TRAITS,
        confidence={k: 0.8 for k in PROFILE_TRAITS},
        evidence=PROFILE_EVIDENCE,
        dodges=["what they would do if they did not get it"],
        contradictions=["said they were fine about it, then said they had reread the "
                        "message four times"],
        texture=["sister called Deniz", "keeps a list of things to finish by thirty",
                 "hates pep talks"],
    )
