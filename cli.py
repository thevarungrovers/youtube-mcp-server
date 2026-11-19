#!/usr/bin/env python3
"""Command-line interface for manual testing of the read-only YouTube wrapper.

Examples::

    python cli.py auth                      # one-time OAuth setup (opens a browser)
    python cli.py auth-status
    python cli.py channel --channel @SomeHandle
    python cli.py videos --limit 10
    python cli.py video dQw4w9WgXcQ
    python cli.py search "python tutorial" --order viewCount --after 2025-01-01
    python cli.py analytics --start 2025-01-01 --end 2025-01-31
    python cli.py top --metric views --days 30

Results print as JSON; errors print to stderr with their code and exit 1.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

import click

import youtube
from youtube import YouTubeClient, YouTubeError
from youtube.analytics import GRANULARITIES, TOP_METRICS, VIDEO_SECTIONS
from youtube.insights import BREAKDOWNS, DEFAULT_BREAKDOWNS, MAX_SEARCH_TERMS
from youtube.videos import SEARCH_ORDERS

channel_option = click.option(
    "--channel", "-c", default=None, help="Channel ID (UC...) or @handle. Default: your channel (OAuth) or YOUTUBE_CHANNEL_ID."
)


def _emit(data: Any) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


def _run(fn: Callable[[YouTubeClient], Any]) -> None:
    """Build a client, call ``fn`` with it, print the result; turn errors into exit code 1."""
    try:
        _emit(fn(YouTubeClient(interactive=True)))
    except YouTubeError as exc:
        click.secho(f"{exc.code}: {exc}", fg="red", err=True)
        sys.exit(1)


def _range(start: str | None, end: str | None, days: int) -> tuple[str, str]:
    if start or end:
        if not (start and end):
            raise click.UsageError("Give both --start and --end, or neither (to use --days).")
        return start, end
    return youtube.last_n_days(days)


@click.group()
def cli() -> None:
    """Read-only YouTube Data & Analytics API tool."""


@cli.command()
@click.option("--no-browser", is_flag=True, help="Print the consent URL instead of opening a browser.")
def auth(no_browser: bool) -> None:
    """Run the OAuth flow and save token.json."""
    try:
        youtube.run_oauth_flow(open_browser=not no_browser)
        click.secho(f"Saved OAuth token to {youtube.auth.token_file()}", fg="green")
        info = youtube.get_channel_info(YouTubeClient(interactive=False))
        click.echo(f"Authenticated as channel: {info['title']} ({info['id']})")
    except YouTubeError as exc:
        click.secho(f"{exc.code}: {exc}", fg="red", err=True)
        sys.exit(1)


@cli.command("auth-status")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON.")
def auth_status_cmd(as_json: bool) -> None:
    """Show which credentials are available and what they support."""
    status = youtube.auth_status()
    if as_json:
        _emit(status)
        return
    yes_no = {True: click.style("yes", fg="green"), False: click.style("no", fg="yellow")}
    click.echo(f"API key (.env)         : {yes_no[status['api_key_present']]}")
    click.echo(f"client_secret.json     : {yes_no[status['client_secret_present']]}")
    click.echo(f"token.json             : {yes_no[status['token_present']]}")
    click.echo(f"OAuth token valid      : {yes_no[status['oauth_token_valid']]}")
    click.echo(f"Active mode            : {status['active_mode'] or click.style('none', fg='red')}")
    click.echo(f"\nSupported ({len(status['supported_operations'])}):")
    for name in status["supported_operations"]:
        click.echo(f"  + {name}")
    if status["unsupported_operations"]:
        click.echo(f"Unsupported ({len(status['unsupported_operations'])}):")
        for name in status["unsupported_operations"]:
            click.echo(f"  - {name}")
    for note in status["notes"]:
        click.echo(f"\nNote: {note}")
    for step in status["next_steps"]:
        click.echo(f"Next: {step}")


@cli.command()
@channel_option
def channel(channel: str | None) -> None:
    """Print channel info."""
    _run(lambda c: youtube.get_channel_info(c, channel))


@cli.command()
@channel_option
@click.option("--limit", "-n", default=10, show_default=True, type=click.IntRange(1, 50))
@click.option("--page-token", default=None, help="next_page_token from a previous run.")
def videos(channel: str | None, limit: int, page_token: str | None) -> None:
    """List a channel's recent videos."""
    _run(lambda c: youtube.list_channel_videos(c, channel, max_results=limit, page_token=page_token))


@cli.command()
@click.argument("video_ids", nargs=-1, required=True)
def video(video_ids: tuple[str, ...]) -> None:
    """Get details for one or more video IDs."""
    _run(lambda c: youtube.get_video_details(c, list(video_ids)))


@cli.command()
@click.argument("query")
@click.option("--limit", "-n", default=10, show_default=True, type=click.IntRange(1, 50))
@click.option("--order", default="relevance", show_default=True, type=click.Choice(SEARCH_ORDERS))
@click.option("--after", default=None, help="Published on/after YYYY-MM-DD.")
@click.option("--before", default=None, help="Published on/before YYYY-MM-DD.")
@click.option("--region", default=None, help="ISO country code, e.g. US.")
@click.option("--channel-id", default=None, help="Restrict to one channel ID.")
def search(
    query: str, limit: int, order: str, after: str | None, before: str | None, region: str | None, channel_id: str | None
) -> None:
    """Search videos by keyword (costs ~100 quota units)."""
    _run(
        lambda c: youtube.search_videos(
            c,
            query,
            max_results=limit,
            order=order,
            published_after=after,
            published_before=before,
            region_code=region,
            channel_id=channel_id,
        )
    )


@cli.command()
@click.option("--start", default=None, help="Start date YYYY-MM-DD.")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--days", default=28, show_default=True, type=click.IntRange(min=1), help="Used when no dates given.")
@click.option("--granularity", default="total", show_default=True, type=click.Choice(GRANULARITIES))
def analytics(start: str | None, end: str | None, days: int, granularity: str) -> None:
    """Channel analytics: views, watch time, subscribers (OAuth)."""
    start, end = _range(start, end, days)
    _run(lambda c: youtube.get_channel_analytics(c, start, end, granularity=granularity))


@cli.command("video-analytics")
@click.argument("video_id")
@click.option("--start", default=None, help="Start date YYYY-MM-DD.")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--days", default=28, show_default=True, type=click.IntRange(min=1))
@click.option("--section", "sections", multiple=True, type=click.Choice(VIDEO_SECTIONS), help="Repeatable. Default: all.")
def video_analytics(video_id: str, start: str | None, end: str | None, days: int, sections: tuple[str, ...]) -> None:
    """Per-video analytics: traffic sources, retention, demographics (OAuth)."""
    start, end = _range(start, end, days)
    _run(lambda c: youtube.get_video_analytics(c, video_id, start, end, sections=sections or VIDEO_SECTIONS))


@cli.command()
@click.option("--metric", default="views", show_default=True, type=click.Choice(list(TOP_METRICS)))
@click.option("--days", default=30, show_default=True, type=click.IntRange(min=1))
@click.option("--start", default=None, help="Start date YYYY-MM-DD (overrides --days).")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--limit", "-n", default=10, show_default=True, type=click.IntRange(1, 200))
def top(metric: str, days: int, start: str | None, end: str | None, limit: int) -> None:
    """Top videos by a metric (OAuth)."""
    start, end = _range(start, end, days)
    _run(lambda c: youtube.get_top_videos(c, start, end, metric=metric, limit=limit))


@cli.command()
@click.option("--start", default=None, help="Start date YYYY-MM-DD.")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--days", default=28, show_default=True, type=click.IntRange(min=1))
@click.option("--granularity", default="total", show_default=True, type=click.Choice(GRANULARITIES))
@click.option("--currency", default="USD", show_default=True)
def revenue(start: str | None, end: str | None, days: int, granularity: str, currency: str) -> None:
    """Estimated revenue, if the channel is monetized (OAuth)."""
    start, end = _range(start, end, days)
    _run(lambda c: youtube.get_revenue(c, start, end, granularity=granularity, currency=currency))


@cli.command()
@click.option("--breakdown", "-b", "breakdowns", multiple=True, type=click.Choice(list(BREAKDOWNS)),
              help=f"Repeatable. Default: {', '.join(DEFAULT_BREAKDOWNS)}.")
@click.option("--video", "video_id", default=None, help="Narrow to one video ID.")
@click.option("--limit", "-n", default=10, show_default=True, type=click.IntRange(1, 250), help="Rows per breakdown.")
@click.option("--start", default=None, help="Start date YYYY-MM-DD.")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--days", default=28, show_default=True, type=click.IntRange(min=1))
def insights(breakdowns: tuple[str, ...], video_id: str | None, limit: int, start: str | None, end: str | None, days: int) -> None:
    """Audience breakdowns: geography, devices, playback, traffic, subscribers, formats (OAuth)."""
    start, end = _range(start, end, days)
    _run(lambda c: youtube.get_audience_insights(
        c, start, end, breakdowns=breakdowns or DEFAULT_BREAKDOWNS, video_id=video_id, limit=limit
    ))


@cli.command("search-terms")
@click.option("--video", "video_id", default=None, help="Narrow to one video ID.")
@click.option("--limit", "-n", default=MAX_SEARCH_TERMS, show_default=True, type=click.IntRange(1, MAX_SEARCH_TERMS))
@click.option("--start", default=None, help="Start date YYYY-MM-DD.")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--days", default=28, show_default=True, type=click.IntRange(min=1))
def search_terms(video_id: str | None, limit: int, start: str | None, end: str | None, days: int) -> None:
    """YouTube search terms that led viewers to your videos (OAuth)."""
    start, end = _range(start, end, days)
    _run(lambda c: youtube.get_search_terms(c, start, end, video_id=video_id, limit=limit))


@cli.command()
@channel_option
@click.option("--limit", "-n", default=25, show_default=True, type=click.IntRange(1, 50))
def playlists(channel: str | None, limit: int) -> None:
    """List a channel's playlists."""
    _run(lambda c: youtube.list_playlists(c, channel, max_results=limit))


@cli.command()
@click.argument("playlist_id")
@click.option("--limit", "-n", default=25, show_default=True, type=click.IntRange(1, 50))
@click.option("--stats", is_flag=True, help="Include view/like counts.")
def playlist(playlist_id: str, limit: int, stats: bool) -> None:
    """List the videos in a playlist."""
    _run(
        lambda c: {
            "playlist": youtube.get_playlist_details(c, playlist_id),
            **youtube.get_playlist_items(c, playlist_id, max_results=limit, include_stats=stats),
        }
    )


if __name__ == "__main__":
    cli()
