import pytest

import youtube
from youtube.errors import InvalidRequestError

from tests.helpers import client, err, ok

CHANNEL_ID = "UC" + "x" * 22


def _comment(cid, author_channel, text):
    return {"id": cid, "snippet": {"authorDisplayName": "A", "authorChannelId": {"value": author_channel},
                                   "textOriginal": text, "likeCount": 2, "publishedAt": "2026-11-01T00:00:00Z"}}


def test_channel_comments_flag_owner_replies():
    thread = {
        "id": "t1",
        "snippet": {"videoId": "v1", "channelId": CHANNEL_ID, "totalReplyCount": 1,
                    "topLevelComment": _comment("t1", "UCviewer", "When is delivery?")},
        "replies": {"comments": [_comment("r1", CHANNEL_ID, "Tuesdays!")]},
    }
    c, _ = client(ok({"items": [thread], "nextPageToken": "N"}))
    result = youtube.list_comments(c, channel=CHANNEL_ID)
    first = result["comments"][0]
    assert first["text"] == "When is delivery?" and first["owner_replied"] is True
    assert first["is_owner_comment"] is False and first["reply_count"] == 1
    assert first["url"].endswith("lc=t1") and result["next_page_token"] == "N"


def test_video_comments_use_video_owner_from_snippet():
    thread = {"id": "t2", "snippet": {"videoId": "v1", "channelId": CHANNEL_ID, "totalReplyCount": 0,
                                      "topLevelComment": _comment("t2", "UCviewer", "Nice")}}
    c, _ = client(ok({"items": [thread]}))
    first = youtube.list_comments(c, video_id="v1")["comments"][0]
    assert first["owner_replied"] is False and first["replies"] == []


def test_comments_disabled_is_a_clear_error():
    c, _ = client(err(403, "commentsDisabled", "The video has disabled comments."))
    with pytest.raises(InvalidRequestError, match="turned off"):
        youtube.list_comments(c, video_id="v1")


def test_comment_order_is_validated():
    c, _ = client()
    with pytest.raises(InvalidRequestError, match="order"):
        youtube.list_comments(c, video_id="v1", order="likes")


def test_replies():
    c, _ = client(ok({"items": [_comment("r1", "UCa", "one"), _comment("r2", "UCb", "two")]}))
    result = youtube.get_comment_replies(c, "t1")
    assert [r["text"] for r in result["replies"]] == ["one", "two"]


def test_comments_with_oauth_but_no_key_explain_the_key_is_needed():
    from googleapiclient.http import HttpMockSequence

    from youtube import AuthContext, AuthMode, YouTubeClient
    from youtube.errors import AuthError

    c = YouTubeClient(auth=AuthContext(AuthMode.OAUTH), http=HttpMockSequence([]))
    with pytest.raises(AuthError, match="YOUTUBE_API_KEY.*--with-comments"):
        youtube.list_comments(c, video_id="v1")


def test_comments_with_oauth_and_key_use_the_key():
    from googleapiclient.http import HttpMockSequence

    from youtube import AuthContext, AuthMode, YouTubeClient

    http = HttpMockSequence([({"status": "200"}, "echo_request_uri")])
    c = YouTubeClient(auth=AuthContext(AuthMode.OAUTH, api_key="k"), http=http)
    request = c.comments.commentThreads().list(part="snippet", videoId="v1")
    assert "key=k" in request.uri


def test_comments_with_comments_scope_use_oauth_not_the_key():
    from google.oauth2.credentials import Credentials
    from googleapiclient.http import HttpMockSequence

    from youtube import AuthContext, AuthMode, YouTubeClient
    from youtube.auth import SCOPE_FORCE_SSL, SCOPES

    creds = Credentials(token="t", scopes=SCOPES + [SCOPE_FORCE_SSL])
    c = YouTubeClient(auth=AuthContext(AuthMode.OAUTH, credentials=creds, api_key="k"), http=HttpMockSequence([]))
    assert c.comments is c.data
