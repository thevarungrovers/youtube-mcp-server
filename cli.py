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
import os
import sys
from collections.abc import Callable
from typing import Any

import click

import youtube
from youtube import YouTubeClient, YouTubeError
from youtube.analytics import GRANULARITIES, TOP_METRICS, VIDEO_SECTIONS
from youtube.comments import COMMENT_ORDERS
from youtube.export import DATASETS, FORMATS, export_dataset, write_rows
from youtube.insights import BREAKDOWNS, DEFAULT_BREAKDOWNS, MAX_SEARCH_TERMS
from youtube.reporting import parse_report, save_report
from youtube.reports import PERIODS, post_webhook
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


def _can_prompt() -> bool:
    """True when a person is at the terminal to answer a question (not cron, not a pipe)."""
    return sys.stdin.isatty()


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
@click.option(
    "--with-comments/--read-only", default=None,
    help="Grant (or skip) the scope Google requires to read comments over OAuth; it can also edit and delete, "
    "and this tool never does. Default: read-only if YOUTUBE_API_KEY is set (comments use the key), "
    "otherwise ask.",
)
def auth(no_browser: bool, with_comments: bool | None) -> None:
    """Run the OAuth flow and save token.json. Checks for YOUTUBE_API_KEY to decide how comments are read."""
    has_key = youtube.auth.api_key() is not None
    if with_comments is None:
        if has_key:
            click.echo("YOUTUBE_API_KEY found: signing in read-only; comments will use the key.")
            with_comments = False
        else:
            click.echo(
                "No YOUTUBE_API_KEY in .env, so comments can't be read with a read-only login.\n"
                "Google only allows reading comments over OAuth with a scope that can also edit and delete\n"
                "(this tool never does). Alternatively, add an API key to .env and run this again."
            )
            with_comments = _can_prompt() and click.confirm("Grant comment access to this login?", default=False)
    try:
        youtube.run_oauth_flow(open_browser=not no_browser, with_comments=with_comments)
        click.secho(f"Saved OAuth token to {youtube.auth.token_file()}", fg="green")
        client = YouTubeClient(interactive=False)
        info = youtube.get_channel_info(client)
        click.echo(f"Authenticated as channel: {info['title']} ({info['id']})")
        if client.auth.oauth_reads_comments:
            click.echo("Comments: read with this login.")
        elif has_key:
            click.echo("Comments: read with YOUTUBE_API_KEY.")
        else:
            click.secho("Comments: unavailable (no API key, comment access not granted).", fg="yellow")
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


webhook_option = click.option(
    "--webhook", default=lambda: os.environ.get("YOUTUBE_REPORT_WEBHOOK"), show_default="$YOUTUBE_REPORT_WEBHOOK",
    help="Also post the text to this Slack-compatible incoming webhook URL.",
)


def _deliver(text: str, out: str | None, webhook: str | None) -> None:
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        click.secho(f"Wrote {out}", fg="green", err=True)
    else:
        click.echo(text)
    if webhook:
        post_webhook(webhook, text)
        click.secho("Posted to webhook", fg="green", err=True)


@cli.command()
@click.option("--period", default="last_week", show_default=True, type=click.Choice(PERIODS))
@click.option("--start", default=None, help="Start date YYYY-MM-DD (with --end, overrides --period).")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--top", "top_n", default=5, show_default=True, type=click.IntRange(1, 25), help="Top videos to include.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON instead of Markdown.")
@click.option("--out", default=None, help="Write to this file instead of stdout.")
@webhook_option
def report(period: str, start: str | None, end: str | None, top_n: int, as_json: bool, out: str | None, webhook: str | None) -> None:
    """Channel performance report vs the previous period (OAuth)."""
    if start or end:
        start, end = _range(start, end, 28)
    else:
        start, end = youtube.period_dates(period)
    try:
        data = youtube.build_report(YouTubeClient(interactive=True), start, end, top_n=top_n)
        _deliver(json.dumps(data, indent=2, ensure_ascii=False) + "\n" if as_json else youtube.render_markdown(data), out, webhook)
    except YouTubeError as exc:
        click.secho(f"{exc.code}: {exc}", fg="red", err=True)
        sys.exit(1)


@cli.command()
@click.option("--days", default=14, show_default=True, type=click.IntRange(1, 90), help="Recent days to check.")
@click.option("--baseline", "baseline_days", default=28, show_default=True, type=click.IntRange(7, 180))
@click.option("--threshold", default=2.0, show_default=True, type=click.FloatRange(min=1, min_open=True))
@webhook_option
def alerts(days: int, baseline_days: int, threshold: float, webhook: str | None) -> None:
    """Spikes, drops and subscriber losses in recent days (OAuth). Posts to the webhook only when something is found."""
    try:
        data = youtube.detect_anomalies(YouTubeClient(interactive=True), days=days, baseline_days=baseline_days, threshold=threshold)
        _emit(data)
        found = data["anomalies"] or data["subscriber_alerts"]
        if webhook and found:
            lines = [f"YouTube alerts {data['checked']['start']} to {data['checked']['end']}:"]
            lines += [f"- {a['day']}: views {a['kind']} ({a['views']:,} vs usual {a['baseline_median']:,.0f})" for a in data["anomalies"]]
            lines += [f"- {a['day']}: net subscribers {a['net_subscribers']:+}" for a in data["subscriber_alerts"]]
            post_webhook(webhook, "\n".join(lines))
            click.secho("Posted to webhook", fg="green", err=True)
    except YouTubeError as exc:
        click.secho(f"{exc.code}: {exc}", fg="red", err=True)
        sys.exit(1)


@cli.command()
@click.option("--dataset", "-d", "datasets", multiple=True, type=click.Choice(list(DATASETS)), help="Repeatable. Default: all.")
@click.option("--start", default=None, help="Start date YYYY-MM-DD.")
@click.option("--end", default=None, help="End date YYYY-MM-DD.")
@click.option("--days", default=28, show_default=True, type=click.IntRange(min=1), help="Used when no dates given.")
@click.option("--format", "fmt", default="csv", show_default=True, type=click.Choice(FORMATS))
@click.option("--out-dir", default="exports", show_default=True, help="Directory for the files.")
def export(datasets: tuple[str, ...], start: str | None, end: str | None, days: int, fmt: str, out_dir: str) -> None:
    """Write daily datasets as CSV or JSON Lines, named <dataset>_<start>_<end>.<format>."""
    start, end = _range(start, end, days)
    client = YouTubeClient(interactive=True)
    failed = False
    for name in datasets or DATASETS:
        try:
            rows = export_dataset(client, name, start, end)
        except YouTubeError as exc:
            click.secho(f"{name}: {exc.code}: {exc}", fg="red", err=True)
            failed = True
            continue
        path = write_rows(rows, f"{out_dir}/{name}_{start}_{end}.{fmt}", fmt)
        click.echo(f"{name}: {len(rows)} rows -> {path}")
    if failed:
        sys.exit(1)


@cli.command()
@click.argument("channels", nargs=-1, required=True)
@click.option("--recent", default=20, show_default=True, type=click.IntRange(1, 50), help="Latest uploads to sample per channel.")
def compare(channels: tuple[str, ...], recent: int) -> None:
    """Compare channels side by side (IDs or @handles; 'mine' for yours)."""
    _run(lambda c: youtube.compare_channels(c, list(channels), recent_videos=recent))


@cli.command()
@click.option("--region", default="US", show_default=True, help="ISO country code, e.g. CA.")
@click.option("--category", default=None, help="Video category ID, e.g. 26 (Howto & Style).")
@click.option("--limit", "-n", default=25, show_default=True, type=click.IntRange(1, 50))
def trending(region: str, category: str | None, limit: int) -> None:
    """YouTube's most-popular videos in a country."""
    _run(lambda c: youtube.get_trending_videos(c, region_code=region, category_id=category, max_results=limit))


@cli.command()
@click.option("--video", "video_id", default=None, help="Comments on this video ID (default: all of the channel's videos).")
@channel_option
@click.option("--order", default="time", show_default=True, type=click.Choice(COMMENT_ORDERS))
@click.option("--search", default=None, help="Only threads containing this text.")
@click.option("--limit", "-n", default=20, show_default=True, type=click.IntRange(1, 100))
@click.option("--page-token", default=None, help="next_page_token from a previous run.")
def comments(
    video_id: str | None, channel: str | None, order: str, search: str | None, limit: int, page_token: str | None
) -> None:
    """List public comment threads on a video or a channel."""
    _run(lambda c: youtube.list_comments(
        c, video_id=video_id, channel=channel, order=order, search=search, max_results=limit, page_token=page_token
    ))


@cli.command()
@click.argument("comment_id")
@click.option("--limit", "-n", default=50, show_default=True, type=click.IntRange(1, 100))
def replies(comment_id: str, limit: int) -> None:
    """List all replies to a comment thread."""
    _run(lambda c: youtube.get_comment_replies(c, comment_id, max_results=limit))


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


@cli.group()
def reporting() -> None:
    """Bulk daily CSV reports from the YouTube Reporting API (OAuth)."""


@reporting.command("types")
def reporting_types() -> None:
    """List the report types available to your channel."""
    _run(youtube.list_report_types)


@reporting.command("jobs")
def reporting_jobs() -> None:
    """List your scheduled report jobs."""
    _run(youtube.list_reporting_jobs)


@reporting.command("create-job")
@click.argument("report_type_id")
@click.option("--name", default=None, help="Label for the job (default: the type ID).")
def reporting_create_job(report_type_id: str, name: str | None) -> None:
    """Schedule daily reports of one type (e.g. channel_reach_basic_a1). First reports in ~48h."""
    _run(lambda c: youtube.create_reporting_job(c, report_type_id, name=name))


@reporting.command("reports")
@click.argument("job_id")
@click.option("--created-after", default=None, help="Only reports created after this RFC 3339 time.")
def reporting_reports(job_id: str, created_after: str | None) -> None:
    """List the reports a job has produced, newest first."""
    _run(lambda c: youtube.list_reports(c, job_id, created_after=created_after))


@reporting.command("download")
@click.argument("job_id")
@click.option("--latest", default=1, show_default=True, type=click.IntRange(1, 60), help="How many of the newest reports.")
@click.option("--out-dir", default="exports/reporting", show_default=True)
def reporting_download(job_id: str, latest: int, out_dir: str) -> None:
    """Download a job's newest reports as <job>_<day>.csv."""
    try:
        client = YouTubeClient(interactive=True)
        reports = youtube.list_reports(client, job_id)["reports"][:latest]
        if not reports:
            click.echo("No reports yet. New jobs produce their first reports within about 48 hours.")
            return
        for report in reports:
            data = youtube.download_report(client, report["download_url"])
            day = (report["start_time"] or "unknown")[:10]
            path = save_report(data, f"{out_dir}/{job_id}_{day}.csv")
            click.echo(f"{day}: {len(parse_report(data))} rows -> {path}")
    except YouTubeError as exc:
        click.secho(f"{exc.code}: {exc}", fg="red", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
