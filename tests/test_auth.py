import json

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from youtube import auth
from youtube.auth import SCOPES, AuthMode, resolve_auth
from youtube.errors import CredentialsNotFoundError


def write_token(path, *, expired: bool = False, scopes=SCOPES):
    data = {
        "token": "access",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "id.apps.googleusercontent.com",
        "client_secret": "secret",
        "scopes": scopes,
        "expiry": "2000-01-01T00:00:00Z" if expired else "2999-01-01T00:00:00Z",
    }
    path.write_text(json.dumps(data))


def test_nothing_available_explains_both_options():
    with pytest.raises(CredentialsNotFoundError) as exc:
        resolve_auth(interactive=False)
    msg = str(exc.value)
    assert "cli.py auth" in msg and "YOUTUBE_API_KEY" in msg


def test_api_key_only(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "abc")
    ctx = resolve_auth(interactive=False)
    assert ctx.mode is AuthMode.API_KEY and ctx.api_key == "abc"


def test_placeholder_api_key_is_ignored(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "your_api_key_here")
    with pytest.raises(CredentialsNotFoundError):
        resolve_auth(interactive=False)


def test_valid_token_wins_over_api_key(isolated_credentials, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "abc")
    write_token(isolated_credentials / "token.json")
    ctx = resolve_auth(interactive=False)
    assert ctx.mode is AuthMode.OAUTH and ctx.api_key == "abc"


def test_expired_token_is_refreshed_and_saved(isolated_credentials, monkeypatch):
    token = isolated_credentials / "token.json"
    write_token(token, expired=True)

    def fake_refresh(self, request):
        self.token = "new-access"
        self.expiry = None

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    ctx = resolve_auth(interactive=False)
    assert ctx.mode is AuthMode.OAUTH
    assert json.loads(token.read_text())["token"] == "new-access"


def test_revoked_token_falls_back_to_api_key_with_note(isolated_credentials, monkeypatch):
    write_token(isolated_credentials / "token.json", expired=True)
    monkeypatch.setenv("YOUTUBE_API_KEY", "abc")

    def boom(self, request):
        raise RefreshError("invalid_grant")

    monkeypatch.setattr(Credentials, "refresh", boom)
    ctx = resolve_auth(interactive=False)
    assert ctx.mode is AuthMode.API_KEY
    assert any("could not be refreshed" in n for n in ctx.notes)


def test_client_secret_without_token_non_interactive_notes_it(isolated_credentials, monkeypatch):
    (isolated_credentials / "client_secret.json").write_text("{}")
    monkeypatch.setenv("YOUTUBE_API_KEY", "abc")
    ctx = resolve_auth(interactive=False)
    assert ctx.mode is AuthMode.API_KEY
    assert any("no OAuth token" in n for n in ctx.notes)


def test_client_secret_without_token_interactive_runs_flow(isolated_credentials, monkeypatch):
    (isolated_credentials / "client_secret.json").write_text("{}")
    sentinel = object()
    monkeypatch.setattr(auth, "run_oauth_flow", lambda: sentinel)
    ctx = resolve_auth(interactive=True)
    assert ctx.mode is AuthMode.OAUTH and ctx.credentials is sentinel


def test_corrupt_token_is_reported(isolated_credentials):
    (isolated_credentials / "token.json").write_text("not json")
    with pytest.raises(CredentialsNotFoundError) as exc:
        resolve_auth(interactive=False)
    assert "could not be read" in str(exc.value)


def test_auth_status_api_key_only(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "abc")
    status = auth.auth_status()
    assert status["credentials_available"] == "api_key"
    assert "get_channel_info" in status["supported_operations"]
    assert "get_top_videos" in status["unsupported_operations"]


def test_auth_status_both(isolated_credentials, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "abc")
    write_token(isolated_credentials / "token.json")
    status = auth.auth_status()
    assert status["credentials_available"] == "both"
    assert status["unsupported_operations"] == []


def test_auth_status_oauth_without_key_marks_comments_unsupported(isolated_credentials):
    import youtube  # noqa: F401  (registers every operation)

    write_token(isolated_credentials / "token.json")
    status = auth.auth_status()
    assert status["credentials_available"] == "oauth"
    assert set(status["unsupported_operations"]) == {"list_comments", "get_comment_replies"}
    assert any("comments" in step for step in status["next_steps"])


def test_auth_status_token_with_comments_scope_supports_comments(isolated_credentials):
    import youtube  # noqa: F401  (registers every operation)
    from youtube.auth import SCOPE_FORCE_SSL

    write_token(isolated_credentials / "token.json", scopes=SCOPES + [SCOPE_FORCE_SSL])
    status = auth.auth_status()
    assert status["unsupported_operations"] == []
    assert not any("comments" in step for step in status["next_steps"])


@pytest.mark.parametrize("with_comments", [False, True])
def test_oauth_flow_asks_for_comments_scope_only_on_request(isolated_credentials, monkeypatch, with_comments):
    from youtube.auth import SCOPE_FORCE_SSL

    (isolated_credentials / "client_secret.json").write_text("{}")
    asked = {}

    class FakeFlow:
        def run_local_server(self, **kwargs):
            return Credentials(token="t", refresh_token="r", client_id="c", client_secret="s",
                               token_uri="https://oauth2.googleapis.com/token", scopes=asked["scopes"])

    def from_client_secrets_file(path, scopes):
        asked["scopes"] = scopes
        return FakeFlow()

    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", staticmethod(from_client_secrets_file))
    auth.run_oauth_flow(open_browser=False, with_comments=with_comments)
    assert (SCOPE_FORCE_SSL in asked["scopes"]) is with_comments
    assert set(SCOPES) <= set(asked["scopes"])
