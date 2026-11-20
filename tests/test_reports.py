from datetime import date

import pytest

import youtube
from youtube.errors import InvalidRequestError
from youtube.reports import _previous, period_dates

TODAY = date(2026, 11, 19)  # a Thursday


@pytest.mark.parametrize(("period", "expected"), [
    ("last_7_days", ("2026-11-11", "2026-11-17")),
    ("last_28_days", ("2026-10-21", "2026-11-17")),
    ("last_week", ("2026-11-09", "2026-11-15")),
    ("last_month", ("2026-10-01", "2026-10-31")),
])
def test_period_dates(period, expected):
    assert period_dates(period, today=TODAY) == expected


def test_unknown_period():
    with pytest.raises(InvalidRequestError):
        period_dates("yesterday", today=TODAY)


def test_previous_period():
    assert _previous("2026-11-09", "2026-11-15") == ("2026-11-02", "2026-11-08")
    assert _previous("2026-03-01", "2026-03-31") == ("2026-02-01", "2026-02-28")


def _fake_analytics(monkeypatch, rows_by_call):
    calls = iter(rows_by_call)
    monkeypatch.setattr(youtube.reports, "_query", lambda *a, **kw: next(calls))


def test_detect_anomalies(monkeypatch):
    # 28 baseline days of 100 views, then 3 checked days: normal, spike, drop with subscriber loss.
    days = [date.fromordinal(date(2026, 10, 18).toordinal() + i) for i in range(31)]
    rows = [{"day": d.isoformat(), "views": 100, "subscribersGained": 0, "subscribersLost": 0} for d in days]
    rows[-2]["views"] = 250
    rows[-1].update(views=40, subscribersLost=4)
    _fake_analytics(monkeypatch, [rows])
    from tests.helpers import client

    c, _ = client(oauth=True)
    result = youtube.detect_anomalies(c, days=3, baseline_days=28, today=TODAY)
    assert result["checked"] == {"start": "2026-11-15", "end": "2026-11-17"}
    assert [(a["day"], a["kind"]) for a in result["anomalies"]] == [("2026-11-16", "spike"), ("2026-11-17", "drop")]
    assert result["subscriber_alerts"][0]["net_subscribers"] == -4


def test_render_markdown_handles_failed_sections():
    report = {
        "period": {"start": "2026-11-09", "end": "2026-11-15"},
        "previous_period": {"start": "2026-11-02", "end": "2026-11-08"},
        "totals": {"views": 1200, "estimatedMinutesWatched": 600, "averageViewDuration": 90, "likes": 10, "comments": 1, "shares": 2},
        "change": {"views": 0.2, "estimatedMinutesWatched": None, "averageViewDuration": -0.1, "likes": 0, "comments": 0, "shares": 1.0},
        "net_subscribers": -2,
        "previous_net_subscribers": 3,
        "top_videos": [{"rank": 1, "title": "Rooftop tour", "url": "u", "views": 500, "main_traffic_source": "YT_SEARCH"}],
        "audience": {"error": "INVALID_REQUEST: nope"},
        "search_terms": [{"term": "greenhouse", "views": 9}],
    }
    text = youtube.render_markdown(report)
    assert "| Views | 1,200 | +20% |" in text and "| Watch time (hours) | 10 | n/a |" in text
    assert "| Net subscribers | -2 | was +3 |" in text
    assert "mostly from YT_SEARCH" in text and "_Unavailable: INVALID_REQUEST" in text
    assert "greenhouse (9)" in text

