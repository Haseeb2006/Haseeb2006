"""End-to-end through the real MCP dispatch path, not the functions directly."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from mcp_server import macos
from mcp_server.server import server


async def _tool(name):
    return next(t for t in await server.list_tools() if t.name == name)


async def test_all_tools_are_registered():
    names = {t.name for t in await server.list_tools()}
    assert names == {
        "system_status",
        "search_files",
        "list_shortcuts",
        "open_app",
        "run_shortcut",
    }


async def test_context_is_not_exposed_as_a_parameter():
    """`ctx` is injected by the server — the model must never see or fill it."""
    schema = (await _tool("run_shortcut")).input_schema
    assert "ctx" not in schema.get("properties", {})
    assert set(schema.get("required", [])) == {"name"}


async def test_every_tool_documents_itself():
    """Tool descriptions are the prompt engineering — none may be blank."""
    for tool in await server.list_tools():
        assert tool.description and len(tool.description) > 30, tool.name


async def test_read_only_tools_are_annotated():
    for name in ("system_status", "search_files", "list_shortcuts"):
        assert (await _tool(name)).annotations.read_only_hint is True
    assert (await _tool("run_shortcut")).annotations.destructive_hint is True


async def test_search_files_round_trip_through_dispatch(sandbox):
    (sandbox["root"] / "budget.xlsx").write_text("x")
    result = await server.call_tool("search_files", {"query": "budget"})
    assert result.is_error is False
    assert "budget.xlsx" in str(result.content)


async def test_refusal_reason_reaches_the_model(sandbox, monkeypatch):
    """A refusal must explain itself, not arrive as a bare 'Error executing tool'."""
    async def fake_names():
        return ["Send Text"]

    from mcp_server.tools import shortcuts

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(shortcuts, "_names", fake_names)

    with pytest.raises(ToolError) as exc:
        await server.call_tool("run_shortcut", {"name": "Send Text"})
    message = str(exc.value)
    assert "RED" in message
    assert "JARVIS_ALLOWED_SHORTCUTS" in message


async def test_bad_shortcut_name_reaches_the_model(sandbox, monkeypatch):
    async def fake_names():
        return ["Send Text"]

    from mcp_server.tools import shortcuts

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(shortcuts, "_names", fake_names)

    with pytest.raises(ToolError, match="No Shortcut named"):
        await server.call_tool("run_shortcut", {"name": "Nope"})


async def test_unexpected_crashes_stay_masked(sandbox, monkeypatch):
    """A bug must NOT leak its message; that is the reason for the masking."""
    from mcp_server.tools import files

    def boom(*a, **k):
        raise KeyError("internal detail that must not escape")

    monkeypatch.setattr(files, "_walk", boom)
    monkeypatch.setattr(macos, "is_macos", lambda: False)

    with pytest.raises(UnexpectedToolError) as exc:
        await server.call_tool("search_files", {"query": "x"})
    assert "internal detail" not in str(exc.value)


async def test_dispatch_rejects_bad_arguments(sandbox):
    with pytest.raises(ToolError):
        await server.call_tool("search_files", {})
