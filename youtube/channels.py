"""Channel operations: details, uploaded videos. Public data -- an API key suffices.

A ``channel`` argument may be a channel ID (``UC...``), a handle (``@name``),
or omitted. Omitted means ``YOUTUBE_CHANNEL_ID`` from ``.env`` when only an API
key is available, and the authenticated user's own channel under OAuth.
"""

from __future__ import annotations

import re
from typing import Any

from youtube import auth as auth_module
from youtube._utils import best_thumbnail, clamp, thumbnail_urls, to_int
from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError, NotFoundError
from youtube.operations import operation

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


def channel_selector(client: YouTubeClient, channel: str | None) -> dict[str, Any]:
    """Translate a ``channel`` argument into ``channels.list`` filter parameters.

    Raises:
        InvalidRequestError: No channel given and none can be inferred.
    """
    channel = (channel or "").strip()
    if not channel:
        if client.auth.has_oauth:
            return {"mine": True}
        channel = auth_module.default_channel() or ""
    if not channel:
        raise InvalidRequestError(
            "No channel specified. With only an API key, pass a channel ID (UC...) or "
            "handle (@name), or set YOUTUBE_CHANNEL_ID in .env. With OAuth "
            "(`python cli.py auth`), your own channel is used by default."
        )
    if channel.lower() == "mine":
        if not client.auth.has_oauth:
            raise InvalidRequestError("channel='mine' requires OAuth. Run `python cli.py auth` to set up.")
        return {"mine": True}
    if _CHANNEL_ID_RE.match(channel):
        return {"id": channel}
    return {"forHandle": channel if channel.startswith("@") else f"@{channel}"}


def _fetch_channel(client: YouTubeClient, channel: str | None, part: str) -> dict[str, Any]:
    selector = channel_selector(client, channel)
    response = client.execute(client.data.channels().list(part=part, **selector))
    items = response.get("items") or []
    if not items:
        raise NotFoundError(f"Channel not found: {channel or selector}.")
    return items[0]


def resolve_channel_id(client: YouTubeClient, channel: str | None) -> str:
    """Return the ``UC...`` channel ID for any accepted ``channel`` form."""
    if channel and _CHANNEL_ID_RE.match(channel.strip()):
        return channel.strip()
    return _fetch_channel(client, channel, "id")["id"]


@operation()
def get_channel_info(client: YouTubeClient, channel: str | None = None) -> dict[str, Any]:
    """Channel overview: name, description, subscriber/video/view counts.

    Args:
        client: The API client.
        channel: Channel ID, @handle, or None (see module docs).

    Returns:
        A dict with ``id``, ``title``, ``description``, ``custom_url``,
        ``published_at``, ``country``, ``thumbnail_url``, ``subscriber_count``
        (None when the channel hides it), ``video_count``, ``view_count`` and
        ``uploads_playlist_id``.
    """
    item = _fetch_channel(client, channel, "snippet,statistics,contentDetails")
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    return {
        "id": item["id"],
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "custom_url": snippet.get("customUrl"),
        "published_at": snippet.get("publishedAt"),
        "country": snippet.get("country"),
        "thumbnail_url": best_thumbnail(snippet.get("thumbnails")),
        "thumbnails": thumbnail_urls(snippet.get("thumbnails")),
        "subscriber_count": None if stats.get("hiddenSubscriberCount") else to_int(stats.get("subscriberCount")),
        "subscriber_count_hidden": bool(stats.get("hiddenSubscriberCount")),
        "video_count": to_int(stats.get("videoCount")),
        "view_count": to_int(stats.get("viewCount")),
        "uploads_playlist_id": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
    }


@operation()
def list_channel_videos(
    client: YouTubeClient,
    channel: str | None = None,
    max_results: int = 25,
    page_token: str | None = None,
    include_stats: bool = True,
) -> dict[str, Any]:
    """A channel's uploads, newest first, one page at a time.

    Reads the channel's uploads playlist (1 quota unit per page) rather than
    using search (100 units).

    Args:
        client: The API client.
        channel: Channel ID, @handle, or None (see module docs).
        max_results: Videos per page, 1-50.
        page_token: ``next_page_token`` from a previous call.
        include_stats: Add views/likes/comments/duration (one extra request per page).

    Returns:
        ``{"channel_id", "videos": [...], "next_page_token", "total_results"}``.
    """
    from youtube.playlists import get_playlist_items  # avoid an import cycle

    clamp(max_results, 1, 50, name="max_results")
    item = _fetch_channel(client, channel, "contentDetails")
    uploads = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        raise NotFoundError(f"Channel {item['id']} has no uploads playlist.")
    page = get_playlist_items(
        client, uploads, max_results=max_results, page_token=page_token, include_stats=include_stats
    )
    return {
        "channel_id": item["id"],
        "videos": page["items"],
        "next_page_token": page["next_page_token"],
        "total_results": page["total_results"],
    }
