"""Hospital comparison — the same numbers, side by side.

Two kinds of numbers appear, and they must not be confused:

* Place-level (rating, total reviews, star split, growth) come from the review
  site itself and cover *every* review, so they compare fairly between hospitals.
* Sample-level (top issue) come from the reviews Harken collected: the newest
  plus the lowest-rated. They show what people complain about, not how many.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from harken.analyze.loudness import rank_issues
from harken.store import Store


def compare_hospitals(store: Store, queries: list[str], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for query in queries:
        snapshots = store.place_snapshots(query)
        latest = snapshots[-1] if snapshots else None
        first = snapshots[0] if snapshots else None
        issues = rank_issues(store.mentions(query=query, limit=None), now)

        low_share = None
        if latest and latest["per_score"]:
            rated = sum(latest["per_score"].values())
            if rated:
                low = sum(latest["per_score"][star] for star in (1, 2, 3))
                low_share = round(100.0 * low / rated, 1)

        growth = growth_days = None
        if latest and first and latest["total"] is not None and first["total"] is not None:
            elapsed = (latest["captured_at"] - first["captured_at"]).total_seconds() / 86400.0
            if elapsed >= 1:
                growth, growth_days = latest["total"] - first["total"], round(elapsed)

        rows.append(
            {
                "query": query,
                "report_url": f"/report?q={quote(query)}",
                "rating": latest["rating"] if latest else None,
                "total": latest["total"] if latest else None,
                "low_share": low_share,
                "growth": growth,
                "growth_days": growth_days,
                "top_issue": issues[0]["theme"] if issues else None,
                "issues": [i["theme"] for i in issues[:3]],
                "sample": sum(i["count"] for i in issues),
            }
        )
    return rows
