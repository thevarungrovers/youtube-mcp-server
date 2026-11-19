import pytest
from click.testing import CliRunner

import cli
import youtube


@pytest.fixture
def flow(monkeypatch):
    """Capture run_oauth_flow's with_comments and skip everything after it."""
    seen = {}

    def fake_flow(*, open_browser, with_comments):
        seen["with_comments"] = with_comments
        raise youtube.AuthError("stop after flow")

    monkeypatch.setattr(youtube, "run_oauth_flow", fake_flow)
    return seen


@pytest.mark.parametrize("key", ["", "k"])
def test_auth_asks_for_comment_access_by_default(monkeypatch, flow, key):
    monkeypatch.setenv("YOUTUBE_API_KEY", key)
    CliRunner().invoke(cli.cli, ["auth"])
    assert flow["with_comments"] is True


def test_auth_read_only_skips_comment_access(flow):
    CliRunner().invoke(cli.cli, ["auth", "--read-only"])
    assert flow["with_comments"] is False
