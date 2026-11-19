"""Build clients backed by canned HTTP responses."""

from __future__ import annotations

import json
from typing import Any

from googleapiclient.http import HttpMockSequence

from youtube import AuthContext, AuthMode, YouTubeClient


def ok(body: dict[str, Any]) -> tuple[dict[str, str], str]:
    return ({"status": "200"}, json.dumps(body))


def err(status: int, reason: str, message: str = "error") -> tuple[dict[str, str], str]:
    body = {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}}
    return ({"status": str(status)}, json.dumps(body))


def client(*responses: tuple[dict[str, str], str], oauth: bool = False) -> tuple[YouTubeClient, HttpMockSequence]:
    """A client whose requests are answered by ``responses`` in order."""
    http = HttpMockSequence(list(responses))
    auth = AuthContext(AuthMode.OAUTH) if oauth else AuthContext(AuthMode.API_KEY, api_key="test-key")
    return YouTubeClient(auth=auth, http=http), http
