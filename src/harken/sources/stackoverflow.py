"""Stack Overflow questions via the public Stack Exchange API."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from harken.models import Mention, clean_engagement
from harken.sources.base import FetchPage, Source, strip_html

_API = "https://api.stackexchange.com/2.3/search/advanced"


class StackOverflowSource(Source):
    name = "stackoverflow"
    label = "Stack Overflow"
    needs_config = False

    # Backoff and anonymous daily quota apply to the calling process, even though
    # Pipeline creates a fresh source object for each scan.
    _backoff_until = 0.0
    _quota_remaining: int | None = None

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
        remaining = self._backoff_until - time.monotonic()
        if remaining > 0:
            raise RuntimeError(f"Stack Exchange API requested backoff ({remaining:.0f}s remaining)")
        if self._quota_remaining == 0:
            raise RuntimeError("Stack Exchange API daily quota is exhausted")

        params = {
            "site": "stackoverflow",
            "q": query,
            "pagesize": min(limit, 100),
            "sort": "creation",
            "order": "desc",
            "filter": "withbody",
        }
        if cursor:
            params["todate"] = int(cursor)
        if since:
            params["fromdate"] = int(since.timestamp())
        with self._client() as client:
            response = client.get(_API, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("backoff"):
            type(self)._backoff_until = time.monotonic() + max(int(data["backoff"]), 0)
        if "quota_remaining" in data:
            type(self)._quota_remaining = max(int(data["quota_remaining"]), 0)

        mentions: list[Mention] = []
        for question in data.get("items", []):
            owner = question.get("owner") or {}
            created = _created_at(question.get("creation_date"))
            question_id = question.get("question_id")
            body = strip_html(question.get("body", ""))
            mentions.append(
                Mention(
                    source=self.name,
                    query=query,
                    author=strip_html(owner.get("display_name", "")) or None,
                    title=strip_html(question.get("title", "")) or None,
                    text=_matching_excerpt(body, query),
                    url=question.get("link")
                    or (
                        f"https://stackoverflow.com/questions/{question_id}"
                        if question_id
                        else None
                    ),
                    created_at=created,
                    score=question.get("score"),
                    engagement=clean_engagement(
                        likes=question.get("score"),
                        comments=question.get("answer_count"),
                        views=question.get("view_count"),
                    ),
                )
            )
        timestamps = [
            int(item["creation_date"])
            for item in data.get("items", [])
            if item.get("creation_date") is not None
        ]
        # `todate` is inclusive; cursor at the page's oldest second (not min-1)
        # re-includes questions that share that second but overflowed the page
        # cap. The store de-duplicates the overlap; the pipeline's bounded page
        # loop prevents a stall when a whole page shares one second.
        next_cursor = str(min(timestamps)) if data.get("has_more") and timestamps else None
        return FetchPage(mentions, next_cursor)


def _created_at(value) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


def _matching_excerpt(text: str, query: str, limit: int = 800) -> str:
    """Keep the matched term visible instead of storing an entire long question."""
    if len(text) <= limit:
        return text
    index = text.casefold().find(query.casefold())
    start = max(0, index - 140) if index >= 0 else 0
    end = min(len(text), start + limit)
    excerpt = text[start:end].strip()
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")
