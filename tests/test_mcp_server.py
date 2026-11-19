import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.server import mcp

EXPECTED_TOOLS = {
    "auth_status",
    "get_channel_info",
    "list_channel_videos",
    "get_video_details",
    "search_videos",
    "get_channel_analytics",
    "get_video_analytics",
    "get_top_videos",
    "get_revenue",
    "list_playlists",
    "get_playlist_items",
    "get_audience_insights",
    "get_search_terms",
    "list_comments",
    "get_comment_replies",
    "compare_channels",
    "get_trending_videos",
}


def test_tool_surface_is_pinned_and_read_only():
    tools = anyio.run(mcp.list_tools)
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name
        assert tool.description, tool.name
        for name, prop in tool.input_schema.get("properties", {}).items():
            assert prop.get("description"), f"{tool.name}.{name} has no description"


def _call(name, args):
    async def go():
        return await mcp.call_tool(name, args)

    return anyio.run(go)


@pytest.mark.parametrize("tool", ["get_channel_analytics", "get_top_videos", "get_revenue", "get_audience_insights", "get_search_terms"])
def test_oauth_tools_explain_how_to_enable(tool, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "abc")
    from mcp_server import server

    server.client.reset()
    with pytest.raises(ToolError, match="OAUTH_REQUIRED.*cli.py auth"):
        _call(tool, {})


def test_no_credentials_error_reaches_agent():
    from mcp_server import server

    server.client.reset()
    with pytest.raises(ToolError, match="NO_CREDENTIALS"):
        _call("get_video_details", {"video_ids": "abc"})


def test_auth_status_never_fails():
    result = _call("auth_status", {})
    assert "credentials_available" in str(result)
