"""Core data models for Harken.

Everything flowing through the pipeline is normalised into a :class:`Mention`.
Sources produce them, analyzers annotate them, the store persists them, and the
web dashboard renders them.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, field_validator

ENGAGEMENT_KEYS = ("likes", "shares", "comments", "views", "helpful")


def clean_engagement(**counts) -> dict[str, int] | None:
    """Keep only known, positive whole-number engagement counts (else None)."""
    cleaned: dict[str, int] = {}
    for key in ENGAGEMENT_KEYS:
        try:
            value = int(counts.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            cleaned[key] = value
    return cleaned or None


class Sentiment(str, Enum):
    """Coarse sentiment label. Kept deliberately small — useful, not precise."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Mention(BaseModel):
    """A single thing someone said, somewhere, that matched a tracked query.

    ``id`` is a stable content hash so the same item fetched twice (or by two
    overlapping queries) de-duplicates cleanly in the store.
    """

    id: str = ""
    source: str  # e.g. "hackernews", "reddit", "mastodon"
    query: str  # the tracked term this mention matched
    author: str | None = None
    title: str | None = None
    text: str = ""
    url: str | None = None
    created_at: datetime
    score: int | None = None  # upvotes / points / favourites, source-dependent
    #: how far the item travelled, where the source reports it:
    #: likes, shares, comments, views, helpful (e.g. Google "helpful" votes)
    engagement: dict[str, int] | None = None

    # Populated by analyzers (None until analysed).
    sentiment: Sentiment | None = None
    sentiment_score: float | None = None  # signed, roughly [-1, 1]
    theme: str | None = None

    @field_validator("created_at")
    @classmethod
    def _ensure_tz_aware(cls, value: datetime) -> datetime:
        """Treat a tz-naive source timestamp as UTC.

        Some source APIs (or non-conformant federated servers) return
        offset-less timestamps. Left naive, they later blow up when compared
        against an aware ``datetime`` (alert bucketing) or get silently shifted
        by the host's local offset when normalised for cursor bounds. Anchoring
        them to UTC here keeps every ``created_at`` aware and comparable.
        """
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator("engagement")
    @classmethod
    def _clean_engagement(cls, value: dict | None) -> dict[str, int] | None:
        return clean_engagement(**value) if value else None

    def model_post_init(self, __context) -> None:  # noqa: D401
        if not self.id:
            self.id = self.compute_id()

    @property
    def content(self) -> str:
        """Title + body, the text analyzers actually read."""
        parts = [p for p in (self.title, self.text) if p]
        return "\n".join(parts).strip()

    def compute_id(self) -> str:
        basis = self.url or f"{self.source}:{self.author}:{self.content[:200]}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
