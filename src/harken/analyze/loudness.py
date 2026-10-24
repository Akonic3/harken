"""Loudness score — how far a mention travelled, not just that it exists.

One lone complaint and a viral post should not weigh the same. Each mention gets
a transparent weight:

    points   = likes*1 + helpful*2 + comments*2 + shares*3 + views*0.01
    loudness = recency * (1 + log2(1 + points))

* A mention with no reported engagement scores 1.0 (it still counts once).
* The log keeps one huge post from drowning everything else: 10 points ~ 4.5,
  100 ~ 7.7, 1,000 ~ 11.
* ``recency`` halves every 365 days, never below 0.25, so an old post still counts
  but a fresh one matters more.

Bands: quiet < 2, noticed 2-4, loud 4-7, viral 7+. Engagement is only what the
source reports (YouTube search results, for example, report none), so the score
is a relative guide inside one report, not an absolute measure of reach.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from harken.models import Mention

WEIGHTS = {"likes": 1.0, "helpful": 2.0, "comments": 2.0, "shares": 3.0, "views": 0.01}
HALF_LIFE_DAYS = 365.0
RECENCY_FLOOR = 0.25
OTHER_THEME = "Other / unclassified"


def engagement_points(mention: Mention) -> float:
    counts = mention.engagement or {}
    return sum(WEIGHTS[key] * counts.get(key, 0) for key in WEIGHTS)


def loudness(mention: Mention, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    age_days = max((now - mention.created_at).total_seconds() / 86400.0, 0.0)
    recency = max(0.5 ** (age_days / HALF_LIFE_DAYS), RECENCY_FLOOR)
    return round(recency * (1.0 + math.log2(1.0 + engagement_points(mention))), 2)


def band(value: float) -> str:
    if value >= 7:
        return "viral"
    if value >= 4:
        return "loud"
    if value >= 2:
        return "noticed"
    return "quiet"


def rank_issues(mentions: list[Mention], now: datetime | None = None) -> list[dict]:
    """Group negative mentions by topic and rank topics by total loudness."""
    now = now or datetime.now(timezone.utc)
    groups: dict[str, list[tuple[float, Mention]]] = {}
    for mention in mentions:
        if mention.sentiment is None or mention.sentiment.value != "negative":
            continue
        groups.setdefault(mention.theme or OTHER_THEME, []).append(
            (loudness(mention, now), mention)
        )
    issues = []
    for theme, rows in groups.items():
        rows.sort(key=lambda row: (-row[0], -row[1].created_at.timestamp()))
        issues.append(
            {
                "theme": theme,
                "count": len(rows),
                "loudness": round(sum(value for value, _ in rows), 1),
                "peak": rows[0][0],
                "top": rows[0][1],
            }
        )
    issues.sort(key=lambda i: (-i["loudness"], -i["count"], i["theme"]))
    return issues
