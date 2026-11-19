"""YouTube Analytics operations. All require OAuth as the channel's owner or manager.

Every report is for the authenticated channel (``ids=channel==MINE``). Dates
are ``YYYY-MM-DD`` and inclusive; analytics data usually lags by 2-3 days, so
the most recent days may be missing or incomplete.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from youtube._utils import chunked, clamp, date_range
from youtube.client import YouTubeClient
from youtube.errors import AuthError, InvalidRequestError, QuotaExceededError, YouTubeError
from youtube.operations import operation
from youtube.videos import BATCH_SIZE

API = "YouTube Analytics API"

CHANNEL_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "subscribersGained",
    "subscribersLost",
    "likes",
    "comments",
    "shares",
)

VIDEO_SUMMARY_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
)

REVENUE_METRICS = (
    "estimatedRevenue",
    "estimatedAdRevenue",
    "grossRevenue",
    "monetizedPlaybacks",
    "playbackBasedCpm",
    "cpm",
)

GRANULARITIES = ("total", "day", "month")

#: Metric names accepted by :func:`get_top_videos`, mapped to the API metric they sort on.
TOP_METRICS: dict[str, str] = {
    "views": "views",
    "watch_time": "estimatedMinutesWatched",
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
    "subscribers": "subscribersGained",
    "engagement": "engagement",  # computed: likes + comments + shares
}

VIDEO_SECTIONS = ("summary", "traffic_sources", "retention", "demographics")

_TOP_VIDEO_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
)

#: The API's hard limit on rows for a ``dimensions=video`` report.
_MAX_VIDEO_ROWS = 200


def _query(
    client: YouTubeClient,
    start: str,
    end: str,
    metrics: tuple[str, ...] | list[str],
    *,
    dimensions: str | None = None,
    filters: str | None = None,
    sort: str | None = None,
    max_results: int | None = None,
    currency: str | None = None,
) -> list[dict[str, Any]]:
    """Run one ``reports.query`` and return its rows as dicts keyed by column name."""
    params: dict[str, Any] = {
        "ids": "channel==MINE",
        "startDate": start,
        "endDate": end,
        "metrics": ",".join(metrics),
    }
    for key, value in (
        ("dimensions", dimensions),
        ("filters", filters),
        ("sort", sort),
        ("maxResults", max_results),
        ("currency", currency),
    ):
        if value is not None:
            params[key] = value
    response = client.execute(client.analytics.reports().query(**params), api=API)
    headers = [h["name"] for h in response.get("columnHeaders", [])]
    return [dict(zip(headers, row)) for row in response.get("rows") or []]


def _granular(
    client: YouTubeClient,
    start: str,
    end: str,
    metrics: tuple[str, ...],
    granularity: str,
    **kwargs: Any,
) -> dict[str, Any]:
    if granularity not in GRANULARITIES:
        raise InvalidRequestError(f"granularity must be one of {', '.join(GRANULARITIES)}; got {granularity!r}.")
    if granularity == "month" and (start[8:] != "01"):
        raise InvalidRequestError("granularity='month' needs start_date on the 1st of a month.")
    totals = _query(client, start, end, metrics, **kwargs)
    result: dict[str, Any] = {
        "start_date": start,
        "end_date": end,
        "totals": totals[0] if totals else {m: 0 for m in metrics},
    }
    if granularity != "total":
        # A month series must end on the 1st of its last month; YouTube still
        # returns that whole month (to date). The totals keep the real end date.
        rows_end = end[:8] + "01" if granularity == "month" else end
        result["granularity"] = granularity
        result["rows"] = _query(client, start, rows_end, metrics, dimensions=granularity, sort=granularity, **kwargs)
    return result


@operation(requires_oauth=True)
def get_channel_analytics(
    client: YouTubeClient,
    start_date: str,
    end_date: str,
    granularity: str = "total",
) -> dict[str, Any]:
    """Channel views, watch time, and subscribers gained/lost over a date range.

    Args:
        client: The API client (OAuth).
        start_date: ``YYYY-MM-DD``, inclusive.
        end_date: ``YYYY-MM-DD``, inclusive.
        granularity: ``total`` for one row, or ``day`` / ``month`` to add a
            time series under ``rows`` (``month`` needs start on the 1st).

    Returns:
        ``{"start_date", "end_date", "totals": {...}, "net_subscribers", "rows"?}``
        where watch time is ``estimatedMinutesWatched`` and durations are seconds.
    """
    start, end = date_range(start_date, end_date)
    result = _granular(client, start, end, CHANNEL_METRICS, granularity)
    totals = result["totals"]
    result["net_subscribers"] = (totals.get("subscribersGained") or 0) - (totals.get("subscribersLost") or 0)
    return result


def _section(fn: Any) -> Any:
    """Run one report section; turn a section-specific failure into an ``error`` entry.

    Quota and credential problems still raise, since every other section would
    hit them too.
    """
    try:
        return fn()
    except (AuthError, QuotaExceededError):
        raise
    except YouTubeError as exc:
        return {"error": f"{exc.code}: {exc}"}


@operation(requires_oauth=True)
def get_video_analytics(
    client: YouTubeClient,
    video_id: str,
    start_date: str,
    end_date: str,
    sections: tuple[str, ...] | list[str] = VIDEO_SECTIONS,
) -> dict[str, Any]:
    """Per-video analytics: summary, traffic sources, audience retention, demographics.

    Args:
        client: The API client (OAuth).
        video_id: A video on the authenticated channel.
        start_date: ``YYYY-MM-DD``, inclusive.
        end_date: ``YYYY-MM-DD``, inclusive.
        sections: Any of ``summary``, ``traffic_sources``, ``retention``,
            ``demographics``. One that fails (e.g. too little data for
            demographics) reports ``{"error": ...}`` without failing the others.

    Returns:
        ``{"video_id", "start_date", "end_date", <section>: ...}``. Retention rows
        give ``audienceWatchRatio`` at each ``elapsedVideoTimeRatio`` (0.01-1.0);
        demographics give ``viewerPercentage`` by ``ageGroup`` and ``gender``.
    """
    video_id = (video_id or "").strip()
    if not video_id:
        raise InvalidRequestError("video_id must not be empty.")
    unknown = set(sections) - set(VIDEO_SECTIONS)
    if unknown:
        raise InvalidRequestError(f"Unknown sections {sorted(unknown)}; choose from {', '.join(VIDEO_SECTIONS)}.")
    start, end = date_range(start_date, end_date)
    flt = f"video=={video_id}"

    runners = {
        "summary": lambda: (_query(client, start, end, VIDEO_SUMMARY_METRICS, filters=flt) or [{}])[0],
        "traffic_sources": lambda: _query(
            client, start, end, ("views", "estimatedMinutesWatched"),
            dimensions="insightTrafficSourceType", filters=flt, sort="-views",
        ),
        "retention": lambda: _query(
            client, start, end, ("audienceWatchRatio", "relativeRetentionPerformance"),
            dimensions="elapsedVideoTimeRatio", filters=flt,
        ),
        "demographics": lambda: _query(
            client, start, end, ("viewerPercentage",),
            dimensions="ageGroup,gender", filters=flt, sort="gender,ageGroup",
        ),
    }
    result: dict[str, Any] = {"video_id": video_id, "start_date": start, "end_date": end}
    for name in VIDEO_SECTIONS:
        if name in sections:
            result[name] = _section(runners[name])
    return result


def _video_titles(client: YouTubeClient, ids: list[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for batch in chunked(ids, BATCH_SIZE):
        response = client.execute(client.data.videos().list(part="snippet", id=",".join(batch), maxResults=len(batch)))
        for item in response.get("items", []):
            titles[item["id"]] = item.get("snippet", {}).get("title", "")
    return titles


@operation(requires_oauth=True)
def get_top_videos(
    client: YouTubeClient,
    start_date: str,
    end_date: str,
    metric: str = "views",
    limit: int = 10,
) -> dict[str, Any]:
    """Top N videos on the authenticated channel by a metric over a date range.

    Args:
        client: The API client (OAuth).
        start_date: ``YYYY-MM-DD``, inclusive.
        end_date: ``YYYY-MM-DD``, inclusive.
        metric: ``views``, ``watch_time``, ``likes``, ``comments``, ``shares``,
            ``subscribers``, or ``engagement`` (likes + comments + shares;
            ranked among the top 200 videos by views, since the API cannot
            sort on a computed value).
        limit: How many videos, 1-200.

    Returns:
        ``{"metric", "start_date", "end_date", "videos": [{rank, video_id, title, ...metrics}]}``.
    """
    if metric not in TOP_METRICS:
        raise InvalidRequestError(f"metric must be one of {', '.join(TOP_METRICS)}; got {metric!r}.")
    clamp(limit, 1, _MAX_VIDEO_ROWS, name="limit")
    start, end = date_range(start_date, end_date)

    api_metric = TOP_METRICS[metric]
    if metric == "engagement":
        rows = _query(client, start, end, _TOP_VIDEO_METRICS, dimensions="video", sort="-views", max_results=_MAX_VIDEO_ROWS)
        for row in rows:
            row["engagement"] = (row.get("likes") or 0) + (row.get("comments") or 0) + (row.get("shares") or 0)
        rows = sorted(rows, key=lambda r: r["engagement"], reverse=True)[:limit]
    else:
        rows = _query(client, start, end, _TOP_VIDEO_METRICS, dimensions="video", sort=f"-{api_metric}", max_results=limit)

    titles = _video_titles(client, [r["video"] for r in rows]) if rows else {}
    videos = []
    for rank, row in enumerate(rows, start=1):
        video_id = row.pop("video")
        videos.append(
            {
                "rank": rank,
                "video_id": video_id,
                "title": titles.get(video_id),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                **row,
            }
        )
    return {"metric": metric, "sorted_by": api_metric, "start_date": start, "end_date": end, "videos": videos}


@operation(requires_oauth=True)
def get_revenue(
    client: YouTubeClient,
    start_date: str,
    end_date: str,
    granularity: str = "total",
    currency: str = "USD",
) -> dict[str, Any]:
    """Estimated revenue, ad revenue, and CPM -- only for monetized channels.

    Args:
        client: The API client (OAuth with the yt-analytics-monetary scope).
        start_date: ``YYYY-MM-DD``, inclusive.
        end_date: ``YYYY-MM-DD``, inclusive.
        granularity: ``total``, ``day``, or ``month``.
        currency: ISO 4217 code for monetary values, e.g. ``USD``.

    Returns:
        ``{"available": True, "currency", "totals", "rows"?}``, or
        ``{"available": False, "reason": ...}`` when the channel is not in the
        YouTube Partner Program or the token lacks the monetary scope.
    """
    start, end = date_range(start_date, end_date)
    try:
        result = _granular(client, start, end, REVENUE_METRICS, granularity, currency=currency.upper())
    except AuthError as exc:
        return {
            "available": False,
            "reason": (
                f"{exc} Revenue data requires a channel in the YouTube Partner Program and an "
                "OAuth token with the yt-analytics-monetary.readonly scope (re-run `python cli.py auth`)."
            ),
        }
    return {"available": True, "currency": currency.upper(), **result}


def last_n_days(days: int, *, today: date | None = None) -> tuple[str, str]:
    """The ``(start, end)`` dates of the last ``days`` days, ending today (local time)."""
    if days < 1:
        raise InvalidRequestError(f"days must be at least 1, got {days}.")
    end = today or date.today()
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()
