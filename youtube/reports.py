"""Ready-made reports and alerts built from the analytics operations.

:func:`build_report` compares a period with the one before it and adds the
top videos, audience highlights and search terms; :func:`render_markdown`
turns it into text for a chat message, an email or a doc.
:func:`detect_anomalies` flags days whose views or subscriber change stand out
from the days before them. All need OAuth.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any

from youtube._utils import date_range, parse_date
from youtube.analytics import CHANNEL_METRICS, _query, _section, get_channel_analytics, get_top_videos
from youtube.client import YouTubeClient
from youtube.errors import APIError, InvalidRequestError
from youtube.insights import get_audience_insights, get_search_terms
from youtube.operations import operation

PERIODS = ("last_7_days", "last_28_days", "last_week", "last_month")

#: Analytics data lags; periods ending "today" stop this many days earlier.
DATA_LAG_DAYS = 2

_REPORT_METRICS = ("views", "estimatedMinutesWatched", "averageViewDuration", "subscribersGained", "subscribersLost", "likes", "comments", "shares")


def period_dates(period: str, *, today: date | None = None) -> tuple[str, str]:
    """The ``(start, end)`` of a named period.

    ``last_7_days`` / ``last_28_days`` end :data:`DATA_LAG_DAYS` before today;
    ``last_week`` is the previous Monday-Sunday; ``last_month`` the previous
    calendar month.
    """
    today = today or date.today()
    if period in ("last_7_days", "last_28_days"):
        end = today - timedelta(days=DATA_LAG_DAYS)
        return (end - timedelta(days=int(period.split("_")[1]) - 1)).isoformat(), end.isoformat()
    if period == "last_week":
        monday = today - timedelta(days=today.weekday() + 7)
        return monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    if period == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1).isoformat(), end.isoformat()
    raise InvalidRequestError(f"period must be one of {', '.join(PERIODS)}; got {period!r}.")


def _previous(start: str, end: str) -> tuple[str, str]:
    """The period of the same length just before ``start``-``end`` (the previous month for a whole month)."""
    s, e = parse_date(start), parse_date(end)
    if s.day == 1 and (e + timedelta(days=1)).day == 1:
        prev_end = s - timedelta(days=1)
        return prev_end.replace(day=1).isoformat(), prev_end.isoformat()
    length = (e - s).days + 1
    return (s - timedelta(days=length)).isoformat(), (s - timedelta(days=1)).isoformat()


def _change(now: float | None, before: float | None) -> float | None:
    if now is None or not before:
        return None
    return round((now - before) / before, 4)


@operation(requires_oauth=True)
def build_report(
    client: YouTubeClient,
    start_date: str,
    end_date: str,
    top_n: int = 5,
) -> dict[str, Any]:
    """A channel performance report: totals vs the previous period, top videos, audience, search terms.

    Args:
        client: The API client (OAuth).
        start_date: ``YYYY-MM-DD``, inclusive.
        end_date: ``YYYY-MM-DD``, inclusive.
        top_n: How many top videos (each with its main traffic source), 1-25.

    Returns:
        ``{"period", "previous_period", "totals", "previous_totals", "change",
        "net_subscribers", "top_videos", "audience", "search_terms"}``. ``change``
        is the fractional change per metric (0.1 = +10%). A section that fails
        holds ``{"error": ...}``.
    """
    if not 1 <= top_n <= 25:
        raise InvalidRequestError(f"top_n must be between 1 and 25, got {top_n}.")
    start, end = date_range(start_date, end_date)
    prev_start, prev_end = _previous(start, end)

    now = get_channel_analytics(client, start, end)
    before = get_channel_analytics(client, prev_start, prev_end)
    totals = {m: now["totals"].get(m) for m in _REPORT_METRICS}
    previous = {m: before["totals"].get(m) for m in _REPORT_METRICS}

    def top_videos() -> list[dict[str, Any]]:
        videos = get_top_videos(client, start, end, metric="views", limit=top_n)["videos"]
        for video in videos:
            sources = _query(
                client, start, end, ("views",), dimensions="insightTrafficSourceType",
                filters=f"video=={video['video_id']}", sort="-views", max_results=1,
            )
            video["main_traffic_source"] = sources[0]["insightTrafficSourceType"] if sources else None
        return [
            {k: v.get(k) for k in ("rank", "title", "url", "views", "estimatedMinutesWatched", "likes", "main_traffic_source")}
            for v in videos
        ]

    def audience() -> dict[str, Any]:
        insights = get_audience_insights(
            client, start, end, breakdowns=["countries", "devices", "subscribed_status", "content_types", "traffic_sources"], limit=3
        )
        return {k: v for k, v in insights.items() if k not in ("start_date", "end_date", "video_id")}

    return {
        "period": {"start": start, "end": end},
        "previous_period": {"start": prev_start, "end": prev_end},
        "totals": totals,
        "previous_totals": previous,
        "change": {m: _change(totals[m], previous[m]) for m in _REPORT_METRICS},
        "net_subscribers": now["net_subscribers"],
        "previous_net_subscribers": before["net_subscribers"],
        "top_videos": _section(top_videos),
        "audience": _section(audience),
        "search_terms": _section(lambda: get_search_terms(client, start, end, limit=10)["terms"]),
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.0%}"


def _num(value: Any) -> str:
    return "n/a" if value is None else f"{value:,}"


def render_markdown(report: dict[str, Any], *, title: str = "YouTube report") -> str:
    """Format a :func:`build_report` result as Markdown."""
    p, pp = report["period"], report["previous_period"]
    t, ch = report["totals"], report["change"]
    lines = [
        f"# {title}: {p['start']} to {p['end']}",
        f"Compared with {pp['start']} to {pp['end']}.",
        "",
        "| Metric | Value | Change |",
        "|---|---:|---:|",
        f"| Views | {_num(t['views'])} | {_pct(ch['views'])} |",
        f"| Watch time (hours) | {_num(round((t['estimatedMinutesWatched'] or 0) / 60))} | {_pct(ch['estimatedMinutesWatched'])} |",
        f"| Avg view duration (s) | {_num(t['averageViewDuration'])} | {_pct(ch['averageViewDuration'])} |",
        f"| Net subscribers | {report['net_subscribers']:+,} | was {report['previous_net_subscribers']:+,} |",
        f"| Likes | {_num(t['likes'])} | {_pct(ch['likes'])} |",
        f"| Comments | {_num(t['comments'])} | {_pct(ch['comments'])} |",
        f"| Shares | {_num(t['shares'])} | {_pct(ch['shares'])} |",
        "",
        "## Top videos",
    ]
    top = report["top_videos"]
    if isinstance(top, dict):
        lines.append(f"_Unavailable: {top['error']}_")
    elif not top:
        lines.append("_No views in this period._")
    else:
        for v in top:
            source = f", mostly from {v['main_traffic_source']}" if v.get("main_traffic_source") else ""
            lines.append(f"{v['rank']}. [{v['title']}]({v['url']}): {_num(v['views'])} views{source}")
    audience = report["audience"]
    lines += ["", "## Audience"]
    if "error" in audience:
        lines.append(f"_Unavailable: {audience['error']}_")
    else:
        labels = {
            "countries": ("country", "Top countries"),
            "devices": ("deviceType", "Devices"),
            "subscribed_status": ("subscribedStatus", "Subscribers vs not"),
            "content_types": ("creatorContentType", "Formats"),
            "traffic_sources": ("insightTrafficSourceType", "Traffic sources"),
        }
        for key, (dim, label) in labels.items():
            rows = audience.get(key)
            if isinstance(rows, list) and rows:
                parts = [f"{r[dim]} {r['share_of_total']:.0%}" for r in rows if r.get("share_of_total") is not None]
                lines.append(f"- **{label}:** {', '.join(parts)}")
    terms = report["search_terms"]
    if isinstance(terms, list) and terms:
        lines += ["", "## Top YouTube searches", ", ".join(f"{t['term']} ({t['views']})" for t in terms)]
    return "\n".join(lines) + "\n"


@operation(requires_oauth=True)
def detect_anomalies(
    client: YouTubeClient,
    days: int = 14,
    baseline_days: int = 28,
    threshold: float = 2.0,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Flag recent days whose views or subscriber change stand out from the days before.

    Args:
        client: The API client (OAuth).
        days: How many recent days to check, 1-90.
        baseline_days: How many days before each checked day form its baseline, 7-180.
        threshold: A day is a spike when views >= threshold x the baseline
            median, a drop when views <= baseline median / threshold. Must be > 1.

    Returns:
        ``{"checked", "baseline_days", "threshold", "anomalies": [{day, kind, views,
        baseline_median, ratio}], "subscriber_alerts": [...]}``. Subscriber alerts
        are days that lost at least 3 more subscribers than they gained.
    """
    if not 1 <= days <= 90:
        raise InvalidRequestError(f"days must be between 1 and 90, got {days}.")
    if not 7 <= baseline_days <= 180:
        raise InvalidRequestError(f"baseline_days must be between 7 and 180, got {baseline_days}.")
    if threshold <= 1:
        raise InvalidRequestError(f"threshold must be greater than 1, got {threshold}.")
    end = (today or date.today()) - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=days + baseline_days - 1)
    rows = _query(client, start.isoformat(), end.isoformat(), CHANNEL_METRICS, dimensions="day", sort="day")
    series = {r["day"]: r for r in rows}

    anomalies: list[dict[str, Any]] = []
    subscriber_alerts: list[dict[str, Any]] = []
    for offset in range(days):
        day = end - timedelta(days=days - 1 - offset)
        row = series.get(day.isoformat())
        if row is None:
            continue
        baseline = [
            series[d.isoformat()]["views"]
            for d in (day - timedelta(days=i) for i in range(1, baseline_days + 1))
            if d.isoformat() in series
        ]
        if len(baseline) >= 7:
            base = median(baseline)
            views = row.get("views") or 0
            kind = "spike" if base and views >= threshold * base else "drop" if base and views <= base / threshold else None
            if kind:
                anomalies.append(
                    {"day": day.isoformat(), "kind": kind, "views": views, "baseline_median": base,
                     "ratio": round(views / base, 2) if base else None}
                )
        net = (row.get("subscribersGained") or 0) - (row.get("subscribersLost") or 0)
        if net <= -3:
            subscriber_alerts.append(
                {"day": day.isoformat(), "net_subscribers": net,
                 "gained": row.get("subscribersGained"), "lost": row.get("subscribersLost")}
            )
    first_checked = (end - timedelta(days=days - 1)).isoformat()
    return {
        "checked": {"start": first_checked, "end": end.isoformat()},
        "baseline_days": baseline_days,
        "threshold": threshold,
        "anomalies": anomalies,
        "subscriber_alerts": subscriber_alerts,
    }

