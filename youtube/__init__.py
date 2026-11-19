"""Read-only Python wrapper for the YouTube Data API v3 and YouTube Analytics API v2.

Typical use::

    from youtube import YouTubeClient, get_channel_info, get_top_videos

    client = YouTubeClient()            # picks the best credentials available
    print(get_channel_info(client))     # works with an API key or OAuth
    print(get_top_videos(client, "2025-01-01", "2025-01-31", metric="views"))  # OAuth only

Every operation takes the client as its first argument and returns plain,
JSON-serialisable dicts. Failures raise a :class:`YouTubeError` subclass whose
message says how to fix the problem.
"""

from youtube.analytics import (
    get_channel_analytics,
    get_revenue,
    get_top_videos,
    get_video_analytics,
    last_n_days,
)
from youtube.auth import (
    AuthContext,
    AuthMode,
    auth_status,
    get_analytics_service,
    get_youtube_service,
    resolve_auth,
    run_oauth_flow,
)
from youtube.channels import get_channel_info, list_channel_videos
from youtube.client import YouTubeClient
from youtube.comments import get_comment_replies, list_comments
from youtube.errors import (
    APIError,
    AuthError,
    CredentialsNotFoundError,
    InvalidRequestError,
    NotFoundError,
    OAuthRequiredError,
    QuotaExceededError,
    YouTubeError,
)
from youtube.insights import get_audience_insights, get_search_terms
from youtube.operations import OPERATIONS
from youtube.playlists import get_playlist_details, get_playlist_items, list_playlists
from youtube.videos import get_video_details, get_video_statistics, search_videos

__all__ = [
    "APIError",
    "AuthContext",
    "AuthError",
    "AuthMode",
    "CredentialsNotFoundError",
    "InvalidRequestError",
    "NotFoundError",
    "OAuthRequiredError",
    "OPERATIONS",
    "QuotaExceededError",
    "YouTubeClient",
    "YouTubeError",
    "auth_status",
    "get_analytics_service",
    "get_audience_insights",
    "get_channel_analytics",
    "get_channel_info",
    "get_comment_replies",
    "get_playlist_details",
    "get_playlist_items",
    "get_revenue",
    "get_search_terms",
    "get_top_videos",
    "get_video_analytics",
    "get_video_details",
    "get_video_statistics",
    "get_youtube_service",
    "last_n_days",
    "list_channel_videos",
    "list_comments",
    "list_playlists",
    "resolve_auth",
    "run_oauth_flow",
    "search_videos",
]

__version__ = "0.1.0"
