"""Flat, daily datasets for loading into a spreadsheet, warehouse or BI tool.

Each dataset is a list of flat rows (one per day and breakdown value), so it
can be written as CSV or JSON Lines and appended to a table on a schedule.
The analytics datasets need OAuth; ``videos`` (a snapshot of every upload
with its current counters) works with an API key too.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from youtube._utils import chunked, date_range
from youtube.analytics import CHANNEL_METRICS, _query
from youtube.channels import list_channel_videos
from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError, oauth_required

_WATCH = ("views", "estimatedMinutesWatched")
_VIDEO_DAILY_METRICS = ("views", "estimatedMinutesWatched", "averageViewDuration", "likes", "comments", "shares", "subscribersGained", "subscribersLost")

#: Videos per ``video==a,b,...`` filter in the per-video daily query.
_VIDEO_FILTER_BATCH = 50

FORMATS = ("csv", "jsonl")


def _breakdown(dimension: str, metrics: tuple[str, ...] = _WATCH) -> Callable[[YouTubeClient, str, str], list[dict[str, Any]]]:
    def run(client: YouTubeClient, start: str, end: str) -> list[dict[str, Any]]:
        return _query(client, start, end, metrics, dimensions=f"day,{dimension}", sort="day")

    return run


def _channel_daily(client: YouTubeClient, start: str, end: str) -> list[dict[str, Any]]:
    return _query(client, start, end, CHANNEL_METRICS, dimensions="day", sort="day")


def _all_uploads(client: YouTubeClient) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        page = list_channel_videos(client, None, max_results=50, page_token=token)
        videos += page["videos"]
        token = page["next_page_token"]
        if not token:
            return videos


def _videos(client: YouTubeClient, start: str, end: str) -> list[dict[str, Any]]:
    snapshot = date.today().isoformat()
    keys = ("video_id", "title", "published_at", "duration_seconds", "view_count", "like_count", "comment_count", "privacy_status")
    return [{"snapshot_date": snapshot, **{k: v.get(k) for k in keys}} for v in _all_uploads(client)]


def _video_daily(client: YouTubeClient, start: str, end: str) -> list[dict[str, Any]]:
    ids = [v["video_id"] for v in _all_uploads(client) if v.get("video_id")]
    rows: list[dict[str, Any]] = []
    for batch in chunked(ids, _VIDEO_FILTER_BATCH):
        rows += _query(
            client, start, end, _VIDEO_DAILY_METRICS,
            dimensions="day,video", filters="video==" + ",".join(batch), sort="day",
        )
    return sorted(rows, key=lambda r: (r["day"], r["video"]))


DATASETS: dict[str, tuple[Callable[[YouTubeClient, str, str], list[dict[str, Any]]], bool, str]] = {
    # name: (builder, requires_oauth, description)
    "channel_daily": (_channel_daily, True, "Channel totals per day: views, watch time, subscribers, engagement."),
    "video_daily": (_video_daily, True, "Per video per day: views, watch time, engagement, subscribers."),
    "traffic_daily": (_breakdown("insightTrafficSourceType"), True, "Views and watch time per day and traffic source."),
    "device_daily": (_breakdown("deviceType"), True, "Views and watch time per day and device type."),
    "content_type_daily": (_breakdown("creatorContentType"), True, "Views and watch time per day for Shorts vs long-form."),
    "subscribed_daily": (_breakdown("subscribedStatus"), True, "Views and watch time per day, subscribers vs not."),
    "videos": (_videos, False, "Every upload with its current views, likes and comments (a snapshot; dates ignored)."),
}


def export_dataset(client: YouTubeClient, dataset: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Build one dataset's rows for the date range.

    Raises:
        InvalidRequestError: Unknown dataset or bad dates.
        OAuthRequiredError: An analytics dataset without OAuth.
    """
    if dataset not in DATASETS:
        raise InvalidRequestError(f"Unknown dataset {dataset!r}; choose from {', '.join(DATASETS)}.")
    builder, needs_oauth, _ = DATASETS[dataset]
    if needs_oauth and not client.auth.has_oauth:
        raise oauth_required(f"export {dataset}")
    start, end = date_range(start_date, end_date)
    return builder(client, start, end)


def write_rows(rows: list[dict[str, Any]], path: str | Path, fmt: str = "csv") -> Path:
    """Write rows as CSV (header from the union of keys, in first-seen order) or JSON Lines."""
    if fmt not in FORMATS:
        raise InvalidRequestError(f"format must be one of {', '.join(FORMATS)}; got {fmt!r}.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        if fmt == "jsonl":
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            fields = list(dict.fromkeys(k for row in rows for k in row))
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return path
