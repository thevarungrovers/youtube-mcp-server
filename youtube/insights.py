"""Audience insights: where viewers are, how they watch, and how they find the channel.

Like :mod:`youtube.analytics`, every report is for the authenticated channel
(OAuth), optionally narrowed to one video, and lags by 2-3 days.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from youtube._utils import clamp, date_range
from youtube.analytics import _query, _section
from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError
from youtube.operations import operation


@dataclass(frozen=True)
class Breakdown:
    """One audience report: a dimension and the metrics reported for each of its values."""

    dimension: str | None
    metrics: tuple[str, ...]
    description: str
    filters: str | None = None
    max_rows: int | None = None  # the API's cap for this dimension; None = no row limit


_WATCH = ("views", "estimatedMinutesWatched")

BREAKDOWNS: dict[str, Breakdown] = {
    "countries": Breakdown("country", (*_WATCH, "averageViewDuration"), "Views by viewer country (ISO code).", max_rows=250),
    "cities": Breakdown("city", _WATCH, "Views by viewer city.", max_rows=250),
    "devices": Breakdown("deviceType", _WATCH, "Mobile, desktop, tablet, TV, ..."),
    "operating_systems": Breakdown("operatingSystem", ("views",), "Android, iOS, Windows, ..."),
    "playback_locations": Breakdown(
        "insightPlaybackLocationType", _WATCH, "Where the video was played: YouTube watch page, Shorts feed, embedded, ..."
    ),
    "embedding_sites": Breakdown(
        "insightPlaybackLocationDetail", _WATCH, "Websites that play the videos in an embedded player.",
        filters="insightPlaybackLocationType==EMBEDDED", max_rows=25,
    ),
    "traffic_sources": Breakdown(
        "insightTrafficSourceType", _WATCH, "How viewers found the videos: search, suggested, external, Shorts, ..."
    ),
    "external_sites": Breakdown(
        "insightTrafficSourceDetail", _WATCH, "Websites and apps that link viewers to the videos.",
        filters="insightTrafficSourceType==EXT_URL", max_rows=25,
    ),
    "subscribed_status": Breakdown(
        "subscribedStatus", (*_WATCH, "averageViewDuration"), "Subscribers vs non-subscribers."
    ),
    "content_types": Breakdown(
        "creatorContentType", (*_WATCH, "likes", "subscribersGained"), "Shorts vs long-form vs live."
    ),
    "sharing_services": Breakdown("sharingService", ("shares",), "Where viewers share the videos: WhatsApp, copy link, ..."),
    "cards": Breakdown(
        None,
        ("cardImpressions", "cardClicks", "cardClickRate", "cardTeaserImpressions", "cardTeaserClicks", "cardTeaserClickRate"),
        "Info card impressions, clicks and click rates.",
    ),
}

DEFAULT_BREAKDOWNS = ("countries", "devices", "playback_locations", "traffic_sources", "subscribed_status", "content_types")

#: Search terms come from a detail dimension, which the API caps at 25 rows.
MAX_SEARCH_TERMS = 25


def _video_filter(video_id: str | None, base: str | None = None) -> str | None:
    parts = [p for p in (base, f"video=={video_id.strip()}" if video_id and video_id.strip() else None) if p]
    return ";".join(parts) or None


def _sort_metric(spec: Breakdown) -> str:
    return "-views" if "views" in spec.metrics else f"-{spec.metrics[0]}"


@operation(requires_oauth=True)
def get_audience_insights(
    client: YouTubeClient,
    start_date: str,
    end_date: str,
    breakdowns: tuple[str, ...] | list[str] = DEFAULT_BREAKDOWNS,
    video_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Audience breakdowns: geography, devices, playback locations, traffic, subscribers, formats.

    Args:
        client: The API client (OAuth).
        start_date: ``YYYY-MM-DD``, inclusive.
        end_date: ``YYYY-MM-DD``, inclusive.
        breakdowns: Any keys of :data:`BREAKDOWNS`. One that fails reports
            ``{"error": ...}`` without failing the others.
        video_id: Narrow every breakdown to one video on the channel.
        limit: Rows per breakdown, 1-250 (detail breakdowns stop at 25).

    Returns:
        ``{"start_date", "end_date", "video_id", <breakdown>: [rows]}``, rows sorted
        by views (or shares) with ``share_of_total``: the row's fraction of all the
        period's views (or shares). ``cards`` is a single dict. An empty list means
        YouTube has no data for that breakdown (too few views, or not reported
        for that video).
    """
    unknown = set(breakdowns) - set(BREAKDOWNS)
    if unknown:
        raise InvalidRequestError(f"Unknown breakdowns {sorted(unknown)}; choose from {', '.join(BREAKDOWNS)}.")
    clamp(limit, 1, 250, name="limit")
    start, end = date_range(start_date, end_date)

    totals: dict[str, Any] = {}

    def total(metric: str) -> float:
        # One query for the whole period, so shares are of all views, not of the rows shown.
        if not totals:
            totals.update((_query(client, start, end, ("views", "shares"), filters=_video_filter(video_id)) or [{}])[0])
        return totals.get(metric) or 0

    def run(spec: Breakdown) -> Any:
        filters = _video_filter(video_id, spec.filters)
        if spec.dimension is None:
            return (_query(client, start, end, spec.metrics, filters=filters) or [{}])[0]
        sort = _sort_metric(spec)
        rows = _query(
            client, start, end, spec.metrics, dimensions=spec.dimension, filters=filters, sort=sort,
            max_results=min(limit, spec.max_rows) if spec.max_rows else None,
        )[:limit]
        key = sort.lstrip("-")
        whole = total(key) if rows else 0
        for row in rows:
            row["share_of_total"] = round((row.get(key) or 0) / whole, 4) if whole else None
        return rows

    result: dict[str, Any] = {"start_date": start, "end_date": end, "video_id": video_id or None}
    for name in BREAKDOWNS:
        if name in breakdowns:
            result[name] = _section(lambda spec=BREAKDOWNS[name]: run(spec))
    return result


@operation(requires_oauth=True)
def get_search_terms(
    client: YouTubeClient,
    start_date: str,
    end_date: str,
    video_id: str | None = None,
    limit: int = MAX_SEARCH_TERMS,
) -> dict[str, Any]:
    """The YouTube search terms that led viewers to the channel's videos.

    Args:
        client: The API client (OAuth).
        start_date: ``YYYY-MM-DD``, inclusive.
        end_date: ``YYYY-MM-DD``, inclusive.
        video_id: Only searches that led to this video.
        limit: How many terms, 1-25 (the API's maximum).

    Returns:
        ``{"start_date", "end_date", "video_id", "terms": [{term, views, estimatedMinutesWatched}]}``,
        most views first. Rare terms are omitted by YouTube for privacy.
    """
    clamp(limit, 1, MAX_SEARCH_TERMS, name="limit")
    start, end = date_range(start_date, end_date)
    rows = _query(
        client, start, end, ("views", "estimatedMinutesWatched"),
        dimensions="insightTrafficSourceDetail",
        filters=_video_filter(video_id, "insightTrafficSourceType==YT_SEARCH"),
        sort="-views", max_results=limit,
    )
    terms = [{"term": r.pop("insightTrafficSourceDetail"), **r} for r in rows]
    return {"start_date": start, "end_date": end, "video_id": video_id or None, "terms": terms}
