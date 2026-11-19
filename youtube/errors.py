"""Exceptions raised by the YouTube wrapper, and translation of Google API errors.

Every exception carries a stable ``code`` (e.g. ``QUOTA_EXCEEDED``) so callers --
the CLI and the MCP server -- can show it as a prefix, and a message written for
the person who has to fix the problem: what went wrong and what to do next.
"""

from __future__ import annotations

import json
from typing import Any

from googleapiclient.errors import HttpError

AUTH_HINT = "Run `python cli.py auth` to set up OAuth."


class YouTubeError(Exception):
    """Base class for every error this package raises on purpose."""

    code = "YOUTUBE_ERROR"


class CredentialsNotFoundError(YouTubeError):
    """No usable credentials of any kind were found."""

    code = "NO_CREDENTIALS"


class OAuthRequiredError(YouTubeError):
    """The operation needs OAuth, but only an API key is available."""

    code = "OAUTH_REQUIRED"


class AuthError(YouTubeError):
    """Credentials exist but were rejected, expired, or lack permission."""

    code = "AUTH_ERROR"


class QuotaExceededError(YouTubeError):
    """The project's API quota or rate limit has been exhausted."""

    code = "QUOTA_EXCEEDED"


class NotFoundError(YouTubeError):
    """The requested channel, video, or playlist does not exist or is private."""

    code = "NOT_FOUND"


class InvalidRequestError(YouTubeError):
    """The request was malformed: bad argument, unsupported combination, etc."""

    code = "INVALID_REQUEST"


class APIError(YouTubeError):
    """Any other API failure, typically transient (5xx)."""

    code = "API_ERROR"


def oauth_required(operation: str) -> OAuthRequiredError:
    """Build the standard error for an OAuth-only operation called with an API key."""
    return OAuthRequiredError(
        f"'{operation}' requires OAuth authentication; only an API key is available. "
        f"{AUTH_HINT}"
    )


_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"}
_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
_NOT_FOUND_REASONS = {
    "notFound",
    "videoNotFound",
    "channelNotFound",
    "playlistNotFound",
    "playlistItemsNotAccessible",
    "channelClosed",
    "channelSuspended",
}


def _error_payload(exc: HttpError) -> tuple[str, list[str]]:
    """Pull the human message and the list of ``reason`` codes out of an HttpError."""
    message = ""
    reasons: list[str] = []
    try:
        body: Any = json.loads(exc.content.decode("utf-8") if exc.content else "{}")
    except (ValueError, UnicodeDecodeError):
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "")
        for item in error.get("errors") or []:
            if isinstance(item, dict) and item.get("reason"):
                reasons.append(str(item["reason"]))
        for item in error.get("details") or []:
            if isinstance(item, dict) and item.get("reason"):
                reasons.append(str(item["reason"]))
        if error.get("status"):
            reasons.append(str(error["status"]))
    elif isinstance(error, str):  # OAuth-style {"error": "invalid_grant"}
        reasons.append(error)
        message = str(body.get("error_description") or error)
    if not message:
        message = getattr(exc, "reason", "") or str(exc)
    return message, reasons


def translate_http_error(exc: HttpError, *, api: str = "YouTube Data API") -> YouTubeError:
    """Map a ``googleapiclient`` HttpError to the matching :class:`YouTubeError`.

    Args:
        exc: The error raised by ``request.execute()``.
        api: Which API was being called, used in the message.

    Returns:
        An exception instance (not raised) whose message says what to do next.
    """
    status = int(getattr(exc.resp, "status", 0) or 0)
    message, reasons = _error_payload(exc)
    reason_set = set(reasons)
    detail = f"{api} returned HTTP {status}: {message.rstrip('. ')}"

    if reason_set & _QUOTA_REASONS:
        return QuotaExceededError(
            f"{detail}. The daily quota for this Google Cloud project is used up; it "
            "resets at midnight Pacific Time. Check usage in the Cloud console under "
            "APIs & Services > Quotas, or request a higher quota. Note that a search "
            "costs 100 units while most reads cost 1."
        )
    if reason_set & _RATE_REASONS or status == 429:
        return QuotaExceededError(
            f"{detail}. Too many requests in a short period; wait a moment and retry."
        )
    if "keyInvalid" in reason_set or "API key not valid" in message:
        return AuthError(
            f"{detail}. The YOUTUBE_API_KEY in .env is not valid. Create a new key in "
            "the Cloud console (APIs & Services > Credentials) or remove it and use OAuth."
        )
    if "accessNotConfigured" in reason_set or "SERVICE_DISABLED" in reason_set:
        return AuthError(
            f"{detail}. Enable the {api} for your Google Cloud project "
            "(APIs & Services > Library), then retry."
        )
    if "commentsDisabled" in reason_set:
        return InvalidRequestError(f"{detail}. Comments are turned off for this video.")
    if status == 401:
        return AuthError(f"{detail}. The OAuth token was rejected. {AUTH_HINT}")
    if status == 403:
        hint = (
            "The credentials do not have permission for this data. Analytics is only "
            "available for channels the authenticated account owns or manages; revenue "
            "also requires a monetized channel and the yt-analytics-monetary scope."
        )
        if "insufficientPermissions" in reason_set or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in reason_set:
            hint = f"The OAuth token is missing a required scope. {AUTH_HINT}"
        return AuthError(f"{detail}. {hint}")
    if status == 404 or reason_set & _NOT_FOUND_REASONS:
        return NotFoundError(f"{detail}. Check the ID; private or deleted items are not visible.")
    if 400 <= status < 500:
        return InvalidRequestError(detail)
    return APIError(f"{detail}. This is usually temporary; retry shortly.")
