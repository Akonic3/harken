"""Place-level stats, snapshots, hospital comparison and its report section."""

import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import respx
from fastapi.testclient import TestClient

from harken.analyze.compare import compare_hospitals
from harken.config import Config
from harken.models import Mention, Sentiment
from harken.pipeline import Pipeline
from harken.sources.googlereviews import GoogleReviewsSource
from harken.store import Store
from harken.web.app import create_app

API = "https://api.app.outscraper.com/maps/reviews-v3"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SPLIT = {1: 10, 2: 10, 3: 30, 4: 50, 5: 900}


def review_payload(place_extra):
    place = {
        "name": "KIMS",
        "reviews_data": [
            {
                "review_text": "bad",
                "review_rating": 1,
                "review_link": "https://m/1",
                "review_timestamp": 1_790_000_000,
            }
        ],
        **place_extra,
    }
    return {"data": [place]}


@respx.mock
def test_googlereviews_returns_place_stats_in_either_documented_shape():
    nested = {
        "rating": 4.9,
        "reviews": 22069,
        "reviews_per_score": {"1": 10, "2": 10, "3": 30, "4": 50, "5": 900},
    }
    flat = {
        "rating": "4.8",
        "reviews": 100,
        **{f"reviews_per_score_{s}": n for s, n in SPLIT.items()},
    }
    for extra, want in ((nested, 22069), (flat, 100)):
        respx.get(API).mock(return_value=httpx.Response(200, json=review_payload(extra)))
        page = GoogleReviewsSource(api_key="k", places={"a": "b"}, lowest_reviews=0).fetch_page("a")
        assert page.place_stats["total"] == want
        assert page.place_stats["per_score"] == SPLIT or page.place_stats["per_score"][1] == 10


@respx.mock
def test_missing_or_partial_place_stats_are_not_invented():
    respx.get(API).mock(return_value=httpx.Response(200, json=review_payload({})))
    page = GoogleReviewsSource(api_key="k", places={"a": "b"}, lowest_reviews=0).fetch_page("a")
    assert page.place_stats is None
    respx.get(API).mock(
        return_value=httpx.Response(
            200, json=review_payload({"rating": 4.5, "reviews_per_score": {"1": 2}})
        )
    )
    page = GoogleReviewsSource(api_key="k", places={"a": "b"}, lowest_reviews=0).fetch_page("a")
    assert page.place_stats == {"rating": 4.5, "total": None, "per_score": None}


def test_snapshots_skip_unchanged_numbers_and_order_oldest_first(tmp_path):
    with Store(tmp_path / "s.db") as store:
        stats = {"rating": 4.9, "total": 1000, "per_score": SPLIT}
        assert store.record_place_stats("kims", "googlereviews", stats, now=T0)
        assert not store.record_place_stats(
            "kims", "googlereviews", stats, now=T0 + timedelta(days=1)
        )
        bigger = {**stats, "total": 1100}
        assert store.record_place_stats("kims", "googlereviews", bigger, now=T0 + timedelta(days=7))
        snaps = store.place_snapshots("kims")
        assert [s["total"] for s in snaps] == [1000, 1100]
        assert snaps[0]["per_score"] == SPLIT


def test_v3_database_gains_place_stats_table(tmp_path):
    path = tmp_path / "v3.db"
    with Store(path) as store:
        store.upsert([Mention(source="s", query="q", text="x", created_at=T0)])
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE place_stats")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    with Store(path) as store:
        assert store.record_place_stats("q", "googlereviews", {"rating": 4.0, "total": 5})
        assert [m.text for m in store.mentions()] == ["x"]


def test_pipeline_records_place_stats_from_a_source(tmp_path, monkeypatch):
    from harken.sources import REGISTRY
    from harken.sources.base import FetchPage

    class PlaceSource:
        label = "Place"
        needs_config = False

        def __init__(self, **options):
            pass

        def fetch_page(self, query, limit=50, *, cursor=None, since=None):
            mention = Mention(
                source="place", query=query, text="ok", url="https://p/1", created_at=T0
            )
            return FetchPage(
                [mention], place_stats={"rating": 4.7, "total": 321, "per_score": None}
            )

    monkeypatch.setitem(REGISTRY, "place", PlaceSource)
    pipe = Pipeline(Config(db_path=str(tmp_path / "p.db"), sources=["place"], source_retries=0))
    pipe.track("kims")
    assert pipe.store.place_snapshots("kims", "place")[0]["total"] == 321
    pipe.close()


def test_compare_hospitals_uses_place_numbers_and_sample_issues(tmp_path):
    now = T0 + timedelta(days=14)
    with Store(tmp_path / "c.db") as store:
        for query, total, split, theme in (
            ("kims", 1000, SPLIT, "Waiting time"),
            ("rival", 400, {1: 20, 2: 20, 3: 60, 4: 100, 5: 200}, "Billing & cost"),
        ):
            store.record_place_stats(
                query,
                "googlereviews",
                {"rating": 4.5, "total": total - 50, "per_score": split},
                now=T0,
            )
            store.record_place_stats(
                query, "googlereviews", {"rating": 4.5, "total": total, "per_score": split}, now=now
            )
            store.upsert(
                [
                    Mention(
                        source="googlereviews",
                        query=query,
                        text="bad",
                        url=f"https://{query}",
                        created_at=now,
                        sentiment=Sentiment.NEGATIVE,
                        theme=theme,
                    )
                ]
            )
        rows = {r["query"]: r for r in compare_hospitals(store, ["kims", "rival"], now)}
    assert rows["kims"]["low_share"] == 5.0  # (10+10+30) of 1000 rated reviews
    assert rows["rival"]["low_share"] == 25.0  # (20+20+60) of 400
    assert rows["kims"]["growth"] == 50 and rows["kims"]["growth_days"] == 14
    assert rows["kims"]["top_issue"] == "Waiting time"
    assert rows["rival"]["report_url"] == "/report?q=rival"


def test_report_shows_comparison_for_a_multi_hospital_project(tmp_path):
    path = tmp_path / "r.db"
    with Store(path) as store:
        for query in ("KIMS Saveera", "Rival Care"):
            store.record_place_stats(
                query, "googlereviews", {"rating": 4.6, "total": 2500, "per_score": SPLIT}
            )
            store.upsert(
                [
                    Mention(
                        source="googlereviews",
                        query=query,
                        text=f"{query} slow",
                        url=f"https://{query}",
                        created_at=datetime.now(timezone.utc),
                        sentiment=Sentiment.NEGATIVE,
                    )
                ]
            )
        project = store.create_project("Anantapur hospitals")
        for query in ("KIMS Saveera", "Rival Care"):
            store.add_query_to_project(project["id"], query)
    html = TestClient(create_app(str(path))).get(f"/report?p={project['id']}").text
    assert "How the hospitals compare" in html
    assert "2,500" in html and "4.6" in html and "5.0%" in html
    assert "/report?q=Rival%20Care" in html
    assert "open a hospital&#39;s own report" in html or "open a hospital's own report" in html


def test_report_without_any_place_numbers_hides_the_comparison(tmp_path):
    path = tmp_path / "n.db"
    with Store(path) as store:
        store.upsert(
            [
                Mention(
                    source="s", query="solo", text="x", created_at=T0, sentiment=Sentiment.NEGATIVE
                )
            ]
        )
    html = TestClient(create_app(str(path))).get("/report?q=solo").text
    assert "How the hospitals compare" not in html
