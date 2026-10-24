"""Google Reviews source, hospital topics and star-rating sentiment — HTTP mocked."""

from datetime import datetime, timezone

import httpx
import pytest
import respx

from harken.analyze.hospital_themes import apply_topics, classify
from harken.config import Config
from harken.models import Mention, Sentiment
from harken.pipeline import _apply_star_ratings
from harken.sources.googlereviews import GoogleReviewsSource

API = "https://api.app.outscraper.com/maps/reviews-v3"
PAYLOAD = {
    "status": "Success",
    "data": [
        {
            "name": "KIMS Saveera Hospital",
            "reviews_data": [
                {
                    "review_id": "r1",
                    "author_title": "Ravi",
                    "review_text": "Waited 2 hours, nobody gave an update",
                    "review_rating": 2,
                    "review_datetime_utc": "09/14/2026 10:30:00",
                    "review_link": "https://maps.google.com/?cid=1&r=1",
                },
                {
                    "review_id": "r2",
                    "author_title": "Lakshmi",
                    "review_text": "",
                    "review_rating": 5,
                    "review_timestamp": 1_790_000_000,
                    "review_link": "https://maps.google.com/?cid=1&r=2",
                },
                {"review_id": "r3", "review_text": "", "review_rating": None},
            ],
        }
    ],
}


@respx.mock
def test_fetches_mapped_keyword_and_parses_reviews():
    route = respx.get(API).mock(return_value=httpx.Response(200, json=PAYLOAD))
    src = GoogleReviewsSource(api_key="k", places={"KIMS Saveera": "KIMS Saveera Anantapur"})
    out = src.fetch("kims saveera")  # keyword match is case-insensitive
    assert [m.score for m in out] == [2, 5]  # empty, unrated review is skipped
    assert out[0].source == "googlereviews" and out[0].author == "Ravi"
    assert out[0].created_at == datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc)
    assert out[1].text == "(rating only: 5/5)"
    req = route.calls.last.request
    assert req.headers["X-API-KEY"] == "k"
    assert "KIMS+Saveera+Anantapur" in str(req.url) or "KIMS%20Saveera%20Anantapur" in str(req.url)
    assert "k" not in req.url.params.get("query", "").split()  # key never in the URL


@respx.mock
def test_first_scan_also_pulls_lowest_rated_and_dedupes():
    route = respx.get(API).mock(return_value=httpx.Response(200, json=PAYLOAD))
    src = GoogleReviewsSource(api_key="k", places={"a": "b"}, lowest_reviews=50)
    page = src.fetch_page("a")
    sorts = [c.request.url.params["sort"] for c in route.calls]
    assert sorts == ["newest", "lowest_rating"]
    assert len(page.mentions) == 2  # same reviews returned twice are kept once


@respx.mock
def test_incremental_scan_pulls_only_newest():
    route = respx.get(API).mock(return_value=httpx.Response(200, json=PAYLOAD))
    src = GoogleReviewsSource(api_key="k", places={"a": "b"})
    src.fetch_page("a", since=datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert [c.request.url.params["sort"] for c in route.calls] == ["newest"]


@respx.mock
def test_unmapped_keyword_makes_no_request():
    route = respx.get(API).mock(return_value=httpx.Response(200, json=PAYLOAD))
    src = GoogleReviewsSource(api_key="k", places={"KIMS Saveera": "x"})
    assert src.fetch("something else") == []
    assert not route.called


@respx.mock
def test_since_becomes_cutoff_and_nested_lists_are_handled():
    route = respx.get(API).mock(return_value=httpx.Response(200, json={"data": [PAYLOAD["data"]]}))
    src = GoogleReviewsSource(api_key="k", places={"a": "b"})
    page = src.fetch_page("a", since=datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert len(page.mentions) == 2
    assert route.calls.last.request.url.params["cutoff"] == "1788220800"


def test_missing_key_is_a_clear_error():
    with pytest.raises(RuntimeError, match="HARKEN_OUTSCRAPER_API_KEY"):
        GoogleReviewsSource(places={"a": "b"}).fetch("a")


@respx.mock
def test_http_error_does_not_expose_key():
    respx.get(API).mock(return_value=httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError) as err:
        GoogleReviewsSource(api_key="do-not-leak", places={"a": "b"}).fetch("a")
    assert "do-not-leak" not in str(err.value)


def test_places_env_parsing(monkeypatch):
    monkeypatch.setenv("HARKEN_GOOGLE_PLACES", "KIMS Saveera=KIMS Saveera, Anantapur; bad;x=")
    assert Config().google_places == {"KIMS Saveera": "KIMS Saveera, Anantapur"}


@pytest.mark.parametrize(
    "text,topic",
    [
        ("Waited 3 hours, huge delay at reception queue", "Waiting time"),
        ("They overcharged us, the bill was too high", "Billing & cost"),
        ("nurses were very rude and the staff ignored us", "Staff behaviour"),
        ("డాక్టర్ గారు బాగా వివరించారు", "Doctor communication"),
        ("బిల్లు చాలా ఎక్కువ, ఖర్చు భరించలేము", "Billing & cost"),
        ("ICU and ambulance response was quick in emergency", "Emergency & ICU"),
        ("washroom was dirty and the room smell was bad", "Cleanliness & facilities"),
        ("great place", None),
    ],
)
def test_hospital_topics(text, topic):
    assert classify(text) == topic


def test_apply_topics_sets_and_clears_theme():
    def mk(text):
        return Mention(source="s", query="q", text=text, created_at=datetime.now(timezone.utc))

    ms = [mk("long delay"), mk("hello")]
    ms[1].theme = "stale"
    assert apply_topics(ms) == 1
    assert ms[0].theme == "Waiting time" and ms[1].theme is None


def test_star_rating_overrides_text_sentiment_only_when_clear():
    def mk(score, source="googlereviews"):
        return Mention(
            source=source,
            query="q",
            text="x",
            score=score,
            created_at=datetime.now(timezone.utc),
            sentiment=Sentiment.NEUTRAL,
        )

    five, one, three, other = mk(5), mk(1), mk(3), mk(1, source="reddit")
    _apply_star_ratings([five, one, three, other])
    assert five.sentiment is Sentiment.POSITIVE
    assert one.sentiment is Sentiment.NEGATIVE
    assert three.sentiment is Sentiment.NEUTRAL
    assert other.sentiment is Sentiment.NEUTRAL
