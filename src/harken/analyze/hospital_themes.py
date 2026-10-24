"""Hospital topic tagging — a transparent keyword taxonomy for patient feedback.

Patients write in English, Telugu script, romanised Telugu and Hinglish, often
mixed in one sentence. Each topic below lists terms in those forms. A mention
gets the topic with the most term hits (ties go to the earlier topic). This is
a starting vocabulary meant to be tuned on real KIMS Saveera data; unmatched
mentions simply get no topic rather than a guess.
"""

from __future__ import annotations

import re

from harken.models import Mention

TOPICS: dict[str, tuple[str, ...]] = {
    "Waiting time": (
        "waiting",
        "waited",
        "wait time",
        "delay",
        "delayed",
        "long queue",
        "queue",
        "hours",
        "late",
        "slow",
        "time waste",
        "aalasyam",
        "alasyam",
        "intha time",
        "ఆలస్యం",
        "వెయిటింగ్",
        "గంటలు",
        "క్యూ",
    ),
    "Billing & cost": (
        "bill",
        "billing",
        "charges",
        "charged",
        "cost",
        "costly",
        "expensive",
        "overcharge",
        "fees",
        "fee",
        "payment",
        "insurance",
        "refund",
        "deposit",
        "rates",
        "paisa",
        "paise",
        "ఖర్చు",
        "బిల్లు",
        "ఫీజు",
        "డబ్బులు",
        "ఇన్సూరెన్స్",
    ),
    "Staff behaviour": (
        "staff",
        "nurse",
        "nurses",
        "rude",
        "behaviour",
        "behavior",
        "attitude",
        "polite",
        "courteous",
        "reception",
        "helpful",
        "ignored",
        "shouted",
        "misbehave",
        "samjhaya",
        "సిబ్బంది",
        "నర్సు",
        "ప్రవర్తన",
        "మర్యాద",
    ),
    "Doctor communication": (
        "doctor",
        "doctors",
        "dr.",
        "explained",
        "explain",
        "counselling",
        "counseling",
        "listened",
        "consultation",
        "diagnosis",
        "surgeon",
        "specialist",
        "samjhaya",
        "డాక్టర్",
        "వైద్యులు",
        "వైద్యుడు",
        "వివరించారు",
    ),
    "Cleanliness & facilities": (
        "clean",
        "cleanliness",
        "hygiene",
        "dirty",
        "washroom",
        "toilet",
        "parking",
        "ac ",
        "room",
        "ward",
        "bed",
        "food",
        "canteen",
        "lift",
        "facilities",
        "smell",
        "శుభ్రత",
        "పరిశుభ్రత",
        "గది",
        "టాయిలెట్",
    ),
    "Emergency & ICU": (
        "emergency",
        "icu",
        "ambulance",
        "casualty",
        "critical",
        "accident",
        "ventilator",
        "ఎమర్జెన్సీ",
        "అంబులెన్స్",
        "ఐసీయూ",
    ),
    "Treatment outcome": (
        "recovered",
        "recovery",
        "cured",
        "surgery",
        "operation",
        "successful",
        "treatment",
        "complication",
        "infection",
        "died",
        "death",
        "negligence",
        "wrong treatment",
        "misdiagnosed",
        "delivery",
        "baby",
        "ఆపరేషన్",
        "చికిత్స",
        "ట్రీట్మెంట్",
        "డెలివరీ",
    ),
}

_ASCII = re.compile(r"^[a-z0-9 .]+$")


def _hits(text: str, terms: tuple[str, ...]) -> int:
    count = 0
    for term in terms:
        if _ASCII.match(term):
            count += len(re.findall(rf"(?<![a-z0-9]){re.escape(term.strip())}(?![a-z0-9])", text))
        else:  # Telugu script has no spaces/case: plain substring match
            count += text.count(term)
    return count


def classify(text: str) -> str | None:
    """Return the best-matching hospital topic for ``text`` or None."""
    lowered = (text or "").lower()
    best, best_hits = None, 0
    for topic, terms in TOPICS.items():
        hits = _hits(lowered, terms)
        if hits > best_hits:
            best, best_hits = topic, hits
    return best


def apply_topics(mentions: list[Mention]) -> int:
    """Set ``mention.theme`` from the taxonomy in place; return how many matched."""
    matched = 0
    for mention in mentions:
        mention.theme = classify(mention.content)
        matched += mention.theme is not None
    return matched
