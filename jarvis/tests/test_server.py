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
        # read-only
        "system_status", "search_files", "list_shortcuts", "now_playing",
        "read_clipboard",
        # reversible
        "open_app", "quit_app", "set_volume", "change_volume", "set_mute",
        "set_wifi", "set_dark_mode", "media_control", "write_clipboard",
        "lock_screen",
        # memory
        "recall", "list_memories", "remember", "forget",
        # needs confirmation
        "run_shortcut", "forget",
    }


PAIRS = [
    ("open_app", "quit_app"),
    ("read_clipboard", "write_clipboard"),
    ("remember", "forget"),
]


async def test_paired_tools_both_exist():
    """Every basic action should have its opposite, where one can exist."""
    names = {t.name for t in await server.list_tools()}
    for forward, back in PAIRS:
        assert forward in names and back in names, f"{forward}/{back}"


async def test_toggles_take_a_boolean_rather_than_splitting_in_two():
    """One tool with a state cannot drift out of sync the way two can."""
    for name in ("set_mute", "set_wifi", "set_dark_mode"):
        schema = (await _tool(name)).input_schema
        (field,) = schema["properties"].values()
        assert field["type"] == "boolean", name


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

    monkeypatch.setattr(files, "_walk_root", boom)
    monkeypatch.setattr(macos, "is_macos", lambda: False)

    with pytest.raises(UnexpectedToolError) as exc:
        await server.call_tool("search_files", {"query": "x"})
    assert "internal detail" not in str(exc.value)


async def test_dispatch_rejects_bad_arguments(sandbox):
    with pytest.raises(ToolError):
        await server.call_tool("search_files", {})
