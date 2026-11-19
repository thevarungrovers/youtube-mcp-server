# YouTube MCP Server

A read-only Python toolkit for the **YouTube Data API v3** and **YouTube Analytics API v2**:

- **`youtube/`** — a typed Python library (channels, videos, search, playlists, analytics, revenue)
- **`mcp_server/`** — a [Model Context Protocol](https://modelcontextprotocol.io) server so AI agents (Claude Desktop, Claude Code, …) can call it as tools
- **`cli.py`** — a command-line interface for manual testing

Everything is **read-only**: nothing here can upload, edit, or delete.

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

### 2. Google Cloud credentials

In the [Google Cloud console](https://console.cloud.google.com/):

1. **Create or pick a project.**
2. **Enable the APIs** (APIs & Services → Library):
   - *YouTube Data API v3* — required
   - *YouTube Analytics API* — required for analytics/revenue
3. **OAuth (recommended — unlocks everything):**
   1. APIs & Services → OAuth consent screen: configure it (External is fine for personal use) and add your Google account under **Test users**.
   2. APIs & Services → Credentials → **Create credentials → OAuth client ID** → application type **Desktop app**.
   3. Download the JSON and save it as **`client_secret.json`** in the project root.
   4. Run:
      ```bash
      python cli.py auth                # opens a browser for consent
      python cli.py auth --no-browser   # prints the URL instead
      ```
      Sign in with the Google account that owns (or manages) the channel. The token is saved to `token.json`.

      **Choosing an account:** after you sign in, Google may list your personal profile *and* the YouTube channels you manage. Brand Account channels show up here labelled "YouTube". **Pick the YouTube channel you want to analyze, not your personal profile.** The token is tied to the channel you pick, and "my channel" means that channel everywhere: channel info, video lists, and every analytics tool. If you pick a profile with no channel or no videos, analytics comes back empty or fails.

      After the flow finishes, `cli.py auth` prints the channel it connected to. To switch channels, delete `token.json` and run `python cli.py auth` again. Analytics also needs a role on the channel that can view analytics (for example Manager or Owner). Revenue additionally needs a monetized channel.
4. **API key (optional — public data only):** Credentials → Create credentials → API key. Restrict it to the YouTube Data API v3, then:
   ```bash
   cp .env.example .env
   # edit .env: YOUTUBE_API_KEY=...
   ```
   With only an API key, there is no "my channel" — pass `--channel UC...` / `@handle`, or set `YOUTUBE_CHANNEL_ID` in `.env`.

> **Tip:** While your OAuth consent screen is in *Testing* status, Google expires refresh tokens after 7 days. If you start seeing "could not be refreshed", run `python cli.py auth` again, or publish the consent screen.

`client_secret.json`, `token.json` and `.env` are gitignored. Never commit them.

### Troubleshooting sign-in

| Error | Cause | Fix |
|-------|-------|-----|
| `Error 403: org_internal` | The OAuth consent screen's user type is **Internal**, which only admits users of the project's Google Workspace organization. Brand Account channels count as outside the organization, even when a member manages them. | Google Auth Platform → **Audience** → **Make external**. Keep the publishing status on **Testing**, add the Google account you sign in with under **Test users**, delete `token.json`, and run `python cli.py auth` again. If switching to External is blocked by an organization policy, ask your Workspace admin, or create the Cloud project under a personal Google account. |
| `Error 403: access_denied` | The app is in Testing and the account isn't listed as a test user. | Add the account under **Audience → Test users**. |
| "Google hasn't verified this app" | Normal for a private app that hasn't been through Google's verification. | Click **Advanced → Go to (app name)**. |
| "could not be refreshed" after about a week | Apps in **Testing** get refresh tokens that expire after 7 days. | Run `python cli.py auth` again, or set the publishing status to **In production**. That works unverified, with the warning above, for up to 100 users. |

**Scopes requested** (all read-only): `youtube.readonly`, `yt-analytics.readonly`, `yt-analytics-monetary.readonly`.

### Optional settings (`.env`)

| Variable | Purpose |
|----------|---------|
| `YOUTUBE_API_KEY` | API key for public read-only calls |
| `YOUTUBE_CHANNEL_ID` | Default channel (ID or `@handle`) when only an API key is set |
| `YOUTUBE_CLIENT_SECRET_FILE` | Path to the OAuth client JSON (default `client_secret.json`) |
| `YOUTUBE_TOKEN_FILE` | Where to store the OAuth token (default `token.json`) |

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
python cli.py playlists [--channel @handle]
python cli.py playlist PLAYLIST_ID [--stats]
```

Output is JSON. Errors go to stderr prefixed with a code and exit with status 1.

## MCP server

### Tools

| Tool | Needs OAuth | Description |
|------|:-----------:|-------------|
| `auth_status` | | Which credentials are available and which tools work |
| `get_channel_info` | | Channel name, description, subscriber/video/view counts |
| `list_channel_videos` | | A channel's uploads with basic stats (paginated) |
| `get_video_details` | | Full details for one or more video IDs |
| `search_videos` | | Keyword search with date, order, region and channel filters |
| `list_playlists` | | A channel's playlists |
| `get_playlist_items` | | Videos in a playlist |
| `get_channel_analytics` | ✓ | Views, watch time, subscribers gained/lost over a date range |
| `get_video_analytics` | ✓ | Per-video traffic sources, audience retention, demographics |
| `get_top_videos` | ✓ | Top N videos by a metric over a date range |
| `get_revenue` | ✓ | Estimated revenue and CPM (monetized channels only) |

Every tool returns structured JSON, is annotated read-only, and documents each parameter. Analytics tools accept `start_date`/`end_date` (YYYY-MM-DD) or `days` (default 28). Errors reach the agent with a stable prefix: `NO_CREDENTIALS`, `OAUTH_REQUIRED`, `AUTH_ERROR`, `QUOTA_EXCEEDED`, `NOT_FOUND`, `INVALID_REQUEST`, `API_ERROR`.

The server **never opens a browser**. Run `python cli.py auth` once in a terminal; if you do this while the server is running, it picks up the new token on its next call.

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

The YouTube Data API has a daily quota (10,000 units by default, reset at midnight Pacific). Most reads cost **1 unit**; **search costs 100**. `list_channel_videos` reads the channel's uploads playlist rather than searching, so it's cheap. Quota and rate-limit errors are reported as `QUOTA_EXCEEDED` with guidance rather than a stack trace.

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
  operations.py  registry of operations and their OAuth requirement
  channels.py    channel info, channel videos
  videos.py      video details, bulk stats, search
  playlists.py   playlists, playlist items
  analytics.py   channel/video analytics, top videos, revenue
mcp_server/
  server.py      MCP tools
cli.py           click CLI
tests/           offline pytest suite
```

## License

MIT
