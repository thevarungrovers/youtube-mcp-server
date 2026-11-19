"""Keep the suite offline and away from the developer's real credentials.

Set at import time, before any test module imports ``youtube``: blank env vars
win over ``.env`` (load_dotenv never overrides), and blanks count as unset.
"""

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="youtube-tests-"))
os.environ["YOUTUBE_API_KEY"] = ""
os.environ["YOUTUBE_CHANNEL_ID"] = ""
os.environ["YOUTUBE_TOKEN_FILE"] = str(_TMP / "token.json")
os.environ["YOUTUBE_CLIENT_SECRET_FILE"] = str(_TMP / "client_secret.json")


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path, monkeypatch):
    """Each test starts with no credentials; files live in its own tmp dir."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "")
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_FILE", str(tmp_path / "client_secret.json"))
    return tmp_path
