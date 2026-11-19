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


def test_auth_with_key_signs_in_read_only(monkeypatch, flow):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    result = CliRunner().invoke(cli.cli, ["auth"])
    assert flow["with_comments"] is False and "comments will use the key" in result.output


@pytest.mark.parametrize(("answer", "expected"), [("y\n", True), ("\n", False)])
def test_auth_without_key_asks(monkeypatch, flow, answer, expected):
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    result = CliRunner().invoke(cli.cli, ["auth"], input=answer)
    assert "No YOUTUBE_API_KEY" in result.output and flow["with_comments"] is expected


@pytest.mark.parametrize(("flag", "expected"), [("--with-comments", True), ("--read-only", False)])
def test_auth_flags_skip_the_question(monkeypatch, flow, flag, expected):
    result = CliRunner().invoke(cli.cli, ["auth", flag])
    assert flow["with_comments"] is expected and "Grant comment access" not in result.output


def test_auth_without_key_and_no_terminal_stays_read_only(monkeypatch, flow):
    monkeypatch.setattr(cli, "_can_prompt", lambda: False)
    CliRunner().invoke(cli.cli, ["auth"])
    assert flow["with_comments"] is False
