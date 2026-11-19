"""Compare channels side by side, and read YouTube's trending chart. Public data -- an API key suffices."""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any

from youtube._utils import clamp
from youtube.channels import get_channel_info, list_channel_videos
from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError, YouTubeError
from youtube.operations import operation
from youtube.videos import format_video

MAX_CHANNELS = 10

#: YouTube counts a video as a Short up to 3 minutes; duration is the only public signal.
SHORT_MAX_SECONDS = 180


def _days_between(first: str, last: str) -> float:
    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    return (parse(first) - parse(last)).total_seconds() / 86400


def _summarize(videos: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a channel's recent uploads into comparable numbers."""
    views = [v["view_count"] for v in videos if v.get("view_count") is not None]
    engagement = [
        ((v.get("like_count") or 0) + (v.get("comment_count") or 0)) / v["view_count"]
        for v in videos
        if v.get("view_count")
    ]
    dates = sorted((v["published_at"] for v in videos if v.get("published_at")), reverse=True)
    durations = [v["duration_seconds"] for v in videos if v.get("duration_seconds") is not None]
    best = max(videos, key=lambda v: v.get("view_count") or 0, default=None)
    return {
        "videos_sampled": len(videos),
        "median_views": int(median(views)) if views else None,
        "average_views": int(sum(views) / len(views)) if views else None,
        "engagement_rate": round(median(engagement), 4) if engagement else None,
        "days_between_uploads": round(_days_between(dates[0], dates[-1]) / (len(dates) - 1), 1) if len(dates) > 1 else None,
        "latest_upload": dates[0] if dates else None,
        "short_share": round(sum(d <= SHORT_MAX_SECONDS for d in durations) / len(durations), 2) if durations else None,
        "top_recent_video": {"title": best.get("title"), "url": best.get("url"), "view_count": best.get("view_count")}
        if best
        else None,
    }


@operation()
def compare_channels(
    client: YouTubeClient,
    channels: list[str],
    recent_videos: int = 20,
) -> dict[str, Any]:
    """Side-by-side numbers for several channels, from their profile and their recent uploads.

    Args:
        client: The API client.
        channels: 1-10 channel IDs or @handles (``mine`` for your own, with OAuth).
        recent_videos: How many latest uploads per channel to sample, 1-50.

    Returns:
        ``{"recent_videos", "channels": [...]}`` in the order given. Each has
        subscribers, total views and videos, plus over the sampled uploads:
        ``median_views``, ``average_views``, ``engagement_rate`` (median of
        (likes + comments) / views), ``days_between_uploads``, ``latest_upload``,
        ``short_share`` (uploads of 3 minutes or less) and ``top_recent_video``.
        A channel that fails gets ``{"channel", "error"}`` instead. Costs about
        3 quota units per channel.
    """
    names = [c.strip() for c in channels if c and c.strip()]
    if not names:
        raise InvalidRequestError("Give at least one channel.")
    if len(names) > MAX_CHANNELS:
        raise InvalidRequestError(f"Compare at most {MAX_CHANNELS} channels at a time, got {len(names)}.")
    clamp(recent_videos, 1, 50, name="recent_videos")

    rows: list[dict[str, Any]] = []
    for name in names:
        try:
            info = get_channel_info(client, name)
            videos = list_channel_videos(client, info["id"], max_results=recent_videos)["videos"]
        except YouTubeError as exc:
            rows.append({"channel": name, "error": f"{exc.code}: {exc}"})
            continue
        rows.append(
            {
                "channel": name,
                "id": info["id"],
                "title": info["title"],
                "custom_url": info["custom_url"],
                "country": info["country"],
                "subscriber_count": info["subscriber_count"],
                "view_count": info["view_count"],
                "video_count": info["video_count"],
                **_summarize(videos),
            }
        )
    return {"recent_videos": recent_videos, "channels": rows}


@operation()
def get_trending_videos(
    client: YouTubeClient,
    region_code: str = "US",
    category_id: str | None = None,
    max_results: int = 25,
    page_token: str | None = None,
) -> dict[str, Any]:
    """YouTube's most-popular chart for a country, optionally one category.

    Args:
        client: The API client.
        region_code: ISO 3166-1 alpha-2 country code, e.g. ``CA``.
        category_id: A video category ID (e.g. ``26`` Howto & Style, ``19``
            Travel & Events, ``22`` People & Blogs). Not every category has a chart.
        max_results: Videos per page, 1-50.
        page_token: ``next_page_token`` from a previous call.

    Returns:
        ``{"region_code", "category_id", "videos": [...], "next_page_token"}``. 1 quota unit.
    """
    clamp(max_results, 1, 50, name="max_results")
    region = (region_code or "").strip().upper()
    if len(region) != 2:
        raise InvalidRequestError(f"region_code must be a 2-letter country code, got {region_code!r}.")
    params: dict[str, Any] = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": max_results,
    }
    if category_id:
        params["videoCategoryId"] = category_id
    if page_token:
        params["pageToken"] = page_token
    response = client.execute(client.data.videos().list(**params))
    return {
        "region_code": region,
        "category_id": category_id,
        "videos": [format_video(item) for item in response.get("items", [])],
        "next_page_token": response.get("nextPageToken"),
    }
