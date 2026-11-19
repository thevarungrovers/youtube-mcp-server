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

### 2. Create a Google Cloud project

In the [Google Cloud console](https://console.cloud.google.com/):

1. Create a project, or select an existing one.
2. **APIs & Services → Library**: enable **YouTube Data API v3** and **YouTube Analytics API**.

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
```

1. Sign in with the Google account that owns or manages the channel.
2. If Google says **"Google hasn't verified this app"**, click **Advanced → Go to (app name)**.
3. **Choose the account:** Google may list your personal profile *and* the channels you manage (Brand Account channels are labelled *YouTube*). **Use the account that you want to connect.**
4. Accept the read-only permissions.
5. The command prints the connected channel. Confirm it is the right one, then run:

```bash
python cli.py auth-status
```

The token is saved to `token.json`. "My channel" means the channel you picked, everywhere. To switch channels, delete `token.json` and run `python cli.py auth` again.

Analytics needs a role on the channel that can view analytics (Manager or Owner). Revenue also needs a monetized channel.

### 6. API key (optional)

Only needed for public data without OAuth, e.g. as a fallback.

1. **APIs & Services → Credentials → Create credentials → API key**.
2. **Edit API key → API restrictions → Restrict key** → tick only **YouTube Data API v3** → **Save**.
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
