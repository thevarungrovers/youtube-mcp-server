import pytest

import youtube
from youtube.benchmark import _summarize
from youtube.errors import InvalidRequestError

from tests.helpers import client, err


def _video(views, likes, comments, published, seconds, title="t"):
    return {"view_count": views, "like_count": likes, "comment_count": comments, "published_at": published,
            "duration_seconds": seconds, "title": title, "url": "u"}


def test_summarize_recent_uploads():
    videos = [
        _video(1000, 90, 10, "2026-11-10T00:00:00Z", 60, "short"),
        _video(300, 10, 5, "2026-11-03T00:00:00Z", 600),
        _video(500, 20, 5, "2026-10-27T00:00:00Z", 900),
    ]
    s = _summarize(videos)
    assert s["median_views"] == 500 and s["average_views"] == 600
    assert s["engagement_rate"] == 0.05  # median of 0.1, 0.05, 0.05
    assert s["days_between_uploads"] == 7.0 and s["latest_upload"] == "2026-11-10T00:00:00Z"
    assert s["short_share"] == 0.33 and s["top_recent_video"]["title"] == "short"


def test_summarize_no_videos():
    assert _summarize([])["median_views"] is None


def test_compare_isolates_a_failing_channel():
    c, _ = client(err(404, "channelNotFound"))
    result = youtube.compare_channels(c, ["@missing"])
    assert result["channels"][0]["error"].startswith("NOT_FOUND")


def test_compare_limits():
    c, _ = client()
    with pytest.raises(InvalidRequestError, match="at most"):
        youtube.compare_channels(c, [f"@c{i}" for i in range(11)])
    with pytest.raises(InvalidRequestError, match="at least one"):
        youtube.compare_channels(c, [" "])


def test_trending_validates_region():
    c, _ = client()
    with pytest.raises(InvalidRequestError, match="region_code"):
        youtube.get_trending_videos(c, region_code="Canada")
