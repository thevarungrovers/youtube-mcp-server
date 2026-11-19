"""The ``youtube`` MCP server: read-only YouTube tools over stdio.

Run it with ``python -m mcp_server`` from the project root (or after
``pip install -e .`` from anywhere), or by absolute path::

    /path/to/youtube-mcp-server/.venv/bin/python /path/to/youtube-mcp-server/mcp_server/server.py

The server never opens a browser: if OAuth has not been set up it falls back
to the API key, and OAuth-only tools explain how to run ``cli.py auth``. A
token created while the server is running is picked up on the next call.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

# Launched by absolute path, sys.path[0] is this directory, not the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402

import youtube  # noqa: E402
from youtube import YouTubeClient, YouTubeError  # noqa: E402

SERVER_NAME = "youtube"

INSTRUCTIONS = """\
Read-only access to YouTube: channels, videos, playlists, search, and (with
OAuth) YouTube Analytics for the authenticated channel. Nothing here can
upload, edit, or delete.

Start with auth_status if unsure what works: an API key supports public data
only; analytics tools (get_channel_analytics, get_video_analytics,
get_top_videos, get_revenue, get_audience_insights, get_search_terms) need OAuth, set up by the user running
`python cli.py auth`.

Comments: list_comments reads public comments on one video or on a whole
channel (any channel, API key is enough).

Channels are given as a channel ID (UC...) or a handle (@name). Leave the
channel empty to mean the authenticated user's own channel (OAuth) or the
configured default (API key).

Dates are YYYY-MM-DD and inclusive. Analytics lags by 2-3 days.

QUOTA: the project has a daily quota (10,000 units by default). Most calls
cost 1 unit; search_videos costs ~100. Prefer list_channel_videos over
searching a channel. Errors begin with a code such as QUOTA_EXCEEDED,
OAUTH_REQUIRED, AUTH_ERROR, NOT_FOUND, or INVALID_REQUEST.
"""

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

mcp = MCPServer(name=SERVER_NAME, version=youtube.__version__, instructions=INSTRUCTIONS)

# One client for the server's lifetime; it resolves credentials lazily and
# reloads them when token.json changes.
client = YouTubeClient(interactive=False)

F = TypeVar("F", bound=Callable[..., Any])


def errors_reach_the_caller(fn: F) -> F:
    """Re-raise failures as ToolError, the only exception whose message the agent sees."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except YouTubeError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - converted, never swallowed
            raise ToolError(f"UNEXPECTED: {type(exc).__name__}: {exc}") from exc

    return wrapper  # type: ignore[return-value]


def _dates(start_date: str | None, end_date: str | None, days: int) -> tuple[str, str]:
    """Explicit dates win; otherwise the last ``days`` days ending today."""
    if start_date or end_date:
        if not (start_date and end_date):
            raise youtube.InvalidRequestError("Give both start_date and end_date, or neither (to use days).")
        return start_date, end_date
    return youtube.last_n_days(days)


Channel = Annotated[
    str | None,
    Field(description="Channel ID (UC...) or handle (@name). Omit for your own channel (OAuth) or the configured default."),
]
MaxResults = Annotated[int, Field(ge=1, le=50, description="Items per page, 1-50.")]
PageToken = Annotated[str | None, Field(description="next_page_token from a previous call, for the next page.")]
StartDate = Annotated[str | None, Field(description="Start date YYYY-MM-DD, inclusive. Omit both dates to use `days`.")]
EndDate = Annotated[str | None, Field(description="End date YYYY-MM-DD, inclusive.")]
Days = Annotated[int, Field(ge=1, le=3650, description="When no dates are given: the last N days ending today.")]


@mcp.tool(title="Show which credentials are available", annotations=READ_ONLY)
@errors_reach_the_caller
def auth_status() -> dict[str, Any]:
    """Which credentials are available (API key, OAuth token, both, or neither) and which tools work with them.

    Includes next steps for enabling anything unsupported. Never opens a browser.
    """
    client.reset()
    return youtube.auth_status()


@mcp.tool(title="Get channel overview", annotations=READ_ONLY)
@errors_reach_the_caller
def get_channel_info(channel: Channel = None) -> dict[str, Any]:
    """Channel name, description, subscriber count, video count, total views, and uploads playlist ID."""
    return youtube.get_channel_info(client, channel)


@mcp.tool(title="List a channel's videos", annotations=READ_ONLY)
@errors_reach_the_caller
def list_channel_videos(
    channel: Channel = None,
    max_results: MaxResults = 25,
    page_token: PageToken = None,
    include_stats: Annotated[bool, Field(description="Include views, likes, comments and duration.")] = True,
) -> dict[str, Any]:
    """A channel's uploaded videos, newest first, with basic stats. Paginated via next_page_token."""
    return youtube.list_channel_videos(
        client, channel, max_results=max_results, page_token=page_token, include_stats=include_stats
    )


@mcp.tool(title="Get video details", annotations=READ_ONLY)
@errors_reach_the_caller
def get_video_details(
    video_ids: Annotated[
        str | list[str],
        Field(description="One video ID, a comma-separated string of IDs, or a list of IDs (any number)."),
    ],
) -> dict[str, Any]:
    """Full details for one or more videos: title, description, views, likes, comment count, duration, publish date, tags, thumbnails.

    IDs that are deleted, private, or wrong are listed under not_found.
    """
    return youtube.get_video_details(client, video_ids)


@mcp.tool(title="Search YouTube videos", annotations=READ_ONLY)
@errors_reach_the_caller
def search_videos(
    query: Annotated[str, Field(description="Search keywords.")],
    max_results: Annotated[int, Field(ge=1, le=50, description="Results per page, 1-50.")] = 10,
    order: Annotated[
        str, Field(description="Sort order: relevance, date, viewCount, rating, or title.")
    ] = "relevance",
    published_after: Annotated[str | None, Field(description="Only videos published on/after this date (YYYY-MM-DD).")] = None,
    published_before: Annotated[str | None, Field(description="Only videos published on/before this date (YYYY-MM-DD).")] = None,
    region_code: Annotated[str | None, Field(description="ISO 3166-1 alpha-2 country code, e.g. US.")] = None,
    channel_id: Annotated[str | None, Field(description="Restrict results to this channel ID (UC...).")] = None,
    page_token: PageToken = None,
) -> dict[str, Any]:
    """Keyword search over public videos with date, order, region and channel filters. Costs ~100 quota units per call."""
    return youtube.search_videos(
        client,
        query,
        max_results=max_results,
        order=order,
        published_after=published_after,
        published_before=published_before,
        region_code=region_code,
        channel_id=channel_id,
        page_token=page_token,
    )


@mcp.tool(title="Compare channels", annotations=READ_ONLY)
@errors_reach_the_caller
def compare_channels(
    channels: Annotated[
        list[str], Field(description="1-10 channel IDs (UC...) or @handles; 'mine' for your own channel (OAuth).")
    ],
    recent_videos: Annotated[int, Field(ge=1, le=50, description="Latest uploads to sample per channel, 1-50.")] = 20,
) -> dict[str, Any]:
    """Benchmark channels side by side: subscribers, total views, and over their recent uploads the median views, engagement rate, upload frequency, share of Shorts and top video.

    Public data; about 3 quota units per channel. Good for competitor tracking.
    """
    return youtube.compare_channels(client, channels, recent_videos=recent_videos)


@mcp.tool(title="Get trending videos", annotations=READ_ONLY)
@errors_reach_the_caller
def get_trending_videos(
    region_code: Annotated[str, Field(description="ISO 3166-1 alpha-2 country code, e.g. CA.")] = "US",
    category_id: Annotated[
        str | None,
        Field(description="Video category ID, e.g. 26 Howto & Style, 22 People & Blogs, 19 Travel & Events. Omit for all."),
    ] = None,
    max_results: MaxResults = 25,
    page_token: PageToken = None,
) -> dict[str, Any]:
    """YouTube's most-popular videos in a country right now, optionally in one category, with stats. 1 quota unit."""
    return youtube.get_trending_videos(
        client, region_code=region_code, category_id=category_id, max_results=max_results, page_token=page_token
    )


@mcp.tool(title="List comments", annotations=READ_ONLY)
@errors_reach_the_caller
def list_comments(
    video_id: Annotated[str | None, Field(description="Comments on this video. Omit for comments on all of the channel's videos.")] = None,
    channel: Channel = None,
    order: Annotated[str, Field(description="time (newest first) or relevance.")] = "time",
    search: Annotated[str | None, Field(description="Only threads containing this text.")] = None,
    max_results: Annotated[int, Field(ge=1, le=100, description="Threads per page, 1-100.")] = 50,
    page_token: PageToken = None,
) -> dict[str, Any]:
    """Public comment threads on a video or on all of a channel's videos: text, author, likes, date, reply count, first replies.

    owner_replied tells whether the channel answered in the included replies, which helps find unanswered
    questions. Paginated via next_page_token; 1 quota unit per page. Held-for-review comments are not visible.
    """
    return youtube.list_comments(
        client, video_id=video_id, channel=channel, order=order, search=search,
        max_results=max_results, page_token=page_token,
    )


@mcp.tool(title="Get replies to a comment", annotations=READ_ONLY)
@errors_reach_the_caller
def get_comment_replies(
    comment_id: Annotated[str, Field(description="thread_id of a comment from list_comments.")],
    max_results: Annotated[int, Field(ge=1, le=100, description="Replies per page, 1-100.")] = 50,
    page_token: PageToken = None,
) -> dict[str, Any]:
    """All replies to one comment thread, for threads with more replies than list_comments includes."""
    return youtube.get_comment_replies(client, comment_id, max_results=max_results, page_token=page_token)


@mcp.tool(title="Get channel analytics (OAuth)", annotations=READ_ONLY)
@errors_reach_the_caller
def get_channel_analytics(
    start_date: StartDate = None,
    end_date: EndDate = None,
    days: Days = 28,
    granularity: Annotated[
        str, Field(description="total (one row), day, or month (start_date must be the 1st) for a time series.")
    ] = "total",
) -> dict[str, Any]:
    """Views, watch time (estimatedMinutesWatched), average view duration, subscribers gained/lost, likes, comments and shares for your channel.

    Requires OAuth; returns an OAUTH_REQUIRED error with setup steps otherwise.
    """
    start, end = _dates(start_date, end_date, days)
    return youtube.get_channel_analytics(client, start, end, granularity=granularity)


@mcp.tool(title="Get per-video analytics (OAuth)", annotations=READ_ONLY)
@errors_reach_the_caller
def get_video_analytics(
    video_id: Annotated[str, Field(description="ID of a video on your channel.")],
    start_date: StartDate = None,
    end_date: EndDate = None,
    days: Days = 28,
    sections: Annotated[
        list[str] | None,
        Field(description="Subset of: summary, traffic_sources, retention, demographics. Omit for all."),
    ] = None,
) -> dict[str, Any]:
    """Analytics for one video: summary metrics, traffic sources, audience retention curve, and viewer demographics.

    Requires OAuth; returns an OAUTH_REQUIRED error with setup steps otherwise.
    """
    start, end = _dates(start_date, end_date, days)
    return youtube.get_video_analytics(
        client, video_id, start, end, sections=sections or youtube.analytics.VIDEO_SECTIONS
    )


@mcp.tool(title="Get top-performing videos (OAuth)", annotations=READ_ONLY)
@errors_reach_the_caller
def get_top_videos(
    metric: Annotated[
        str,
        Field(description="views, watch_time, likes, comments, shares, subscribers, or engagement (likes+comments+shares)."),
    ] = "views",
    limit: Annotated[int, Field(ge=1, le=200, description="How many videos, 1-200.")] = 10,
    start_date: StartDate = None,
    end_date: EndDate = None,
    days: Days = 28,
) -> dict[str, Any]:
    """Your channel's top N videos by a metric over a date range, with titles and key metrics.

    Requires OAuth; returns an OAUTH_REQUIRED error with setup steps otherwise.
    """
    start, end = _dates(start_date, end_date, days)
    return youtube.get_top_videos(client, start, end, metric=metric, limit=limit)


@mcp.tool(title="Get revenue (OAuth, monetized channels)", annotations=READ_ONLY)
@errors_reach_the_caller
def get_revenue(
    start_date: StartDate = None,
    end_date: EndDate = None,
    days: Days = 28,
    granularity: Annotated[str, Field(description="total, day, or month.")] = "total",
    currency: Annotated[str, Field(description="ISO 4217 currency code, e.g. USD.")] = "USD",
) -> dict[str, Any]:
    """Estimated revenue, ad revenue, gross revenue and CPM for your channel.

    Returns available=false with the reason if the channel is not monetized or
    the token lacks the monetary scope. Requires OAuth.
    """
    start, end = _dates(start_date, end_date, days)
    return youtube.get_revenue(client, start, end, granularity=granularity, currency=currency)


@mcp.tool(title="Get audience insights (OAuth)", annotations=READ_ONLY)
@errors_reach_the_caller
def get_audience_insights(
    breakdowns: Annotated[
        list[str] | None,
        Field(
            description="Subset of: "
            + ", ".join(f"{k} ({v.description})" for k, v in youtube.insights.BREAKDOWNS.items())
            + ". Omit for: " + ", ".join(youtube.insights.DEFAULT_BREAKDOWNS) + "."
        ),
    ] = None,
    video_id: Annotated[str | None, Field(description="Narrow every breakdown to one video on your channel.")] = None,
    limit: Annotated[int, Field(ge=1, le=250, description="Rows per breakdown, 1-250 (embedding/external sites stop at 25).")] = 10,
    start_date: StartDate = None,
    end_date: EndDate = None,
    days: Days = 28,
) -> dict[str, Any]:
    """Who watches and how: countries, cities, devices, playback locations (incl. embeds on websites), traffic sources, subscribers vs not, Shorts vs long-form, sharing, cards.

    Each breakdown lists rows sorted by views with their share of the total. Requires OAuth.
    """
    start, end = _dates(start_date, end_date, days)
    return youtube.get_audience_insights(
        client, start, end, breakdowns=breakdowns or youtube.insights.DEFAULT_BREAKDOWNS, video_id=video_id, limit=limit
    )


@mcp.tool(title="Get YouTube search terms (OAuth)", annotations=READ_ONLY)
@errors_reach_the_caller
def get_search_terms(
    video_id: Annotated[str | None, Field(description="Only searches that led to this video. Omit for the whole channel.")] = None,
    limit: Annotated[int, Field(ge=1, le=25, description="How many terms, 1-25 (the API's maximum).")] = 25,
    start_date: StartDate = None,
    end_date: EndDate = None,
    days: Days = 28,
) -> dict[str, Any]:
    """The YouTube search terms viewers typed before watching your videos, with views and watch time per term.

    Useful for titles, descriptions and tags. Requires OAuth.
    """
    start, end = _dates(start_date, end_date, days)
    return youtube.get_search_terms(client, start, end, video_id=video_id, limit=limit)


@mcp.tool(title="List a channel's playlists", annotations=READ_ONLY)
@errors_reach_the_caller
def list_playlists(
    channel: Channel = None,
    max_results: MaxResults = 25,
    page_token: PageToken = None,
) -> dict[str, Any]:
    """A channel's playlists with title, description and item count. Paginated via next_page_token."""
    return youtube.list_playlists(client, channel, max_results=max_results, page_token=page_token)


@mcp.tool(title="List videos in a playlist", annotations=READ_ONLY)
@errors_reach_the_caller
def get_playlist_items(
    playlist_id: Annotated[str, Field(description="The playlist ID (PL..., UU..., etc.).")],
    max_results: MaxResults = 25,
    page_token: PageToken = None,
    include_stats: Annotated[bool, Field(description="Include views, likes, comments and duration.")] = False,
) -> dict[str, Any]:
    """Videos in a playlist, in playlist order, plus the playlist's own details on the first page. Paginated."""
    page = youtube.get_playlist_items(
        client, playlist_id, max_results=max_results, page_token=page_token, include_stats=include_stats
    )
    if not page_token:
        page["playlist"] = youtube.get_playlist_details(client, playlist_id)
    return page


def main() -> None:
    """Run the server over stdio."""
    mcp.run("stdio")


if __name__ == "__main__":
    main()
