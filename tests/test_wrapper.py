import pytest

import youtube
from youtube._utils import parse_duration, to_rfc3339
from youtube.channels import channel_selector
from youtube.errors import AuthError, InvalidRequestError, NotFoundError, OAuthRequiredError, QuotaExceededError

from tests.helpers import client, err, ok

CHANNEL_ID = "UC" + "x" * 22


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("PT1H2M3S", 3723), ("PT45S", 45), ("P1DT1M", 86460), ("P0D", 0), ("junk", None), (None, None)],
)
def test_parse_duration(value, seconds):
    assert parse_duration(value) == seconds


def test_to_rfc3339_end_of_day_is_inclusive():
    assert to_rfc3339("2025-01-31", end_of_day=True) == "2025-02-01T00:00:00Z"
    with pytest.raises(InvalidRequestError):
        to_rfc3339("31/01/2025")


def test_get_channel_info_by_handle():
    c, _ = client(
        ok({"items": [{"id": CHANNEL_ID, "snippet": {"title": "Example Channel"},
                       "statistics": {"subscriberCount": "10", "videoCount": "2", "viewCount": "99"},
                       "contentDetails": {"relatedPlaylists": {"uploads": "UU" + "x" * 22}}}]})
    )
    info = youtube.get_channel_info(c, "@example")
    assert info["subscriber_count"] == 10 and info["view_count"] == 99


@pytest.mark.parametrize(
    ("channel", "selector"),
    [(CHANNEL_ID, {"id": CHANNEL_ID}), ("@example", {"forHandle": "@example"}), ("example", {"forHandle": "@example"})],
)
def test_channel_selector(channel, selector):
    c, _ = client()
    assert channel_selector(c, channel) == selector


def test_channel_selector_defaults_to_mine_with_oauth():
    c, _ = client(oauth=True)
    assert channel_selector(c, None) == {"mine": True}


def test_channel_required_with_api_key_only():
    c, _ = client()
    with pytest.raises(InvalidRequestError, match="YOUTUBE_CHANNEL_ID"):
        youtube.get_channel_info(c)


def test_default_channel_from_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", CHANNEL_ID)
    c, _ = client(ok({"items": [{"id": CHANNEL_ID, "snippet": {}, "statistics": {"hiddenSubscriberCount": True}}]}))
    info = youtube.get_channel_info(c)
    assert info["id"] == CHANNEL_ID and info["subscriber_count"] is None


def test_video_details_reports_not_found():
    c, _ = client(
        ok({"items": [{"id": "a", "snippet": {"title": "A", "tags": ["t"]},
                       "statistics": {"viewCount": "5", "likeCount": "1"},
                       "contentDetails": {"duration": "PT1M"}}]})
    )
    result = youtube.get_video_details(c, "a, b")
    assert [v["id"] for v in result["videos"]] == ["a"]
    assert result["videos"][0]["duration_seconds"] == 60
    assert result["not_found"] == ["b"]


def test_video_statistics_batches_by_50():
    ids = [f"v{i}" for i in range(120)]
    pages = [ok({"items": [{"id": i, "statistics": {"viewCount": "1"}} for i in ids[n:n + 50]]}) for n in (0, 50, 100)]
    c, _ = client(*pages)
    result = youtube.get_video_statistics(c, ids)
    assert len(result["statistics"]) == 120 and result["not_found"] == []


def test_list_channel_videos_uses_uploads_playlist():
    c, _ = client(
        ok({"items": [{"id": CHANNEL_ID, "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}]}),
        ok({"items": [{"snippet": {"title": "V", "position": 0}, "contentDetails": {"videoId": "v1"}}],
            "nextPageToken": "NEXT", "pageInfo": {"totalResults": 7}}),
        ok({"items": [{"id": "v1", "statistics": {"viewCount": "3"}, "contentDetails": {"duration": "PT10S"}}]}),
    )
    result = youtube.list_channel_videos(c, CHANNEL_ID, max_results=1)
    assert result["next_page_token"] == "NEXT" and result["total_results"] == 7
    assert result["videos"][0]["view_count"] == 3 and result["videos"][0]["duration_seconds"] == 10


def test_search_validates_order():
    c, _ = client()
    with pytest.raises(InvalidRequestError, match="order"):
        youtube.search_videos(c, "x", order="popular")


def test_quota_error_is_translated():
    c, _ = client(err(403, "quotaExceeded", "The request cannot be completed because you have exceeded your quota."))
    with pytest.raises(QuotaExceededError, match="resets at midnight Pacific"):
        youtube.get_video_details(c, "a")


def test_not_found_error_is_translated():
    c, _ = client(err(404, "playlistNotFound"))
    with pytest.raises(NotFoundError):
        youtube.get_playlist_items(c, "PLmissing")


def test_insufficient_scope_points_to_auth():
    c, _ = client(err(403, "insufficientPermissions"), oauth=True)
    with pytest.raises(AuthError, match="cli.py auth"):
        youtube.get_channel_analytics(c, "2025-01-01", "2025-01-31")


@pytest.mark.parametrize(
    "call",
    [
        lambda c: youtube.get_channel_analytics(c, "2025-01-01", "2025-01-31"),
        lambda c: youtube.get_video_analytics(c, "v1", "2025-01-01", "2025-01-31"),
        lambda c: youtube.get_top_videos(c, "2025-01-01", "2025-01-31"),
        lambda c: youtube.get_revenue(c, "2025-01-01", "2025-01-31"),
    ],
)
def test_analytics_refuses_without_oauth_before_any_request(call):
    c, _ = client()  # no responses queued: any request would fail the test
    with pytest.raises(OAuthRequiredError, match="cli.py auth"):
        call(c)


def _report(headers, rows):
    return ok({"columnHeaders": [{"name": h} for h in headers], "rows": rows})


def test_channel_analytics_totals_and_net_subs():
    c, _ = client(
        _report(youtube.analytics.CHANNEL_METRICS, [[100, 50, 30, 40.0, 7, 2, 5, 1, 0]]),
        oauth=True,
    )
    result = youtube.get_channel_analytics(c, "2025-01-01", "2025-01-31")
    assert result["totals"]["views"] == 100 and result["net_subscribers"] == 5


def test_analytics_rejects_reversed_dates():
    c, _ = client(oauth=True)
    with pytest.raises(InvalidRequestError, match="after"):
        youtube.get_channel_analytics(c, "2025-02-01", "2025-01-01")


def test_top_videos_adds_titles_and_ranks():
    c, _ = client(
        _report(("video", "views", "estimatedMinutesWatched", "averageViewDuration", "likes", "comments", "shares", "subscribersGained"),
                [["v1", 10, 5, 30, 1, 0, 0, 0], ["v2", 8, 4, 30, 9, 9, 9, 0]]),
        ok({"items": [{"id": "v1", "snippet": {"title": "One"}}, {"id": "v2", "snippet": {"title": "Two"}}]}),
        oauth=True,
    )
    result = youtube.get_top_videos(c, "2025-01-01", "2025-01-31", metric="views", limit=2)
    assert [(v["rank"], v["video_id"], v["title"]) for v in result["videos"]] == [(1, "v1", "One"), (2, "v2", "Two")]


def test_top_videos_engagement_reorders():
    c, _ = client(
        _report(("video", "views", "estimatedMinutesWatched", "averageViewDuration", "likes", "comments", "shares", "subscribersGained"),
                [["v1", 10, 5, 30, 1, 0, 0, 0], ["v2", 8, 4, 30, 9, 9, 9, 0]]),
        ok({"items": [{"id": "v2", "snippet": {"title": "Two"}}]}),
        oauth=True,
    )
    result = youtube.get_top_videos(c, "2025-01-01", "2025-01-31", metric="engagement", limit=1)
    assert result["videos"][0]["video_id"] == "v2" and result["videos"][0]["engagement"] == 27


def test_video_analytics_isolates_failing_section():
    c, _ = client(
        _report(("views",), [[5]]),
        err(400, "badRequest", "Unsupported query"),
        oauth=True,
    )
    result = youtube.get_video_analytics(c, "v1", "2025-01-01", "2025-01-31", sections=["summary", "demographics"])
    assert result["summary"] == {"views": 5}
    assert result["demographics"]["error"].startswith("INVALID_REQUEST")


def test_revenue_unavailable_for_unmonetized_channel():
    c, _ = client(err(403, "forbidden", "Forbidden"), oauth=True)
    result = youtube.get_revenue(c, "2025-01-01", "2025-01-31")
    assert result["available"] is False and "Partner Program" in result["reason"]


def test_monthly_rows_end_on_first_of_month_but_totals_do_not(monkeypatch):
    calls = []

    def fake_query(client, start, end, metrics, **kwargs):
        calls.append((start, end, kwargs.get("dimensions")))
        return []

    monkeypatch.setattr(youtube.analytics, "_query", fake_query)
    c, _ = client(oauth=True)
    youtube.get_channel_analytics(c, "2026-06-01", "2026-10-31", granularity="month")
    assert calls == [("2026-06-01", "2026-10-31", None), ("2026-06-01", "2026-10-01", "month")]
