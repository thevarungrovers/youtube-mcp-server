"""Credential discovery for the YouTube APIs.

Credentials are tried in this order, and the first usable one wins:

1. ``token.json`` holding a valid OAuth token -- supports every operation.
2. ``token.json`` holding an expired token with a refresh token -- refreshed
   in place and saved back.
3. ``client_secret.json`` with no usable token -- the OAuth Desktop flow runs
   (opens a browser for consent) and the token is saved to ``token.json``.
   Only when ``interactive=True``; a server must not block on a browser.
4. ``YOUTUBE_API_KEY`` in the environment or ``.env`` -- public, read-only
   data only (no analytics).
5. Nothing -- :class:`CredentialsNotFoundError` explains what to set up.

Whatever goes wrong on the way (an unreadable token, a revoked refresh token)
is recorded in :attr:`AuthContext.notes` rather than dropped, so a fallback to
the API key never hides why OAuth was not used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from youtube.errors import AUTH_HINT, AuthError, CredentialsNotFoundError, oauth_required

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCOPE_YOUTUBE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
SCOPE_ANALYTICS_READONLY = "https://www.googleapis.com/auth/yt-analytics.readonly"
SCOPE_ANALYTICS_MONETARY = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"

#: Every scope the OAuth flow asks for by default. All are read-only.
SCOPES: list[str] = [
    SCOPE_YOUTUBE_READONLY,
    SCOPE_ANALYTICS_READONLY,
    SCOPE_ANALYTICS_MONETARY,
]

#: Opt-in (``cli.py auth --with-comments``): Google only lets OAuth read comments
#: with this scope, which also allows editing and deleting. This package never
#: writes; without it, comments are read with YOUTUBE_API_KEY instead.
SCOPE_FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"

_API_KEY_PLACEHOLDER = "your_api_key_here"

_dotenv_loaded = False


class AuthMode(str, Enum):
    """Which kind of credential a service was built with."""

    OAUTH = "oauth"
    API_KEY = "api_key"


@dataclass
class AuthContext:
    """The credential chosen by :func:`resolve_auth`, plus notes on how it was chosen."""

    mode: AuthMode
    credentials: Credentials | None = None
    api_key: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def has_oauth(self) -> bool:
        """True when OAuth credentials are in use (all operations supported)."""
        return self.mode is AuthMode.OAUTH

    @property
    def oauth_reads_comments(self) -> bool:
        """True when the OAuth token was granted the opt-in comments scope."""
        return self.has_oauth and self.credentials is not None and self.credentials.has_scopes([SCOPE_FORCE_SSL])


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def _load_dotenv_once() -> None:
    """Load ``.env`` from the project root, then the cwd; never override real env vars."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(Path.cwd() / ".env", override=False)
    _dotenv_loaded = True


def _env(name: str) -> str | None:
    """Read a setting, treating a blank value as unset."""
    _load_dotenv_once()
    value = (os.environ.get(name) or "").strip()
    return value or None


def _path_setting(name: str, default: str) -> Path:
    path = Path(_env(name) or default).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def client_secret_file() -> Path:
    """Path to the OAuth client secrets JSON (``YOUTUBE_CLIENT_SECRET_FILE``)."""
    return _path_setting("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")


def token_file() -> Path:
    """Path where the OAuth token is stored (``YOUTUBE_TOKEN_FILE``)."""
    return _path_setting("YOUTUBE_TOKEN_FILE", "token.json")


def api_key() -> str | None:
    """The ``YOUTUBE_API_KEY`` value, or None if unset or still the placeholder."""
    key = _env("YOUTUBE_API_KEY")
    return None if key == _API_KEY_PLACEHOLDER else key


def default_channel() -> str | None:
    """The ``YOUTUBE_CHANNEL_ID`` value (channel ID or @handle), if set."""
    return _env("YOUTUBE_CHANNEL_ID")


# --------------------------------------------------------------------------- #
# OAuth token handling
# --------------------------------------------------------------------------- #


def _save_token(creds: Credentials) -> None:
    path = token_file()
    path.write_text(creds.to_json(), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _load_oauth_token(notes: list[str]) -> Credentials | None:
    """Return valid OAuth credentials from token.json, refreshing if needed.

    Problems are appended to ``notes`` and ``None`` is returned, so the caller
    can fall through to the next credential source.
    """
    path = token_file()
    if not path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(path))
    except (ValueError, OSError) as exc:
        notes.append(f"{path.name} exists but could not be read ({exc}). {AUTH_HINT}")
        return None

    if not creds.has_scopes([SCOPE_YOUTUBE_READONLY]):
        notes.append(f"{path.name} is missing the youtube.readonly scope. {AUTH_HINT}")
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            notes.append(
                f"OAuth token in {path.name} could not be refreshed ({exc}); it was "
                f"probably revoked or expired. {AUTH_HINT}"
            )
            return None
        except GoogleAuthError as exc:
            notes.append(f"OAuth token refresh failed ({exc}). Check your network and retry.")
            return None
        _save_token(creds)
        return creds

    notes.append(f"OAuth token in {path.name} is invalid and has no refresh token. {AUTH_HINT}")
    return None


def run_oauth_flow(*, open_browser: bool = True, with_comments: bool = False) -> Credentials:
    """Run the OAuth Desktop-app consent flow and save the token to token.json.

    Args:
        open_browser: Open the consent page automatically. When False, the URL
            is printed so it can be opened by hand.
        with_comments: Also ask for :data:`SCOPE_FORCE_SSL`, so comments can be
            read without an API key. That scope can also edit and delete.

    Returns:
        The new OAuth credentials.

    Raises:
        CredentialsNotFoundError: client_secret.json does not exist.
        AuthError: The flow failed or was cancelled.
    """
    secret = client_secret_file()
    if not secret.exists():
        raise CredentialsNotFoundError(
            f"OAuth client secrets not found at {secret}. In the Google Cloud console, "
            "create an OAuth client ID of type 'Desktop app', download its JSON and save "
            "it as client_secret.json in the project root (see README)."
        )
    try:
        scopes = SCOPES + [SCOPE_FORCE_SSL] if with_comments else SCOPES
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes)
        creds = flow.run_local_server(
            port=0,
            open_browser=open_browser,
            authorization_prompt_message="Open this URL to authorize access:\n{url}\n",
            success_message="Authorization complete. You can close this tab.",
        )
    except (ValueError, GoogleAuthError, OSError) as exc:
        raise AuthError(f"OAuth flow failed: {exc}") from exc
    _save_token(creds)
    return creds


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def _no_credentials_message(notes: list[str]) -> str:
    lines = ["No usable YouTube credentials were found."]
    lines += [f"  - {note}" for note in notes]
    lines += [
        "Set up at least one of:",
        f"  * OAuth (all operations, including analytics): save your Desktop-app OAuth "
        f"client JSON as {client_secret_file()} and run `python cli.py auth`.",
        "  * API key (public read-only data only): set YOUTUBE_API_KEY in .env.",
        "See README.md for step-by-step instructions.",
    ]
    return "\n".join(lines)


def resolve_auth(*, interactive: bool = True) -> AuthContext:
    """Pick the best available credentials, following the module's priority order.

    Args:
        interactive: Allow launching the browser-based OAuth flow when
            client_secret.json exists but no usable token does. Servers pass
            False and fall back to the API key (with a note) instead.

    Returns:
        An :class:`AuthContext` describing the chosen credential.

    Raises:
        CredentialsNotFoundError: Nothing usable is available.
        AuthError: The interactive OAuth flow was attempted and failed.
    """
    notes: list[str] = []

    creds = _load_oauth_token(notes)
    if creds is not None:
        if not creds.has_scopes([SCOPE_ANALYTICS_READONLY]):
            notes.append(f"OAuth token lacks the analytics scope; analytics calls will fail. {AUTH_HINT}")
        return AuthContext(AuthMode.OAUTH, credentials=creds, api_key=api_key(), notes=notes)

    if client_secret_file().exists():
        if interactive:
            creds = run_oauth_flow()
            return AuthContext(AuthMode.OAUTH, credentials=creds, api_key=api_key(), notes=notes)
        notes.append(
            f"{client_secret_file().name} is present but no OAuth token has been created yet. "
            f"{AUTH_HINT}"
        )

    key = api_key()
    if key:
        notes.append("Using YOUTUBE_API_KEY: public read-only data only; analytics needs OAuth.")
        return AuthContext(AuthMode.API_KEY, api_key=key, notes=notes)

    raise CredentialsNotFoundError(_no_credentials_message(notes))


def build_service(
    auth: AuthContext, api: str, version: str, *, http: Any | None = None
) -> Resource:
    """Build a ``googleapiclient`` service object for ``auth``.

    Args:
        auth: Credentials from :func:`resolve_auth`.
        api: API name, e.g. ``"youtube"`` or ``"youtubeAnalytics"``.
        version: API version, e.g. ``"v3"``.
        http: Optional ``httplib2.Http``-like transport (used by tests).
    """
    kwargs: dict[str, Any] = {"cache_discovery": False, "static_discovery": True}
    if http is not None:
        kwargs["http"] = http
        if auth.api_key and not auth.has_oauth:
            kwargs["developerKey"] = auth.api_key
    elif auth.has_oauth:
        kwargs["credentials"] = auth.credentials
    else:
        kwargs["developerKey"] = auth.api_key
    return build(api, version, **kwargs)


def get_youtube_service(*, interactive: bool = True) -> Resource:
    """Return a YouTube Data API v3 service using the best available credentials.

    Args:
        interactive: Allow the browser OAuth flow if it is needed (see
            :func:`resolve_auth`).

    Raises:
        CredentialsNotFoundError: No credentials are available.
    """
    return build_service(resolve_auth(interactive=interactive), "youtube", "v3")


def get_analytics_service(*, interactive: bool = True) -> Resource:
    """Return a YouTube Analytics API v2 service. OAuth is required.

    Raises:
        OAuthRequiredError: Only an API key is available.
        CredentialsNotFoundError: No credentials are available.
    """
    auth = resolve_auth(interactive=interactive)
    if not auth.has_oauth:
        raise oauth_required("YouTube Analytics")
    return build_service(auth, "youtubeAnalytics", "v2")


def auth_status() -> dict[str, Any]:
    """Describe the available credentials and which operations they support.

    Never runs the browser flow and never raises: problems are reported in
    ``notes`` and ``next_steps``. May refresh an expired token (a network call).
    """
    from youtube.operations import OPERATIONS  # late import: operations are registered on package import

    token_path = token_file()
    secret_path = client_secret_file()
    key_present = api_key() is not None

    active: AuthContext | None = None
    error: str | None = None
    try:
        active = resolve_auth(interactive=False)
    except (CredentialsNotFoundError, AuthError) as exc:
        error = str(exc)

    oauth = bool(active and active.has_oauth)
    available = "both" if oauth and key_present else "oauth" if oauth else "api_key" if key_present else "none"

    supported = sorted(
        name
        for name, op in OPERATIONS.items()
        if active
        and (oauth or not op.requires_oauth)
        and (not op.requires_comment_access or key_present or active.oauth_reads_comments)
    )
    unsupported = sorted(set(OPERATIONS) - set(supported))

    next_steps: list[str] = []
    if not oauth:
        if secret_path.exists():
            next_steps.append("Run `python cli.py auth` to create an OAuth token and unlock analytics.")
        else:
            next_steps.append(
                "For analytics: create a Desktop-app OAuth client, save it as "
                f"{secret_path.name}, then run `python cli.py auth`."
            )
    if not key_present and not oauth:
        next_steps.append("For public data only: set YOUTUBE_API_KEY in .env.")
    elif not key_present and not (active and active.oauth_reads_comments):
        next_steps.append(
            "For comments: set YOUTUBE_API_KEY in .env, or run `python cli.py auth --with-comments` "
            "(grants a scope that can also edit and delete)."
        )

    granted = sorted(active.credentials.scopes or []) if oauth and active and active.credentials else []
    return {
        "credentials_available": available,
        "active_mode": active.mode.value if active else None,
        "api_key_present": key_present,
        "client_secret_present": secret_path.exists(),
        "token_present": token_path.exists(),
        "oauth_token_valid": oauth,
        "oauth_scopes": granted,
        "supported_operations": supported,
        "unsupported_operations": unsupported,
        "notes": (active.notes if active else []) + ([error] if error else []),
        "next_steps": next_steps,
    }
