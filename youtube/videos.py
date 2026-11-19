"""Video operations: details, bulk statistics, search. Public data -- an API key suffices."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from youtube._utils import best_thumbnail, chunked, clamp, normalize_ids, parse_duration, thumbnail_urls, to_int, to_rfc3339
from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError
from youtube.operations import operation

#: videos.list accepts at most 50 IDs per request.
BATCH_SIZE = 50

SEARCH_ORDERS = ("relevance", "date", "viewCount", "rating", "title")


def _stats(item: dict[str, Any]) -> dict[str, int | None]:
    stats = item.get("statistics", {})
    return {
        "view_count": to_int(stats.get("viewCount")),
        "like_count": to_int(stats.get("likeCount")),
        "comment_count": to_int(stats.get("commentCount")),
        "favorite_count": to_int(stats.get("favoriteCount")),
    }


def format_video(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a ``videos.list`` item into a stable, JSON-friendly dict."""
    snippet = item.get("snippet", {})
    details = item.get("contentDetails", {})
    status = item.get("status", {})
    duration = details.get("duration")
    return {
        "id": item["id"],
        "url": f"https://www.youtube.com/watch?v={item['id']}",
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "tags": snippet.get("tags", []),
        "category_id": snippet.get("categoryId"),
        "default_language": snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage"),
        "live_broadcast_content": snippet.get("liveBroadcastContent"),
        "duration": duration,
        "duration_seconds": parse_duration(duration),
        "definition": details.get("definition"),
        "caption": details.get("caption") == "true" if "caption" in details else None,
        "privacy_status": status.get("privacyStatus"),
        "made_for_kids": status.get("madeForKids"),
        "thumbnail_url": best_thumbnail(snippet.get("thumbnails")),
        "thumbnails": thumbnail_urls(snippet.get("thumbnails")),
        **_stats(item),
    }


def fetch_videos(client: YouTubeClient, ids: list[str], part: str) -> dict[str, dict[str, Any]]:
    """Fetch raw ``videos.list`` items for ``ids`` in batches of 50, keyed by ID."""
    found: dict[str, dict[str, Any]] = {}
    for batch in chunked(ids, BATCH_SIZE):
        response = client.execute(
            client.data.videos().list(part=part, id=",".join(batch), maxResults=len(batch))
        )
        for item in response.get("items", []):
            found[item["id"]] = item
    return found


@operation()
def get_video_details(client: YouTubeClient, video_ids: str | Iterable[str]) -> dict[str, Any]:
    """Full details for one or more videos (title, stats, duration, tags, thumbnails...).

    Args:
        client: The API client.
        video_ids: One ID, a comma-separated string, or a list. Any number; they
            are fetched 50 at a time.

    Returns:
        ``{"videos": [...], "not_found": [...]}`` -- ``videos`` in the order
        requested; ``not_found`` lists IDs that are deleted, private, or wrong.
    """
    ids = normalize_ids(video_ids)
    found = fetch_videos(client, ids, "snippet,statistics,contentDetails,status")
    return {
        "videos": [format_video(found[i]) for i in ids if i in found],
        "not_found": [i for i in ids if i not in found],
    }


@operation()
def get_video_statistics(client: YouTubeClient, video_ids: str | Iterable[str]) -> dict[str, Any]:
    """View/like/comment counts for many videos at once (1 quota unit per 50 videos).

    Args:
        client: The API client.
        video_ids: One ID, a comma-separated string, or a list.

    Returns:
        ``{"statistics": {video_id: {view_count, like_count, ...}}, "not_found": [...]}``.
    """
    ids = normalize_ids(video_ids)
    found = fetch_videos(client, ids, "statistics")
    return {
        "statistics": {i: _stats(found[i]) for i in ids if i in found},
        "not_found": [i for i in ids if i not in found],
    }


@operation()
def search_videos(
    client: YouTubeClient,
    query: str,
    max_results: int = 10,
    order: str = "relevance",
    published_after: str | None = None,
    published_before: str | None = None,
    region_code: str | None = None,
    channel_id: str | None = None,
    page_token: str | None = None,
    include_stats: bool = True,
) -> dict[str, Any]:
    """Search public videos by keyword. Costs 100 quota units per page.

    Args:
        client: The API client.
        query: Search terms.
        max_results: Results per page, 1-50.
        order: One of ``relevance``, ``date``, ``viewCount``, ``rating``, ``title``.
        published_after: ``YYYY-MM-DD`` or RFC 3339; inclusive.
        published_before: ``YYYY-MM-DD`` (that whole day included) or RFC 3339.
        region_code: ISO 3166-1 alpha-2 country code, e.g. ``US``.
        channel_id: Restrict results to one channel.
        page_token: ``next_page_token`` from a previous call.
        include_stats: Add views/likes/duration (1 extra unit per page).

    Returns:
        ``{"videos": [...], "next_page_token", "total_results"}``.
    """
    if not query or not query.strip():
        raise InvalidRequestError("query must not be empty.")
    clamp(max_results, 1, 50, name="max_results")
    if order not in SEARCH_ORDERS:
        raise InvalidRequestError(f"order must be one of {', '.join(SEARCH_ORDERS)}; got {order!r}.")

    params: dict[str, Any] = {
        "part": "snippet",
        "q": query.strip(),
        "type": "video",
        "maxResults": max_results,
        "order": order,
    }
    after = to_rfc3339(published_after, name="published_after")
    before = to_rfc3339(published_before, end_of_day=True, name="published_before")
    if after:
        params["publishedAfter"] = after
    if before:
        params["publishedBefore"] = before
    if region_code:
        params["regionCode"] = region_code.strip().upper()
    if channel_id:
        params["channelId"] = channel_id.strip()
    if page_token:
        params["pageToken"] = page_token

    response = client.execute(client.data.search().list(**params))
    hits = [h for h in response.get("items", []) if h.get("id", {}).get("videoId")]
    ids = [h["id"]["videoId"] for h in hits]

    if include_stats and ids:
        found = fetch_videos(client, ids, "snippet,statistics,contentDetails")
        videos = [format_video(found[i]) for i in ids if i in found]
    else:
        videos = [
            {
                "id": h["id"]["videoId"],
                "url": f"https://www.youtube.com/watch?v={h['id']['videoId']}",
                "title": h["snippet"].get("title"),
                "description": h["snippet"].get("description"),
                "channel_id": h["snippet"].get("channelId"),
                "channel_title": h["snippet"].get("channelTitle"),
                "published_at": h["snippet"].get("publishedAt"),
                "thumbnail_url": best_thumbnail(h["snippet"].get("thumbnails")),
            }
            for h in hits
        ]
    return {
        "videos": videos,
        "next_page_token": response.get("nextPageToken"),
        "total_results": response.get("pageInfo", {}).get("totalResults"),
    }
