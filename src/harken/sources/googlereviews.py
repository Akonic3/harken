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

from harken.models import Mention
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
        **options,
    ):
        super().__init__(**options)
        self.api_key = api_key
        self.places = {k.casefold(): v for k, v in (places or {}).items()}
        self.max_reviews = max_reviews

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

        params: dict[str, str | int] = {
            "query": place,
            "reviewsLimit": self.max_reviews,
            "sort": "newest",
            "async": "false",
        }
        if since:
            params["cutoff"] = int(since.timestamp())

        # The key travels in a header so it never appears in URLs or error text.
        with self._client(headers={"X-API-KEY": self.api_key}, timeout=120.0) as client:
            response = client.get(_API, params=params)
            response.raise_for_status()
            body = response.json()
            for _ in range(_POLL_ATTEMPTS):
                location = body.get("results_location")
                if body.get("status") != "Pending" or not location:
                    break
                time.sleep(_POLL_SECONDS)
                poll = client.get(location)
                poll.raise_for_status()
                body = poll.json()
            else:
                if body.get("status") == "Pending":
                    raise RuntimeError("Google Reviews request still pending; try again later")

        return FetchPage(_parse(body, query, place))


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
                )
            )
    return mentions


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
