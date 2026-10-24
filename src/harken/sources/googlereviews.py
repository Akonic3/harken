"""Google Maps reviews for a hospital (or any place), via the Outscraper API.

Reviews are the richest public patient feedback in India, but Google's own
Places API returns only ~5 reviews per place. A review-collection API returns
the full history. Coverage and pricing belong to the provider (the first 500
reviews are free, then about $3 per 1,000); Harken only calls it when a tracked
keyword is mapped to a place, so scans of other keywords cost nothing.

Configuration (see .env.example):
    HARKEN_OUTSCRAPER_API_KEY   provider key
    HARKEN_GOOGLE_PLACES        "keyword=place search;keyword2=place search"
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from harken.models import Mention, clean_engagement
from harken.sources.base import FetchPage, Source, strip_html

_API = "https://api.app.outscraper.com/maps/reviews-v3"
_POLL_SECONDS = 5
_POLL_ATTEMPTS = 24


class GoogleReviewsSource(Source):
    name = "googlereviews"
    label = "Google Reviews"
    needs_config = True

    def __init__(
        self,
        api_key: str | None = None,
        places: dict[str, str] | None = None,
        max_reviews: int = 100,
        lowest_reviews: int = 300,
        **options,
    ):
        super().__init__(**options)
        self.api_key = api_key
        self.places = {k.casefold(): v for k, v in (places or {}).items()}
        self.max_reviews = max_reviews
        # Highly rated places (a 4.9 average is common when patients are asked to
        # review at discharge) hide their real signal in the low-star tail, so the
        # first scan also pulls the lowest-rated reviews.
        self.lowest_reviews = lowest_reviews

    def fetch(self, query: str, limit: int = 50) -> list[Mention]:
        return self.fetch_page(query, limit=limit).mentions

    def fetch_page(
        self,
        query: str,
        limit: int = 50,
        *,
        cursor: str | None = None,
        since: datetime | None = None,
    ) -> FetchPage:
        if not self.api_key:
            raise RuntimeError("Google Reviews requires HARKEN_OUTSCRAPER_API_KEY")
        place = self.places.get(query.casefold())
        if not place:
            # Not a mapped keyword: do nothing (and spend nothing).
            return FetchPage([])

        requests: list[tuple[str, int]] = [("newest", self.max_reviews)]
        if since is None and self.lowest_reviews > 0:
            requests.append(("lowest_rating", self.lowest_reviews))

        mentions: dict[str, Mention] = {}
        place_stats: dict | None = None
        # The key travels in a header so it never appears in URLs or error text.
        with self._client(headers={"X-API-KEY": self.api_key}, timeout=120.0) as client:
            for sort, count in requests:
                params: dict[str, str | int] = {
                    "query": place,
                    "reviewsLimit": count,
                    "sort": sort,
                    "async": "false",
                }
                if since:
                    params["cutoff"] = int(since.timestamp())
                body = self._call(client, params)
                place_stats = place_stats or _place_stats(body)
                for mention in _parse(body, query, place):
                    mentions.setdefault(mention.id, mention)
        return FetchPage(list(mentions.values()), place_stats=place_stats)

    def _call(self, client, params: dict) -> dict:
        response = client.get(_API, params=params)
        response.raise_for_status()
        body = response.json()
        for _ in range(_POLL_ATTEMPTS):
            location = body.get("results_location")
            if body.get("status") != "Pending" or not location:
                return body
            time.sleep(_POLL_SECONDS)
            poll = client.get(location)
            poll.raise_for_status()
            body = poll.json()
        if body.get("status") == "Pending":
            raise RuntimeError("Google Reviews request still pending; try again later")
        return body


def _parse(body: dict, query: str, place_query: str) -> list[Mention]:
    mentions: list[Mention] = []
    for place in _iter_places(body.get("data")):
        place_name = strip_html(place.get("name") or "") or place_query
        for review in place.get("reviews_data") or []:
            link = review.get("review_link")
            rating = _rating(review.get("review_rating"))
            text = strip_html(review.get("review_text") or "")
            if not text and rating is None:
                continue
            if not text:
                text = f"(rating only: {rating}/5)"
            mentions.append(
                Mention(
                    source="googlereviews",
                    query=query,
                    author=strip_html(review.get("author_title") or "") or None,
                    title=place_name,
                    text=text,
                    url=link or None,
                    created_at=_when(review),
                    score=rating,
                    engagement=clean_engagement(helpful=review.get("review_likes")),
                )
            )
    return mentions


def _place_stats(body: dict) -> dict | None:
    """Overall rating, review count and 1-5 star split of the place, if reported.

    Field names follow the provider's documented columns; anything missing or
    malformed is simply left out rather than guessed.
    """
    for place in _iter_places(body.get("data")):
        rating = _number(place.get("rating"))
        total = _number(place.get("reviews"))
        per_score = _per_score(place)
        if rating is None and total is None and per_score is None:
            continue
        return {
            "rating": rating,
            "total": int(total) if total is not None else None,
            "per_score": per_score,
        }
    return None


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _per_score(place: dict) -> dict[int, int] | None:
    raw = place.get("reviews_per_score")
    counts: dict[int, int] = {}
    for star in range(1, 6):
        value = None
        if isinstance(raw, dict):
            value = raw.get(str(star), raw.get(star))
        if value is None:
            value = place.get(f"reviews_per_score_{star}")
        number = _number(value)
        if number is not None:
            counts[star] = int(number)
    return counts if len(counts) == 5 else None


def _iter_places(data):
    """The API returns a list of places, or a list of lists for multi-query calls."""
    for item in data or []:
        if isinstance(item, list):
            yield from _iter_places(item)
        elif isinstance(item, dict):
            yield item


def _rating(value) -> int | None:
    try:
        rating = int(float(value))
    except (TypeError, ValueError):
        return None
    return rating if 1 <= rating <= 5 else None


def _when(review: dict) -> datetime:
    stamp = review.get("review_timestamp")
    if isinstance(stamp, (int, float)) and stamp > 0:
        return datetime.fromtimestamp(stamp, tz=timezone.utc)
    raw = review.get("review_datetime_utc")
    if isinstance(raw, str):
        for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(raw, fmt)
            except ValueError:
                continue
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)
