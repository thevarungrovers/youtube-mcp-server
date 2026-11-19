"""Playlist operations. Public data -- an API key suffices (private playlists need OAuth)."""

from __future__ import annotations

from typing import Any

from youtube._utils import best_thumbnail, clamp, parse_duration, to_int
from youtube.channels import channel_selector, resolve_channel_id
from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError, NotFoundError
from youtube.operations import operation
from youtube.videos import fetch_videos


def _format_playlist(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    return {
        "id": item["id"],
        "url": f"https://www.youtube.com/playlist?list={item['id']}",
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "channel_id": snippet.get("channelId"),
        "channel_title": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "item_count": to_int(item.get("contentDetails", {}).get("itemCount")),
        "privacy_status": item.get("status", {}).get("privacyStatus"),
        "thumbnail_url": best_thumbnail(snippet.get("thumbnails")),
    }


@operation()
def list_playlists(
    client: YouTubeClient,
    channel: str | None = None,
    max_results: int = 25,
    page_token: str | None = None,
) -> dict[str, Any]:
    """A channel's playlists, one page at a time.

    Args:
        client: The API client.
        channel: Channel ID, @handle, or None (see :mod:`youtube.channels`).
        max_results: Playlists per page, 1-50.
        page_token: ``next_page_token`` from a previous call.

    Returns:
        ``{"playlists": [...], "next_page_token", "total_results"}``.
    """
    clamp(max_results, 1, 50, name="max_results")
    selector = channel_selector(client, channel)
    params: dict[str, Any] = {"part": "snippet,contentDetails,status", "maxResults": max_results}
    if selector.get("mine"):
        params["mine"] = True
    else:
        params["channelId"] = resolve_channel_id(client, channel)
    if page_token:
        params["pageToken"] = page_token
    response = client.execute(client.data.playlists().list(**params))
    return {
        "playlists": [_format_playlist(p) for p in response.get("items", [])],
        "next_page_token": response.get("nextPageToken"),
        "total_results": response.get("pageInfo", {}).get("totalResults"),
    }


@operation()
def get_playlist_details(client: YouTubeClient, playlist_id: str) -> dict[str, Any]:
    """Title, description, owner, and item count of one playlist.

    Raises:
        NotFoundError: The playlist does not exist or is private.
    """
    if not playlist_id or not playlist_id.strip():
        raise InvalidRequestError("playlist_id must not be empty.")
    response = client.execute(
        client.data.playlists().list(part="snippet,contentDetails,status", id=playlist_id.strip())
    )
    items = response.get("items") or []
    if not items:
        raise NotFoundError(f"Playlist not found: {playlist_id}. Private playlists need OAuth as their owner.")
    return _format_playlist(items[0])


@operation()
def get_playlist_items(
    client: YouTubeClient,
    playlist_id: str,
    max_results: int = 25,
    page_token: str | None = None,
    include_stats: bool = False,
) -> dict[str, Any]:
    """Videos in a playlist, in playlist order, one page at a time.

    Args:
        client: The API client.
        playlist_id: The playlist ID (``PL...``, ``UU...``, etc.).
        max_results: Items per page, 1-50.
        page_token: ``next_page_token`` from a previous call.
        include_stats: Add views/likes/comments/duration (1 extra unit per page).

    Returns:
        ``{"playlist_id", "items": [...], "next_page_token", "total_results"}``.
    """
    if not playlist_id or not playlist_id.strip():
        raise InvalidRequestError("playlist_id must not be empty.")
    clamp(max_results, 1, 50, name="max_results")
    params: dict[str, Any] = {
        "part": "snippet,contentDetails,status",
        "playlistId": playlist_id.strip(),
        "maxResults": max_results,
    }
    if page_token:
        params["pageToken"] = page_token
    response = client.execute(client.data.playlistItems().list(**params))

    items: list[dict[str, Any]] = []
    for entry in response.get("items", []):
        snippet = entry.get("snippet", {})
        video_id = entry.get("contentDetails", {}).get("videoId") or snippet.get("resourceId", {}).get("videoId")
        items.append(
            {
                "position": snippet.get("position"),
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "published_at": entry.get("contentDetails", {}).get("videoPublishedAt"),
                "added_to_playlist_at": snippet.get("publishedAt"),
                "video_owner_channel_title": snippet.get("videoOwnerChannelTitle"),
                "privacy_status": entry.get("status", {}).get("privacyStatus"),
                "thumbnail_url": best_thumbnail(snippet.get("thumbnails")),
            }
        )

    if include_stats:
        ids = [i["video_id"] for i in items if i["video_id"]]
        found = fetch_videos(client, ids, "statistics,contentDetails") if ids else {}
        for item in items:
            video = found.get(item["video_id"] or "")
            stats = (video or {}).get("statistics", {})
            duration = (video or {}).get("contentDetails", {}).get("duration")
            item.update(
                view_count=to_int(stats.get("viewCount")),
                like_count=to_int(stats.get("likeCount")),
                comment_count=to_int(stats.get("commentCount")),
                duration_seconds=parse_duration(duration),
            )

    return {
        "playlist_id": playlist_id.strip(),
        "items": items,
        "next_page_token": response.get("nextPageToken"),
        "total_results": response.get("pageInfo", {}).get("totalResults"),
    }
