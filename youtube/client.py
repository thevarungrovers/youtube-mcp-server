"""A long-lived handle on the YouTube APIs that every operation goes through.

:class:`YouTubeClient` resolves credentials lazily, builds the Data and
Analytics services on first use, and runs every request through
:meth:`YouTubeClient.execute`, which turns Google's errors into the
package's own (see :mod:`youtube.errors`).

It notices when ``token.json`` changes on disk -- e.g. ``cli.py auth`` was run
while the MCP server was up -- and picks up the new credentials on the next
call, so the server does not need a restart.
"""

from __future__ import annotations

import threading
from typing import Any

from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

from youtube import auth as auth_module
from youtube.auth import AuthContext, build_service
from youtube.errors import AUTH_HINT, APIError, AuthError, oauth_required, translate_http_error


class YouTubeClient:
    """Credentials plus lazily-built YouTube Data v3 and Analytics v2 services.

    Args:
        interactive: Allow the browser OAuth flow when client_secret.json exists
            but no token does. The MCP server passes False.
        auth: Use these credentials instead of resolving them (no auto-reload).
        http: Transport passed to every service build (tests use
            ``googleapiclient.http.HttpMockSequence``).
    """

    def __init__(
        self,
        *,
        interactive: bool = True,
        auth: AuthContext | None = None,
        http: Any | None = None,
    ) -> None:
        self._interactive = interactive
        self._fixed_auth = auth is not None
        self._auth = auth
        self._http = http
        self._token_mtime: float | None = self._current_token_mtime()
        self._data: Resource | None = None
        self._analytics: Resource | None = None
        # httplib2 connections are not thread-safe, and MCP runs sync tools on
        # worker threads, so requests are serialised.
        self._lock = threading.RLock()

    @staticmethod
    def _current_token_mtime() -> float | None:
        path = auth_module.token_file()
        return path.stat().st_mtime if path.exists() else None

    def reset(self) -> None:
        """Forget cached credentials and services; the next call re-resolves them."""
        with self._lock:
            if not self._fixed_auth:
                self._auth = None
            self._data = None
            self._analytics = None
            self._token_mtime = self._current_token_mtime()

    @property
    def auth(self) -> AuthContext:
        """The active credentials, resolved on first access."""
        with self._lock:
            if not self._fixed_auth and self._current_token_mtime() != self._token_mtime:
                self.reset()
            if self._auth is None:
                self._auth = auth_module.resolve_auth(interactive=self._interactive)
                self._token_mtime = self._current_token_mtime()
            return self._auth

    @property
    def data(self) -> Resource:
        """The YouTube Data API v3 service."""
        auth = self.auth
        with self._lock:
            if self._data is None:
                self._data = build_service(auth, "youtube", "v3", http=self._http)
            return self._data

    @property
    def analytics(self) -> Resource:
        """The YouTube Analytics API v2 service. Raises OAuthRequiredError without OAuth."""
        auth = self.auth
        if not auth.has_oauth:
            raise oauth_required("YouTube Analytics")
        with self._lock:
            if self._analytics is None:
                self._analytics = build_service(auth, "youtubeAnalytics", "v2", http=self._http)
            return self._analytics

    def execute(self, request: Any, *, api: str = "YouTube Data API") -> dict[str, Any]:
        """Execute a ``googleapiclient`` request, translating failures.

        Raises:
            QuotaExceededError, AuthError, NotFoundError, InvalidRequestError,
            APIError: see :func:`youtube.errors.translate_http_error`.
        """
        with self._lock:
            try:
                return request.execute(num_retries=2)
            except HttpError as exc:
                raise translate_http_error(exc, api=api) from exc
            except RefreshError as exc:
                raise AuthError(f"OAuth token could not be refreshed ({exc}). {AUTH_HINT}") from exc
            except (TransportError, OSError) as exc:
                raise APIError(f"Network error talking to {api}: {exc}") from exc
