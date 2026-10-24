"""Reddit source via its OAuth Data API.

Reddit no longer reliably permits anonymous JSON search and its current terms
require authorized access information. Configure an app client or provide an
existing bearer token; source failures remain isolated by the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from harken.models import Mention, clean_engagement
from harken.sources.base import FetchPage, Source

_API = "https://oauth.reddit.com/search"
_TOKEN_API = "https://www.reddit.com/api/v1/access_token"


class RedditSource(Source):
    name = "reddit"
    label = "Reddit"
    needs_config = True

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_token: str | None = None,
        **options,
    ):
        super().__init__(**options)
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token

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
        params = {"q": query, "limit": min(limit, 100), "sort": "new", "type": "link"}
        if cursor:
            params["after"] = cursor
        with self._client() as client:
            # Cache the minted app token on the instance so a multi-page
            # backfill (same source object across pages) does not POST the
            # rate-limited token endpoint once per page.
            if not self.access_token:
                self.access_token = self._app_token(client)
            client.headers["Authorization"] = f"Bearer {self.access_token}"
            resp = client.get(_API, params=params)
            resp.raise_for_status()
            data = resp.json()

        mentions: list[Mention] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            ts = d.get("created_utc")
            created = (
                datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
            )
            permalink = d.get("permalink")
            mentions.append(
                Mention(
                    source=self.name,
                    query=query,
                    author=d.get("author"),
                    title=d.get("title") or None,
                    text=d.get("selftext") or "",
                    url=f"https://www.reddit.com{permalink}" if permalink else d.get("url"),
                    created_at=created,
                    score=d.get("score"),
                    engagement=clean_engagement(
                        likes=d.get("score"), comments=d.get("num_comments")
                    ),
                )
            )
        return FetchPage(mentions, data.get("data", {}).get("after"))

    def _app_token(self, client) -> str:
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "Reddit requires OAuth. Set HARKEN_REDDIT_CLIENT_ID and "
                "HARKEN_REDDIT_CLIENT_SECRET, or HARKEN_REDDIT_ACCESS_TOKEN."
            )
        resp = client.post(
            _TOKEN_API,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError("Reddit OAuth response did not contain an access token")
        return token
