"""A scripted stand-in for the model, so the whole product can be walked at full speed.

This is not a mock backend. Everything else is real: the real prompts get assembled, the
real memory extraction runs, the real style filter rejects and regenerates, the real
retrieval hits the real book index. Only the thing that takes five minutes on an 8 GB
Intel laptop is replaced.

Two things it does on purpose rather than by accident:

- One chat reply is written to sound like an assistant. The style filter catches it, asks
  for a rewrite, and the second reply lands. That is the product's central mechanism, and
  a demo where it never fires does not show it.
- The replies push back, get bored, and refuse things, because a scripted model that is
  agreeable would misrepresent what the real one is instructed to do.

Start with `python -m ollie serve --demo`.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass

from .ollama import ModelInfo

# A short pause so the typing indicator appears. Instant replies read as canned; this is
# roughly what a small model on good hardware feels like.
LATENCY_SECONDS = 0.45

INTERVIEW_QUESTIONS = [
    "when was the last time you were the difficult one. not the wronged one, the difficult one.",
    "what do you do in the twenty minutes after someone says something that stings.",
    "name something you wanted badly and then talked yourself out of wanting. what was the story you told.",
    "who gets the version of you that you would not want recorded, and what makes them different.",
    "if this goes well and you get bored in four months, which part of you does the getting bored.",
]

# Reactions before the next question, so it reads as a conversation rather than a battery.
INTERVIEW_REACTIONS = [
    "hm. ok.",
    "that's a more honest answer than most people give.",
    "right, that tracks.",
    "you went around that one a bit. noted.",
]

TRAITS = {
    "dimensions": [
        {"name": "anxious_attachment", "score": 0.68, "confidence": 0.8,
         "evidence": "reread the message four times before sending it"},
        {"name": "ambition", "score": 0.74, "confidence": 0.75,
         "evidence": "keeps a list of things to finish by thirty"},
        {"name": "insecurity", "score": 0.61, "confidence": 0.7,
         "evidence": "assumed they had already decided and were being polite"},
        {"name": "conflict_avoidance", "score": 0.66, "confidence": 0.72,
         "evidence": "said it was fine. it wasn't fine."},
        {"name": "self_awareness", "score": 0.71, "confidence": 0.8,
         "evidence": "knows they do this and does it anyway"},
        {"name": "emotional_expressiveness", "score": 0.38, "confidence": 0.6,
         "evidence": "described the feeling in the third person"},
    ],
    "dodges": ["what they would do if it went badly"],
    "contradictions": [
        "said they were fine about it, then said they had reread the message four times"
    ],
    "texture": [
        "keeps a list of things to finish by thirty",
        "hates being given a pep talk",
        "notices when someone is being polite at them",
    ],
}

CANDIDATES = {
    "candidates": [
        {
            "display_name": "Ilya", "adult_age": 33, "pronouns": "he/him",
            "archetype": "match",
            "background": ("Restores field recordings for a small archive. Grew up between "
                           "Rotterdam and Ankara and switches language mid-sentence when "
                           "he is excited, which he does not notice."),
            "stable_traits": ["intense", "funny", "bad at small talk",
                              "will not let a vague answer go"],
            "values": ["craft", "loyalty", "saying the true thing"],
            "special_interest": ("the exact moment a live recording catches the room "
                                 "instead of the band"),
            "tics": ["trails off with 'anyway.'", "says 'right,' before landing a point",
                     "lowercase when calm, capitals when not"],
            "pushback_style": ("argues immediately and enjoys it, then checks he has not "
                               "gone too far"),
            "chemistry_reasons": ["takes your ambition seriously instead of soothing it",
                                  "will not let you dismiss yourself in passing"],
            "friction_points": ["pushes on the thing you were hoping to leave alone",
                                "reads your politeness as evasion, because it usually is"],
            "boundaries": ["will not be spoken to with contempt",
                           "will not pretend to agree to end an argument"],
        },
        {
            "display_name": "Wren", "adult_age": 29, "pronouns": "they/them",
            "archetype": "match",
            "background": ("Repairs analogue synthesisers in a basement in Noord. Talks "
                           "slowly, thinks faster than they talk, and finds most questions "
                           "badly posed."),
            "stable_traits": ["precise", "dry", "slow to warm", "hard to offend"],
            "values": ["accuracy", "solitude", "doing one thing properly"],
            "special_interest": ("why nobody agrees on what a Moog filter actually does to "
                                 "the low end"),
            "tics": ["long pauses written as '...'", "asks 'was that a joke' sincerely"],
            "pushback_style": "gets precise and slightly cold, which is worse than shouting",
            "chemistry_reasons": ["never fills a silence to make you comfortable",
                                  "takes what you say literally, which is restful"],
            "friction_points": ["misses sarcasm and then over-corrects for a day",
                               "will not reassure you on request"],
            "boundaries": ["will not do the emotional work for both of you"],
        },
        {
            "display_name": "Mira", "adult_age": 31, "pronouns": "she/her",
            "archetype": "match",
            "background": ("Cartographer for a flood-modelling group. Argues about coffee "
                           "with the confidence of someone who has read too much about it."),
            "stable_traits": ["blunt", "curious", "restless", "allergic to vagueness"],
            "values": ["competence", "honesty", "being left alone sometimes"],
            "special_interest": "why every Turkish coffee recipe lies about grind size",
            "tics": ["says 'ok but' before disagreeing", "repeats a word she likes"],
            "pushback_style": "goes quiet, then comes back to it twenty minutes later",
            "chemistry_reasons": ["reads what you avoid without making a thing of it",
                                  "matches your pace instead of managing it"],
            "friction_points": ["reads reassurance as condescension",
                               "goes cold when she feels handled"],
            "boundaries": ["will not be managed"],
        },
    ]
}

# Keyed on what the user is likely to say. First match wins; anything unmatched falls
# through to the pool below.
KEYED_REPLIES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\b(nervous|anxious|dreading|scared|worried)\b", re.I), [
        "dreading it since when. this week, or since you applied.",
        "ok. what's the worst version in your head. say the actual sentence.",
    ]),
    (re.compile(r"\b(sister|brother|mum|mother|dad|father|family)\b", re.I), [
        "you mention her a lot for someone who says it's not a big thing.",
        "and does she know that, or is it one of the things you've decided not to say.",
    ]),
    (re.compile(r"\b(interview|job|application|applied|work)\b", re.I), [
        "right. and you applied anyway, so some part of you disagrees with the modest version.",
        "what's the job. or is that the bit you're avoiding.",
    ]),
    # Deliberately wrong, so the character has something to disagree with.
    (re.compile(r"\b(always|never|everyone|nobody|just try harder|obviously)\b", re.I), [
        "no. that's the kind of thing people say when they've stopped looking at the actual case.",
        "ok but that's not true and I think you know it isn't.",
    ]),
    (re.compile(r"\b(fine|okay|ok|nothing|whatever)\s*[.!]?$", re.I), [
        "that's the third 'fine' in a row. I'm not going to pretend I believe it.",
        "hm.",
    ]),
    (re.compile(r"\b(sorry|apolog)", re.I), [
        "you don't have to apologise to me for having a mood. anyway.",
    ]),
    (re.compile(r"\b(coffee|grind|espresso)\b", re.I), [
        "ok so the thing nobody says is that grind size is doing about eighty percent of "
        "the work and every recipe writes it as a footnote. you get a coarse grind and "
        "then people blame the beans, or the water, or the pot. it's the grind. it's "
        "always the grind.\n\n...that was a lot of words about salt-adjacent trivia. anyway.",
    ]),
    (re.compile(r"\b(love|miss you|need you|only you)\b", re.I), [
        "that's a big thing to say on a third date. I'm not saying don't, I'm saying I "
        "noticed.",
    ]),
]

POOL = [
    "go on.",
    "hm. say more about the second part.",
    "right. and what happened after that.",
    "I can't tell if that was a joke. genuinely asking, not being annoying.",
    "you're doing the thing where you ask me what you've already decided.",
    "ok but that's the tidy version. what's the other one.",
    "no, I don't think that's it.",
    "that's the first thing you've said tonight that sounded like you.",
    "I'm still thinking about the tuesday thing, for the record.",
    "fine. change the subject then.",
]

# Fired once per session, on the second turn. The style filter catches it, names the rule,
# and the retry produces the line after it. That mechanism is the product; a demo where it
# never fires is a demo of something else.
PLANTED_ASSISTANT_ISM = (
    "I'm here for you. That sounds really hard, and it's completely understandable that "
    "you feel that way."
)
PLANTED_REWRITE = "that's rubbish. what did they actually say to you."


@dataclass
class _Session:
    turns: int = 0
    planted: bool = False


class MockOllama:
    """Same surface as `ollie.ollama.Ollama`, scripted instead of inferring."""

    def __init__(self, latency: float = LATENCY_SECONDS, seed: int = 4) -> None:
        self.latency = latency
        self.rng = random.Random(seed)
        self.state = _Session()
        self._interview_index = 0
        self._recent: list[str] = []

    async def aclose(self) -> None:
        return None

    async def alive(self) -> bool:
        return True

    async def version(self) -> str:
        return "mock"

    async def tags(self) -> list[ModelInfo]:
        return [ModelInfo("demo:scripted", 0, "mock")]

    async def _pause(self, factor: float = 1.0) -> None:
        await asyncio.sleep(self.latency * factor)

    # -- generation ------------------------------------------------------------------

    async def chat(self, model, messages, *, temperature=0.85, num_ctx=4096,
                   schema=None, stop=None, think=False) -> str:
        await self._pause()
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""

        # The retry after a rejected reply carries the rule name in the last user turn.
        if "rejected" in user.lower() or "write it again" in user.lower():
            return PLANTED_REWRITE

        if "running the short conversation" in system:
            return self._interview_turn()

        return self._reply(user)

    def _interview_turn(self) -> str:
        i = self._interview_index
        self._interview_index += 1
        question = INTERVIEW_QUESTIONS[min(i, len(INTERVIEW_QUESTIONS) - 1)]
        if i == 0:
            return question
        return f"{INTERVIEW_REACTIONS[(i - 1) % len(INTERVIEW_REACTIONS)]}\n\n{question}"

    def _reply(self, user_text: str) -> str:
        self.state.turns += 1

        if self.state.turns == 2 and not self.state.planted:
            self.state.planted = True
            return PLANTED_ASSISTANT_ISM

        for pattern, options in KEYED_REPLIES:
            if pattern.search(user_text):
                return self._fresh(options)
        return self._fresh(POOL)

    def _fresh(self, options: list[str]) -> str:
        """Avoid repeating a line the user has just seen; repetition reads as broken."""
        unused = [o for o in options if o not in self._recent] or options
        choice = self.rng.choice(unused)
        self._recent = (self._recent + [choice])[-6:]
        return choice

    # -- structured output ------------------------------------------------------------

    async def chat_json(self, model, messages, schema, num_ctx=4096) -> dict | None:
        await self._pause(1.6)
        required = set(schema.get("required", []))

        if "candidates" in required:
            return CANDIDATES
        if "dimensions" in required:
            return TRAITS
        if "memories" in required:
            return self._memory(messages)
        if "recent_summary" in required:
            return self._capsule()
        return None

    def _memory(self, messages: list[dict]) -> dict:
        """Extract from what the user actually typed, so the memory panel reflects the
        real conversation rather than a fixed script."""
        text = messages[-1]["content"] if messages else ""
        user_lines = re.findall(r"\[(msg_[0-9a-f]+)\] user: (.+)", text)
        if not user_lines:
            return {"memories": [], "open_threads": [], "state_delta": {}}

        mid, said = user_lines[-1]
        said = said.strip()
        value = said if len(said) <= 90 else said[:87] + "..."

        return {
            "memories": [{
                "kind": "user_fact", "subject": "user", "predicate": "said",
                "value": value, "confidence": 0.9, "importance": 3,
                "sensitivity": "normal", "source_message_ids": [mid],
            }],
            "open_threads": [],
            "state_delta": {
                "warmth": round(self.rng.uniform(0.0, 0.05), 3),
                "trust": round(self.rng.uniform(-0.01, 0.05), 3),
                "emotional_depth": round(self.rng.uniform(0.0, 0.04), 3),
                "playfulness": round(self.rng.uniform(-0.03, 0.04), 3),
            },
        }

    def _capsule(self) -> dict:
        return {
            "recent_summary": (
                "They talked about the interview on Thursday and admitted the "
                "underqualified feeling is a habit rather than a fact. We left it on a "
                "joke about pep talks, and they did not answer the question about what "
                "happens if it goes badly."),
            "unresolved_tension": "they still have not said what happens if it goes badly",
            "open_threads": ["find out how the Thursday interview went",
                             "the question they dodged"],
            "shared_moments": ["the pep talk in the car",
                               "them saying they'd be found out"],
            "carried_tics": ["trails off with 'anyway.'",
                             "says 'right,' before landing a point"],
            "excluded": [],
        }
