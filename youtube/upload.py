"""Uploading videos -- the one part of this package that writes to YouTube.

Off by default: uploads only run when ``YOUTUBE_ALLOW_UPLOADS=true`` is set
in ``.env``. The privacy status comes only from ``YOUTUBE_UPLOAD_PRIVACY``
(``private`` by default, or ``unlisted`` / ``public``); callers, including
the MCP tool, cannot override it. Google keeps uploads from Cloud projects
that have not passed its API audit private regardless; when that happens the
result says so in ``notes``.

An upload costs about 1,600 quota units (of 10,000 a day by default).
"""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload

from youtube.auth import upload_privacy, uploads_enabled
from youtube.client import YouTubeClient
from youtube.errors import AUTH_HINT, AuthError, InvalidRequestError, UploadsDisabledError, YouTubeError, oauth_required
from youtube.operations import operation

MAX_TITLE = 100
MAX_DESCRIPTION = 5000
MAX_TAGS_TOTAL = 500
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024

#: 22 = People & Blogs, YouTube's default.
DEFAULT_CATEGORY = "22"

_CHUNK_SIZE = 8 * 1024 * 1024
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".wmv", ".flv", ".webm", ".mkv", ".mpeg", ".mpg", ".3gp"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _check_file(path: str | Path, suffixes: set[str], kind: str) -> Path:
    file = Path(path).expanduser()
    if not file.is_file():
        raise InvalidRequestError(f"{kind} not found: {file}")
    if file.suffix.lower() not in suffixes:
        raise InvalidRequestError(f"{kind} must be one of {', '.join(sorted(suffixes))}; got {file.name}.")
    return file


def _clean_tags(tags: str | list[str] | None) -> list[str]:
    raw = tags.split(",") if isinstance(tags, str) else list(tags or [])
    cleaned = [t.strip() for t in raw if t and t.strip()]
    # YouTube counts a tag containing a space as if it were quoted (+2 characters).
    total = sum(len(t) + (2 if " " in t else 0) for t in cleaned) + max(len(cleaned) - 1, 0)
    if total > MAX_TAGS_TOTAL:
        raise InvalidRequestError(f"Tags add up to {total} characters; YouTube allows {MAX_TAGS_TOTAL}.")
    return cleaned


@operation(requires_oauth=True, writes=True)
def upload_video(
    client: YouTubeClient,
    file_path: str | Path,
    title: str,
    description: str = "",
    tags: str | list[str] | None = None,
    category_id: str = DEFAULT_CATEGORY,
    made_for_kids: bool = False,
    thumbnail_path: str | Path | None = None,
    playlist_id: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Upload a video to the authenticated channel, with the privacy set in ``YOUTUBE_UPLOAD_PRIVACY``.

    Args:
        client: The API client (OAuth with an upload-capable scope).
        file_path: The video file on this machine.
        title: Up to 100 characters; no ``<`` or ``>``.
        description: Up to 5,000 characters.
        tags: A list, or a comma-separated string (500 characters in all).
        category_id: A video category ID (default 22, People & Blogs).
        made_for_kids: The audience declaration YouTube requires.
        thumbnail_path: Optional JPEG/PNG custom thumbnail, up to 2 MB (the
            channel must be verified for custom thumbnails).
        playlist_id: Optional playlist to add the video to.
        progress: Called with the fraction uploaded after each 8 MB chunk.

    Returns:
        ``{"video_id", "url", "studio_url", "requested_privacy", "privacy_status",
        "upload_status", "thumbnail_set", "playlist_added", "notes"}``.
        ``privacy_status`` is what YouTube applied; a mismatch with
        ``requested_privacy`` (e.g. an unaudited project) is explained in
        ``notes``. A failed thumbnail or playlist step is reported in ``notes``
        without failing the upload.

    Raises:
        UploadsDisabledError: ``YOUTUBE_ALLOW_UPLOADS`` is not on.
        AuthError: The OAuth token has no upload-capable scope.
        InvalidRequestError: Bad arguments, or an invalid ``YOUTUBE_UPLOAD_PRIVACY``.
    """
    if not uploads_enabled():
        raise UploadsDisabledError(
            "Uploads are turned off. Set YOUTUBE_ALLOW_UPLOADS=true in .env to allow uploads "
            "(restart the MCP server afterwards)."
        )
    if not client.auth.has_oauth:
        raise oauth_required("upload_video")
    if not client.auth.oauth_can_upload:
        raise AuthError(f"The OAuth token cannot upload: it was made with --read-only. {AUTH_HINT}")

    privacy = upload_privacy()
    video = _check_file(file_path, _VIDEO_SUFFIXES, "Video file")
    thumbnail = _check_file(thumbnail_path, _IMAGE_SUFFIXES, "Thumbnail") if thumbnail_path else None
    if thumbnail and thumbnail.stat().st_size > MAX_THUMBNAIL_BYTES:
        raise InvalidRequestError(f"Thumbnail must be 2 MB or smaller; {thumbnail.name} is larger.")
    title = (title or "").strip()
    if not title:
        raise InvalidRequestError("title must not be empty.")
    if len(title) > MAX_TITLE or any(c in title for c in "<>"):
        raise InvalidRequestError(f"title must be at most {MAX_TITLE} characters, without < or >.")
    if len(description) > MAX_DESCRIPTION or any(c in description for c in "<>"):
        raise InvalidRequestError(f"description must be at most {MAX_DESCRIPTION} characters, without < or >.")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": _clean_tags(tags),
            "categoryId": str(category_id),
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids)},
    }
    media = MediaFileUpload(
        str(video),
        mimetype=mimetypes.guess_type(video.name)[0] or "application/octet-stream",
        chunksize=_CHUNK_SIZE,
        resumable=True,
    )
    request = client.data.videos().insert(
        part="snippet,status", body=body, media_body=media, notifySubscribers=False
    )
    response = client.execute_resumable(request, progress=progress)
    video_id = response["id"]

    notes: list[str] = []
    thumbnail_set = False
    if thumbnail:
        try:
            client.execute(
                client.data.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumbnail), mimetype=mimetypes.guess_type(thumbnail.name)[0]),
                )
            )
            thumbnail_set = True
        except YouTubeError as exc:
            notes.append(f"Thumbnail not set ({exc.code}: {exc}). Custom thumbnails need a verified channel.")
    playlist_added = False
    if playlist_id:
        try:
            client.execute(
                client.data.playlistItems().insert(
                    part="snippet",
                    body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
                )
            )
            playlist_added = True
        except YouTubeError as exc:
            notes.append(f"Not added to playlist {playlist_id} ({exc.code}: {exc}).")

    status = response.get("status", {})
    applied = status.get("privacyStatus")
    if applied and applied != privacy:
        notes.append(
            f"Requested {privacy} but YouTube set it to {applied}. Google keeps uploads from Cloud projects "
            "that have not passed its API audit private; change it in YouTube Studio or complete the audit."
        )
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "title": response.get("snippet", {}).get("title", title),
        "requested_privacy": privacy,
        "privacy_status": applied,
        "upload_status": status.get("uploadStatus"),
        "thumbnail_set": thumbnail_set,
        "playlist_added": playlist_added,
        "notes": notes,
    }
