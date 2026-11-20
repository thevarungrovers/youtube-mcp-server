# YouTube MCP Server

A read-only Python toolkit for the **YouTube Data API v3**, **YouTube Analytics API v2** and **YouTube Reporting API**:

- **`youtube/`**: a typed Python library covering channels, videos, search, playlists, comments, analytics, audience insights, revenue, channel comparison, reports and alerts, data export, and bulk reports
- **`mcp_server/`**: a [Model Context Protocol](https://modelcontextprotocol.io) server with 19 read-only tools (20 with uploads on), so AI agents (Claude Desktop, Claude Code, …) can use all of this
- **`cli.py`**: a command-line interface for setup, manual checks, exports and scheduled jobs

Everything is **read-only by default**: nothing edits or deletes. Two opt-in exceptions:
- **Uploads** ([Uploading](#uploading-opt-in)): off unless `YOUTUBE_ALLOW_UPLOADS=true`; private unless `YOUTUBE_UPLOAD_PRIVACY` says otherwise.
- `cli.py reporting create-job`: schedules Google-generated reports and does not touch the channel.

The default login includes a comments scope Google ties to write access; see [Comments](#comments).

## How authentication works

The library uses the best credentials it can find, in this order:

| # | What exists | What happens | Supports |
|---|-------------|--------------|----------|
| 1 | `token.json`, valid | Used as-is | Everything |
| 2 | `token.json`, expired | Refreshed automatically and saved | Everything |
| 3 | `client_secret.json`, no token | OAuth browser flow runs, token saved to `token.json` (CLI only — the MCP server never opens a browser) | Everything |
| 4 | `YOUTUBE_API_KEY` in `.env` | API key used | Public data only — no analytics |
| 5 | Nothing | Clear error listing what to set up | — |

If OAuth can't be used (say the refresh token was revoked) and an API key exists, the library falls back to the key **and says why**. Analytics operations called with only an API key fail immediately with:

```
OAUTH_REQUIRED: 'get_top_videos' requires OAuth authentication; only an API key is available. Run `python cli.py auth` to set up OAuth.
```

Run `python cli.py auth-status` at any time to see what's available and which operations work.

## Setup

### 1. Install

Python 3.10+.

```bash
git clone <this repo> youtube-mcp-server && cd youtube-mcp-server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Create a Google Cloud project

In the [Google Cloud console](https://console.cloud.google.com/):

1. Create a project, or select an existing one.
2. **APIs & Services → Library**: enable **YouTube Data API v3** and **YouTube Analytics API** (and **YouTube Reporting API** if you want bulk reports).

### 3. Configure the OAuth consent screen

Go to **Google Auth Platform** (older consoles: **APIs & Services → OAuth consent screen**).

1. **Branding**: set an app name and support email.
2. **Audience → User type**: choose **External**. If it shows Internal, click **Make external**.
3. **Audience → Test users**: add the Google account you will sign in with.
4. **Audience → Publishing status**: click **Publish app** and confirm. Do not submit for verification.

Publish it, because in *Testing* the login expires every 7 days (an AI agent can't sign in again on its own), and signing in as a Brand Account channel is usually refused. A published but unverified app works fine for this tool: you click past a warning when signing in (step 5), and it is limited to 100 users.

### 4. Create the OAuth client

1. **Google Auth Platform → Clients → Create client** (or **APIs & Services → Credentials → Create credentials → OAuth client ID**).
2. Application type: **Desktop app**.
3. Download the JSON and save it as **`client_secret.json`** in the project root.

### 5. Sign in

```bash
python cli.py auth                # opens a browser
python cli.py auth --no-browser   # prints the URL instead
python cli.py auth --read-only    # without comment access (see Comments)
```

1. Sign in with the Google account that owns or manages the channel.
2. If Google says **"Google hasn't verified this app"**, click **Advanced → Go to (app name)**.
3. **Choose the account:** Google may list your personal profile *and* the channels you manage (Brand Account channels are labelled *YouTube*). **Use the account that you want to connect.**
4. Accept the permissions (read-only, plus comment access unless `--read-only`; see [Comments](#comments)).
5. The command prints the connected channel. Confirm it is the right one, then run:

```bash
python cli.py auth-status
```

The token is saved to `token.json`. "My channel" means the channel you picked, everywhere. To switch channels, delete `token.json` and run `python cli.py auth` again.

Analytics needs a role on the channel that can view analytics (Manager or Owner). Revenue also needs a monetized channel.

### 6. API key (optional)

A fallback for comments (see [Comments](#comments)), and for public data without OAuth.

1. **APIs & Services → Credentials → Create credentials → API key**.
2. **Edit API key**:
   - **Application restrictions:** leave **None**. *Websites* only suits browser use, and *IP addresses* breaks when your IP changes.
   - **API restrictions:** **Restrict key** → tick only **YouTube Data API v3** → **Save**. A leaked key can then only read public YouTube data.
3. Add it to `.env`:
   ```bash
   cp .env.example .env
   # edit .env: YOUTUBE_API_KEY=...
   ```

With only an API key there is no "my channel": pass `--channel UC...` / `@handle`, or set `YOUTUBE_CHANNEL_ID` in `.env`. Analytics is not available.

`client_secret.json`, `token.json` and `.env` are gitignored. Never commit them.

### Troubleshooting sign-in

| Error | Fix |
|-------|-----|
| `Error 403: org_internal` | The consent screen is **Internal**. **Audience → Make external**, then sign in again. If External is blocked by an organization policy, ask your Workspace admin, or create the Cloud project under a personal Google account. |
| `Error 403: access_denied` ("can only be accessed by developer-approved testers") | Add your account under **Audience → Test users**. If it is already listed, or the error appears after picking a Brand Account channel, **publish the app** (step 3.4). Then delete `token.json` and sign in again. |
| "Google hasn't verified this app" | Normal. Click **Advanced → Go to (app name)**. |
| "could not be refreshed" | The login expired or was revoked. Run `python cli.py auth`. If it happens every 7 days, the app is still in *Testing*: publish it. |
| A CLI command unexpectedly opens a Google sign-in | Same cause: the saved login could not be refreshed, so the CLI signs in again (the MCP server never does). Pick the same channel. |

**Scopes requested:** `youtube.readonly`, `yt-analytics.readonly`, `yt-analytics-monetary.readonly` (read-only), plus `youtube.force-ssl` for comments unless `--read-only` (see [Comments](#comments)).

### Comments

Comments are read with **OAuth first, then the API key**:

1. **OAuth.** Google only lets OAuth read comments with `youtube.force-ssl`, so `python cli.py auth` requests it. That scope *could* also edit and delete on the channel; this tool never does, but treat `token.json` accordingly.
2. **API key.** If the login has no comment access (made with `--read-only`), or Google refuses the OAuth call, comments fall back to `YOUTUBE_API_KEY` (step 6).

For a strictly read-only token, sign in with `--read-only` and set an API key.

Limits:
- `order=relevance` works only for one video. YouTube rejects it for a whole channel, so channel-wide comments are newest first (`time`). The tool returns a clear `INVALID_REQUEST` instead of Google's opaque 400.
- Comments held for review, or on private videos, are not returned.
- Each page of up to 100 threads costs 1 quota unit. A thread includes up to 5 replies; `get_comment_replies` fetches the rest.

### Optional settings (`.env`)

| Variable | Purpose |
|----------|---------|
| `YOUTUBE_API_KEY` | API key for public read-only calls |
| `YOUTUBE_CHANNEL_ID` | Default channel (ID or `@handle`) when only an API key is set |
| `YOUTUBE_CLIENT_SECRET_FILE` | Path to the OAuth client JSON (default `client_secret.json`) |
| `YOUTUBE_TOKEN_FILE` | Where to store the OAuth token (default `token.json`) |
| `YOUTUBE_ALLOW_UPLOADS` | `true` to allow uploads and add the `upload_video` MCP tool (off by default) |
| `YOUTUBE_UPLOAD_PRIVACY` | `private` (default), `unlisted` or `public` for every upload |

Relative paths are resolved against the project root, so the server works no matter which directory it's launched from.

## CLI

```bash
python cli.py auth                                   # OAuth flow
python cli.py auth-status                            # what works with current credentials
python cli.py channel [--channel @handle]            # channel info
python cli.py videos [--channel UC...] [-n 10]       # recent uploads
python cli.py video VIDEO_ID [VIDEO_ID ...]          # video details
python cli.py search "query" [--order viewCount] [--after 2025-01-01] [--before 2025-03-31] [--region US]
python cli.py analytics --start 2025-01-01 --end 2025-01-31 [--granularity day]   # OAuth
python cli.py video-analytics VIDEO_ID --days 28 [--section retention]            # OAuth
python cli.py top --metric views --days 30 [-n 10]   # OAuth; metrics: views, watch_time, likes, comments, shares, subscribers, engagement
python cli.py revenue --days 28                      # OAuth, monetized channels
python cli.py insights -b countries -b devices [--video VIDEO_ID] [-n 10]          # OAuth; see --help for all breakdowns
python cli.py search-terms --days 90 [--video VIDEO_ID]                          # OAuth
python cli.py comments [--video VIDEO_ID | --channel @handle] [--search text] [--order relevance (one video only)]   # OAuth, or API key
python cli.py replies THREAD_ID                                                                  # OAuth, or API key
python cli.py report --period last_week [--out report.md]   # OAuth; or --start/--end, --json
python cli.py alerts --days 14 [--threshold 2]              # OAuth
python cli.py export [-d channel_daily -d video_daily ...] --days 28 [--format jsonl] [--out-dir exports]   # OAuth
python cli.py compare mine @OtherChannel @AnotherOne [--recent 20]
python cli.py trending --region CA [--category 26]
python cli.py playlists [--channel @handle]
python cli.py playlist PLAYLIST_ID [--stats]
python cli.py upload clip.mp4 --title "..." [--description-file d.txt] [--tags a,b] [--thumbnail t.jpg] [--playlist ID]   # needs YOUTUBE_ALLOW_UPLOADS; privacy from YOUTUBE_UPLOAD_PRIVACY
```

Output is JSON (`report` prints Markdown). Errors go to stderr prefixed with a code and exit with status 1.

### Exporting data

`export` writes flat daily datasets, one file each, named `<dataset>_<start>_<end>.<csv|jsonl>`, ready for a spreadsheet, warehouse or BI tool:

| Dataset | Rows |
|---------|------|
| `channel_daily` | Channel totals per day: views, watch time, subscribers, likes, comments, shares |
| `video_daily` | Per video per day, for every upload |
| `traffic_daily` | Per day and traffic source |
| `device_daily` | Per day and device type |
| `content_type_daily` | Per day, Shorts vs long-form |
| `subscribed_daily` | Per day, subscribers vs not |
| `videos` | Every upload with its current views, likes and comments (a snapshot) |

Run it daily for the last few days and upsert on `day` (+ the breakdown column): recent days keep changing until analytics settles.

### Uploading (opt-in)

Uploads are **off by default**. To turn them on, add `YOUTUBE_ALLOW_UPLOADS=true` to `.env` (and restart the MCP server). Then:

```bash
python cli.py upload clip.mp4 --title "Rooftop harvest" --description-file description.txt --tags "farm,harvest"
```

- **Privacy** comes only from `YOUTUBE_UPLOAD_PRIVACY` in `.env`: `private` (default), `unlisted` or `public`. Neither the CLI nor the agent can override it, and the CLI warns before a non-private upload. `auth_status` shows the current value.
- **Google's audit:** until the Cloud project passes the *YouTube API Services audit*, YouTube stores every upload as private, whatever you request. The result then shows `requested_privacy` vs the applied `privacy_status` with a note; publish in YouTube Studio (the result includes the Studio link).
- It needs the default login (`python cli.py auth`); a `--read-only` login can't upload.
- Large files upload in resumable 8 MB chunks with a progress bar.
- A thumbnail or playlist that fails is reported in `notes` without failing the upload. Custom thumbnails need a verified channel.
- Each upload costs about **1,600 quota units**, so roughly 6 a day on the default quota.

With uploads on, the MCP server also offers an `upload_video` tool (same rules: privacy from `.env`, a file on the server's machine). It is the only tool not marked read-only.

### Bulk reports (YouTube Reporting API)

For long history, or data the Analytics API doesn't offer (such as thumbnail **impressions and click-through rate**, in `channel_reach_basic_a1`), schedule a Reporting API job. Google then writes one CSV per day and keeps each for 60 days. Enable **YouTube Reporting API** in the Cloud project first.

```bash
python cli.py reporting types                                # what's available
python cli.py reporting create-job channel_reach_basic_a1    # once per type; first reports in ~48h
python cli.py reporting jobs
python cli.py reporting download JOB_ID --latest 7           # -> exports/reporting/<job>_<day>.csv
```

Creating a job is the only call in this project that changes anything: it schedules report generation for the channel and never touches videos or the channel itself. It is CLI-only, not an MCP tool.

### Scheduled reports

`report` and `alerts` run fine from cron. For example, a report file every Monday at 9:00 and alerts every morning:

```cron
0 9 * * 1  cd /path/to/youtube-mcp-server && .venv/bin/python cli.py report --period last_week --out reports/latest.md
30 8 * * *  cd /path/to/youtube-mcp-server && .venv/bin/python cli.py alerts --days 3 > reports/alerts.json
```

These need a working OAuth login. Publish the consent screen (setup step 3), or the login expires every 7 days and the jobs fail with `AUTH_ERROR`.

## MCP server

### Tools

| Tool | Needs | Description |
|------|:-----:|-------------|
| `auth_status` | | Which credentials are available and which tools work |
| `get_channel_info` | | Channel name, description, subscriber/video/view counts |
| `list_channel_videos` | | A channel's uploads with basic stats (paginated) |
| `get_video_details` | | Full details for one or more video IDs |
| `search_videos` | | Keyword search with date, order, region and channel filters |
| `list_playlists` | | A channel's playlists |
| `get_playlist_items` | | Videos in a playlist |
| `compare_channels` | | Benchmark up to 10 channels: subscribers, median views, engagement rate, upload frequency, share of Shorts |
| `get_trending_videos` | | YouTube's most-popular chart for a country, optionally one category |
| `get_channel_report` | ✓ | Ready-made report: totals and change vs the previous period, top videos, audience, searches (JSON + Markdown) |
| `detect_anomalies` | ✓ | Days with unusual views (spikes/drops) or subscriber losses |
| `get_channel_analytics` | ✓ | Views, watch time, subscribers gained/lost over a date range |
| `get_video_analytics` | ✓ | Per-video traffic sources, audience retention, demographics |
| `get_top_videos` | ✓ | Top N videos by a metric over a date range |
| `get_revenue` | ✓ | Estimated revenue and CPM (monetized channels only) |
| `get_audience_insights` | ✓ | Countries, cities, devices, playback locations and embedding sites, traffic sources and referring sites, subscribers vs not, Shorts vs long-form, sharing, cards |
| `get_search_terms` | ✓ | The YouTube search terms that led viewers to your videos |
| `list_comments` | key* | Public comment threads on a video or a whole channel, with whether the channel replied |
| `get_comment_replies` | key* | All replies to one comment thread |
| `upload_video` | ✓ | Upload a file; privacy set by `YOUTUBE_UPLOAD_PRIVACY` (default private). Only listed when `YOUTUBE_ALLOW_UPLOADS=true` (see [Uploading](#uploading-opt-in)) |

✓ = OAuth. key* = OAuth with comment access, falling back to `YOUTUBE_API_KEY` (see [Comments](#comments)).

Every tool returns structured JSON, is annotated read-only (except `upload_video`), and documents each parameter. Analytics tools accept `start_date`/`end_date` (YYYY-MM-DD) or `days` (default 28). Errors reach the agent with a stable prefix: `NO_CREDENTIALS`, `OAUTH_REQUIRED`, `AUTH_ERROR`, `QUOTA_EXCEEDED`, `NOT_FOUND`, `INVALID_REQUEST`, `API_ERROR`.

The server **never opens a browser**. Run `python cli.py auth` once in a terminal; if you do this while the server is running, it picks up the new token on its next call. Changes to `.env` (such as adding `YOUTUBE_API_KEY`) are read at startup, so restart or reconnect the server after editing it (in Claude Code: `/mcp` → reconnect).

### Running it

```bash
python -m mcp_server            # from the project root, with the venv active
```

### Adding it to Claude Desktop or Claude Code

```json
{
  "mcpServers": {
    "youtube": {
      "command": "python",
      "args": ["-m", "mcp_server"]
    }
  }
}
```

That works when `python` is the venv's interpreter and the package is installed (`pip install -e .`). Claude Desktop does **not** inherit your shell's PATH or virtualenv, so in practice use absolute paths:

```json
{
  "mcpServers": {
    "youtube": {
      "command": "/absolute/path/to/youtube-mcp-server/.venv/bin/python",
      "args": ["-m", "mcp_server"]
    }
  }
}
```

- **Claude Desktop:** edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`), then restart the app.
- **Claude Code:**
  ```bash
  claude mcp add youtube -- /absolute/path/to/youtube-mcp-server/.venv/bin/python -m mcp_server
  ```

## Library usage

```python
from youtube import YouTubeClient, get_channel_info, get_top_videos, search_videos, YouTubeError

client = YouTubeClient()  # resolves credentials lazily; may run the OAuth flow if needed

print(get_channel_info(client, "@SomeHandle"))
print(search_videos(client, "python tutorial", order="viewCount", published_after="2025-01-01"))

try:
    print(get_top_videos(client, "2025-01-01", "2025-01-31", metric="watch_time", limit=5))
except YouTubeError as exc:
    print(exc.code, exc)
```

Or get a raw `googleapiclient` service with the best available credentials:

```python
from youtube import get_youtube_service, get_analytics_service

yt = get_youtube_service()
```

## Quota

The YouTube Data API has a daily quota (10,000 units by default, reset at midnight Pacific). Quota and rate-limit errors are reported as `QUOTA_EXCEEDED` with guidance rather than a stack trace.

| Call | Approximate cost |
|------|------------------|
| Most reads (channel, videos, playlists, comments page, trending) | 1 unit |
| `search_videos` | 100 units |
| `compare_channels` | ~3 units per channel |
| Upload | ~1,600 units |
| `list_channel_videos` | 1-2 units per page (reads the uploads playlist, not search) |

The Analytics and Reporting APIs (analytics, insights, reports, alerts, export) have separate, generous quotas and don't use these units.

## Development

```bash
pytest          # offline; never reads your real .env or tokens
```

## Project layout

```
youtube/
  auth.py        credential discovery, OAuth flow, get_youtube_service()
  client.py      YouTubeClient: lazy services, error translation, token reload
  errors.py      typed exceptions + Google API error mapping
  operations.py  registry of operations and what credentials each needs
  channels.py    channel info, channel videos
  videos.py      video details, bulk stats, search
  playlists.py   playlists, playlist items
  comments.py    comment threads, replies
  benchmark.py   channel comparison, trending chart
  analytics.py   channel/video analytics, top videos, revenue
  insights.py    audience breakdowns, search terms
  reports.py     period reports, Markdown rendering, anomaly alerts
  export.py      daily datasets as CSV / JSON Lines
  reporting.py   YouTube Reporting API: report types, jobs, CSV downloads
  upload.py      opt-in uploads
mcp_server/
  server.py      MCP tools
cli.py           click CLI
tests/           offline pytest suite
```

## License

MIT
