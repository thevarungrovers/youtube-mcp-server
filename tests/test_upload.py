import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.http import HttpMockSequence

import youtube
from youtube import AuthContext, AuthMode, YouTubeClient
from youtube.auth import SCOPE_FORCE_SSL, SCOPES
from youtube.errors import AuthError, InvalidRequestError, UploadsDisabledError

from tests.helpers import err, ok


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 1024)
    return path


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("YOUTUBE_ALLOW_UPLOADS", "true")


def _client(responses=(), *, scopes=SCOPES + [SCOPE_FORCE_SSL]):
    auth = AuthContext(AuthMode.OAUTH, credentials=Credentials(token="t", scopes=scopes))
    return YouTubeClient(auth=auth, http=HttpMockSequence(list(responses)))


def _uploaded(video_id="vid1", applied="private"):
    # Resumable upload: the session URL, then the final response with the video resource.
    return [
        ({"status": "200", "location": "https://upload.example/session"}, ""),
        ok({"id": video_id, "snippet": {"title": "Clip"}, "status": {"privacyStatus": applied, "uploadStatus": "uploaded"}}),
    ]


def _spy_insert(c):
    """Record the kwargs passed to videos().insert."""
    sent = {}
    service = c.data
    real_videos = service.videos

    def videos():
        resource = real_videos()
        real_insert = resource.insert
        resource.insert = lambda **kwargs: sent.update(kwargs) or real_insert(**kwargs)
        return resource

    service.videos = videos
    return sent


def test_uploads_are_off_by_default(video):
    with pytest.raises(UploadsDisabledError, match="YOUTUBE_ALLOW_UPLOADS"):
        youtube.upload_video(_client(), video, "Clip")


def test_read_only_token_cannot_upload(video, enabled):
    with pytest.raises(AuthError, match="--read-only"):
        youtube.upload_video(_client(scopes=SCOPES), video, "Clip")


def test_upload_defaults_to_private(video, enabled):
    c = _client(_uploaded())
    sent = _spy_insert(c)
    result = youtube.upload_video(c, video, "Clip", tags="farm, rooftop greenhouse", made_for_kids=False)
    assert sent["body"]["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    assert sent["body"]["snippet"]["tags"] == ["farm", "rooftop greenhouse"]
    assert result["video_id"] == "vid1" and result["privacy_status"] == "private"
    assert result["studio_url"].endswith("/vid1/edit")


def test_progress_reaches_one(video, enabled):
    seen = []
    youtube.upload_video(_client(_uploaded()), video, "Clip", progress=seen.append)
    assert seen[-1] == 1.0


def test_playlist_failure_is_a_note_not_a_failure(video, enabled):
    c = _client(_uploaded() + [err(404, "playlistNotFound")])
    result = youtube.upload_video(c, video, "Clip", playlist_id="PLmissing")
    assert result["video_id"] == "vid1" and result["playlist_added"] is False
    assert "PLmissing" in result["notes"][0]


@pytest.mark.parametrize(("kwargs", "match"), [
    ({"title": ""}, "title"),
    ({"title": "x" * 101}, "title"),
    ({"title": "a <b>"}, "title"),
    ({"title": "ok", "tags": ["t" * 501]}, "Tags"),
])
def test_validation(video, enabled, kwargs, match):
    with pytest.raises(InvalidRequestError, match=match):
        youtube.upload_video(_client(), video, **kwargs)


def test_wrong_file_type(tmp_path, enabled):
    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    with pytest.raises(InvalidRequestError, match="Video file must be"):
        youtube.upload_video(_client(), doc, "Clip")


def test_upload_limit_maps_to_quota(video, enabled):
    from youtube.errors import QuotaExceededError

    c = _client([err(400, "uploadLimitExceeded", "The user has exceeded the number of videos they may upload.")])
    with pytest.raises(QuotaExceededError, match="24 hours"):
        youtube.upload_video(c, video, "Clip")


def test_auth_status_lists_upload_when_enabled(isolated_credentials, enabled):
    from tests.test_auth import write_token

    write_token(isolated_credentials / "token.json", scopes=SCOPES + [SCOPE_FORCE_SSL])
    status = youtube.auth_status()
    assert status["uploads_enabled"] is True and "upload_video" in status["supported_operations"]


@pytest.mark.parametrize("privacy", ["private", "unlisted", "public", "PUBLIC "])
def test_privacy_comes_from_env(video, enabled, monkeypatch, privacy):
    monkeypatch.setenv("YOUTUBE_UPLOAD_PRIVACY", privacy)
    expected = privacy.strip().lower()
    c = _client(_uploaded(applied=expected))
    sent = _spy_insert(c)
    result = youtube.upload_video(c, video, "Clip")
    assert sent["body"]["status"]["privacyStatus"] == expected
    assert result["requested_privacy"] == expected and result["notes"] == []


def test_invalid_privacy_setting_is_refused_before_uploading(video, enabled, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_PRIVACY", "friends-only")
    with pytest.raises(InvalidRequestError, match="YOUTUBE_UPLOAD_PRIVACY"):
        youtube.upload_video(_client(), video, "Clip")  # no responses queued: any request would fail


def test_youtube_forcing_private_is_explained(video, enabled, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_PRIVACY", "public")
    result = youtube.upload_video(_client(_uploaded(applied="private")), video, "Clip")
    assert result["requested_privacy"] == "public" and result["privacy_status"] == "private"
    assert "audit" in result["notes"][0]


def test_mcp_tool_has_no_privacy_parameter():
    import inspect

    from mcp_server.server import upload_video

    assert not any("privacy" in name for name in inspect.signature(upload_video).parameters)


def test_auth_status_reports_privacy(isolated_credentials, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_PRIVACY", "unlisted")
    assert youtube.auth_status()["upload_privacy"] == "unlisted"
    monkeypatch.setenv("YOUTUBE_UPLOAD_PRIVACY", "bogus")
    assert youtube.auth_status()["upload_privacy"].startswith("invalid")
