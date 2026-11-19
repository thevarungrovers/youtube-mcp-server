import pytest

import youtube
from youtube.errors import InvalidRequestError, OAuthRequiredError

from tests.helpers import client, err, ok


def _report(headers, rows):
    return ok({"columnHeaders": [{"name": h} for h in headers], "rows": rows})


def test_insights_rows_carry_share_and_failures_stay_isolated():
    c, _ = client(
        _report(("country", "views", "estimatedMinutesWatched", "averageViewDuration"), [["CA", 75, 10, 5], ["FR", 15, 2, 3]]),
        _report(("views", "shares"), [[100, 4]]),
        err(400, "badRequest", "The query is not supported"),
        oauth=True,
    )
    result = youtube.get_audience_insights(c, "2026-10-01", "2026-10-31", breakdowns=["countries", "devices"])
    assert [(r["country"], r["share_of_total"]) for r in result["countries"]] == [("CA", 0.75), ("FR", 0.15)]
    assert result["devices"]["error"].startswith("INVALID_REQUEST")


def test_insights_cards_is_a_single_row():
    c, _ = client(_report(("cardImpressions", "cardClicks"), [[8, 3]]), oauth=True)
    result = youtube.get_audience_insights(c, "2026-10-01", "2026-10-31", breakdowns=["cards"])
    assert result["cards"] == {"cardImpressions": 8, "cardClicks": 3}


def test_insights_filters_combine_with_video(monkeypatch):
    calls = []
    monkeypatch.setattr(youtube.insights, "_query", lambda *a, **kw: calls.append(kw) or [])
    c, _ = client(oauth=True)
    youtube.get_audience_insights(c, "2026-10-01", "2026-10-31", breakdowns=["embedding_sites"], video_id="v1", limit=50)
    assert calls[0]["filters"] == "insightPlaybackLocationType==EMBEDDED;video==v1"
    assert calls[0]["max_results"] == 25


def test_insights_rejects_unknown_breakdown():
    c, _ = client(oauth=True)
    with pytest.raises(InvalidRequestError, match="Unknown breakdowns"):
        youtube.get_audience_insights(c, "2026-10-01", "2026-10-31", breakdowns=["planets"])


def test_search_terms():
    c, _ = client(
        _report(("insightTrafficSourceDetail", "views", "estimatedMinutesWatched"), [["rooftop farm", 25, 21]]),
        oauth=True,
    )
    result = youtube.get_search_terms(c, "2026-10-01", "2026-10-31")
    assert result["terms"] == [{"term": "rooftop farm", "views": 25, "estimatedMinutesWatched": 21}]


@pytest.mark.parametrize("call", [
    lambda c: youtube.get_audience_insights(c, "2026-10-01", "2026-10-31"),
    lambda c: youtube.get_search_terms(c, "2026-10-01", "2026-10-31"),
])
def test_insights_need_oauth(call):
    c, _ = client()
    with pytest.raises(OAuthRequiredError):
        call(c)
