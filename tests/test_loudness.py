"""Loudness score, engagement storage/migration, source mapping and report ranking."""

import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import respx
from fastapi.testclient import TestClient

from harken.analyze.loudness import OTHER_THEME, band, loudness, rank_issues
from harken.models import Mention, Sentiment, clean_engagement
from harken.sources.bluesky import BlueskySource
from harken.sources.googlereviews import GoogleReviewsSource
from harken.store import Store
from harken.web.app import create_app

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def mk(text="t", *, engagement=None, days=0, sentiment=Sentiment.NEGATIVE, theme=None, url=None):
    return Mention(
        source="googlereviews",
        query="kims",
        text=text,
        url=url or f"https://x/{text}",
        created_at=NOW - timedelta(days=days),
        sentiment=sentiment,
        theme=theme,
        engagement=engagement,
    )


def test_clean_engagement_keeps_only_positive_known_counts():
    assert clean_engagement(likes="5", shares=0, junk=9, views=None, comments=-3) == {"likes": 5}
    assert clean_engagement() is None
    assert mk(engagement={"likes": 2, "bogus": 7}).engagement == {"likes": 2}


def test_loudness_is_monotonic_and_log_scaled():
    quiet = loudness(mk(), NOW)
    some = loudness(mk(engagement={"likes": 10}), NOW)
    lots = loudness(mk(engagement={"likes": 1000}), NOW)
    assert quiet == 1.0 < some < lots
    assert lots < 12  # a viral post does not drown everything
    shared = loudness(mk(engagement={"shares": 10}), NOW)
    assert shared > loudness(mk(engagement={"likes": 10}), NOW)


def test_recency_halves_per_year_with_floor():
    fresh = loudness(mk(engagement={"likes": 10}), NOW)
    year = loudness(mk(engagement={"likes": 10}, days=365), NOW)
    assert abs(year - fresh / 2) < 0.02
    assert loudness(mk(days=5000), NOW) == 0.25


def test_bands():
    assert [band(v) for v in (1.0, 2.0, 4.0, 7.0)] == ["quiet", "noticed", "loud", "viral"]


def test_rank_issues_orders_by_loudness_not_count():
    many_quiet = [mk(f"w{i}", theme="Waiting time") for i in range(3)]
    one_loud = [mk("b", theme="Billing & cost", engagement={"helpful": 200, "shares": 20})]
    unthemed = [mk("u")]
    positive = [
        mk("p", sentiment=Sentiment.POSITIVE, theme="Waiting time", engagement={"likes": 99})
    ]
    issues = rank_issues(many_quiet + one_loud + unthemed + positive, NOW)
    assert [i["theme"] for i in issues] == ["Billing & cost", "Waiting time", OTHER_THEME]
    assert issues[1]["count"] == 3  # positives are not counted as issues
    assert issues[0]["top"].text == "b"


def test_store_round_trip_and_update_preserves_missing_engagement(tmp_path):
    with Store(tmp_path / "t.db") as store:
        store.upsert([mk("a", engagement={"helpful": 4})])
        assert store.mentions()[0].engagement == {"helpful": 4}
        store.upsert([mk("a", engagement=None)])  # a source that reports none
        assert store.mentions()[0].engagement == {"helpful": 4}
        store.upsert([mk("a", engagement={"helpful": 9})])
        assert store.mentions()[0].engagement == {"helpful": 9}


def test_existing_v2_database_is_migrated_in_place(tmp_path):
    path = tmp_path / "old.db"
    with Store(path) as store:
        store.upsert([mk("keep")])
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE mentions DROP COLUMN engagement")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    with Store(path) as store:  # reopening upgrades the schema
        assert [m.text for m in store.mentions()] == ["keep"]
        store.upsert([mk("keep", engagement={"likes": 3})])
        assert store.mentions()[0].engagement == {"likes": 3}


@respx.mock
def test_googlereviews_records_helpful_votes():
    payload = {
        "data": [
            {
                "name": "KIMS",
                "reviews_data": [
                    {
                        "review_text": "bad",
                        "review_rating": 1,
                        "review_likes": 12,
                        "review_link": "https://maps/1",
                        "review_timestamp": 1_790_000_000,
                    }
                ],
            }
        ]
    }
    respx.get("https://api.app.outscraper.com/maps/reviews-v3").mock(
        return_value=httpx.Response(200, json=payload)
    )
    src = GoogleReviewsSource(api_key="k", places={"a": "b"}, lowest_reviews=0)
    assert src.fetch("a")[0].engagement == {"helpful": 12}


@respx.mock
def test_bluesky_records_likes_reposts_replies():
    respx.get(url__regex=r"https://api\.bsky\.app/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "posts": [
                    {
                        "uri": "at://did/app.bsky.feed.post/abc",
                        "author": {"handle": "a.bsky.social"},
                        "record": {"text": "kims", "createdAt": "2026-10-01T00:00:00Z"},
                        "likeCount": 5,
                        "repostCount": 2,
                        "quoteCount": 1,
                        "replyCount": 4,
                    }
                ]
            },
        )
    )
    mention = BlueskySource().fetch("kims")[0]
    assert mention.engagement == {"likes": 5, "shares": 3, "comments": 4}


def test_report_ranks_issues_and_negatives_by_loudness(tmp_path):
    path = tmp_path / "r.db"
    now = datetime.now(timezone.utc)
    quiet = Mention(
        source="googlereviews",
        query="kims",
        text="quiet complaint",
        url="https://q",
        created_at=now,
        sentiment=Sentiment.NEGATIVE,
        theme="Waiting time",
    )
    loud = Mention(
        source="googlereviews",
        query="kims",
        text="loud complaint",
        url="https://l",
        created_at=now - timedelta(days=30),
        sentiment=Sentiment.NEGATIVE,
        theme="Billing & cost",
        engagement={"helpful": 150, "shares": 10},
    )
    with Store(path) as store:
        store.upsert([quiet, loud])
    html = TestClient(create_app(str(path))).get("/report?p=1&title=KIMS").text
    assert "Biggest issues, ranked by loudness" in html
    assert html.index("loud complaint") < html.index("quiet complaint")
    assert html.index("Billing &amp; cost") < html.index("Waiting time")
    assert "150 helpful" in html
    assert "not what share of patients are unhappy" in html  # sample-bias note for Google reviews
