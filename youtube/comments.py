"""Comment operations.

Google refuses comment reads under the read-only OAuth scopes: it wants
``youtube.force-ssl``, which can also post and delete. ``cli.py auth`` grants
it unless ``--read-only``. Comments are read with OAuth first, falling back to
``YOUTUBE_API_KEY``. Either way this package only reads.
"""

from __future__ import annotations

from typing import Any

from youtube._utils import clamp, to_int
from youtube.channels import resolve_channel_id
from youtube.client import YouTubeClient
from youtube.errors import InvalidRequestError
from youtube.operations import operation

COMMENT_ORDERS = ("time", "relevance")


def _format_comment(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    return {
        "id": item.get("id"),
        "author": snippet.get("authorDisplayName"),
        "author_channel_id": (snippet.get("authorChannelId") or {}).get("value"),
        "text": snippet.get("textOriginal") or snippet.get("textDisplay"),
        "like_count": to_int(snippet.get("likeCount")),
        "published_at": snippet.get("publishedAt"),
        "updated_at": snippet.get("updatedAt"),
    }


def _format_thread(item: dict[str, Any], owner_id: str | None) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    top = _format_comment(snippet.get("topLevelComment", {}))
    replies = [_format_comment(r) for r in (item.get("replies") or {}).get("comments", [])]
    owner_id = owner_id or snippet.get("channelId")
    video_id = snippet.get("videoId")
    return {
        **top,
        "thread_id": item.get("id"),
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}&lc={item.get('id')}" if video_id else None,
        "reply_count": to_int(snippet.get("totalReplyCount")) or 0,
        "is_owner_comment": bool(owner_id) and top["author_channel_id"] == owner_id,
        # Only the first few replies come with a thread; see get_comment_replies for the rest.
        "owner_replied": bool(owner_id) and any(r["author_channel_id"] == owner_id for r in replies),
        "replies": replies,
    }


@operation(requires_comment_access=True)
def list_comments(
    client: YouTubeClient,
    video_id: str | None = None,
    channel: str | None = None,
    order: str = "time",
    search: str | None = None,
    max_results: int = 50,
    page_token: str | None = None,
) -> dict[str, Any]:
    """Comment threads on one video, or on all of a channel's videos, newest or most relevant first.

    Args:
        client: The API client.
        video_id: Comments on this video. If omitted, comments on every video
            of ``channel``.
        channel: Channel ID, @handle, or None (see :mod:`youtube.channels`).
            Ignored when ``video_id`` is given.
        order: ``time`` (newest first) or ``relevance`` (only with ``video_id``).
        search: Only threads containing this text.
        max_results: Threads per page, 1-100.
        page_token: ``next_page_token`` from a previous call.

    Returns:
        ``{"comments": [...], "next_page_token"}``. Each thread has the top-level
        comment, ``reply_count``, up to 5 ``replies``, ``owner_replied`` (the
        channel answered in those replies) and ``is_owner_comment``.

    Raises:
        InvalidRequestError: Comments are disabled on the video.
    """
    if order not in COMMENT_ORDERS:
        raise InvalidRequestError(f"order must be one of {', '.join(COMMENT_ORDERS)}; got {order!r}.")
    clamp(max_results, 1, 100, name="max_results")
    params: dict[str, Any] = {
        "part": "snippet,replies",
        "order": order,
        "maxResults": max_results,
        "textFormat": "plainText",
    }
    if order == "relevance" and not (video_id and video_id.strip()):
        raise InvalidRequestError(
            "order='relevance' only works for one video (pass video_id); YouTube rejects it for a whole channel. "
            "Use order='time' for channel-wide comments."
        )
    owner_id: str | None = None
    if video_id and video_id.strip():
        params["videoId"] = video_id.strip()
    else:
        owner_id = resolve_channel_id(client, channel)
        params["allThreadsRelatedToChannelId"] = owner_id
    if search:
        params["searchTerms"] = search
    if page_token:
        params["pageToken"] = page_token
    response = client.execute_comments(lambda service: service.commentThreads().list(**params))
    return {
        "comments": [_format_thread(item, owner_id) for item in response.get("items", [])],
        "next_page_token": response.get("nextPageToken"),
    }


@operation(requires_comment_access=True)
def get_comment_replies(
    client: YouTubeClient,
    comment_id: str,
    max_results: int = 50,
    page_token: str | None = None,
) -> dict[str, Any]:
    """All replies to one top-level comment (``thread_id`` from :func:`list_comments`).

    Args:
        client: The API client.
        comment_id: The top-level comment / thread ID.
        max_results: Replies per page, 1-100.
        page_token: ``next_page_token`` from a previous call.

    Returns:
        ``{"comment_id", "replies": [...], "next_page_token"}``, oldest first.
    """
    if not comment_id or not comment_id.strip():
        raise InvalidRequestError("comment_id must not be empty.")
    clamp(max_results, 1, 100, name="max_results")
    params: dict[str, Any] = {
        "part": "snippet",
        "parentId": comment_id.strip(),
        "maxResults": max_results,
        "textFormat": "plainText",
    }
    if page_token:
        params["pageToken"] = page_token
    response = client.execute_comments(lambda service: service.comments().list(**params))
    return {
        "comment_id": comment_id.strip(),
        "replies": [_format_comment(item) for item in response.get("items", [])],
        "next_page_token": response.get("nextPageToken"),
    }
