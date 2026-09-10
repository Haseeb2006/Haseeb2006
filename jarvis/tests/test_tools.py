import pytest

from mcp_server import macos
from mcp_server.tools import files, shortcuts


async def test_search_finds_files_in_root(sandbox):
    (sandbox["root"] / "invoice-2026.pdf").write_text("x")
    (sandbox["root"] / "holiday.jpg").write_text("x")
    result = await files.search_files(query="invoice")
    assert result["count"] == 1
    assert result["results"][0]["name"] == "invoice-2026.pdf"


async def test_search_never_returns_paths_outside_roots(sandbox, monkeypatch):
    """Even if the search backend hands back an outside path, it is filtered."""
    leaked = sandbox["outside"] / "passwords.txt"
    monkeypatch.setattr(files, "_walk", lambda *a, **k: [leaked])
    monkeypatch.setattr(macos, "is_macos", lambda: False)
    result = await files.search_files(query="passwords")
    assert result["count"] == 0


async def test_search_skips_dotfiles(sandbox):
    (sandbox["root"] / ".secret-token").write_text("x")
    result = await files.search_files(query="secret")
    assert result["count"] == 0


async def test_search_respects_limit(sandbox):
    for i in range(30):
        (sandbox["root"] / f"report-{i}.txt").write_text("x")
    result = await files.search_files(query="report", limit=5)
    assert result["count"] == 5


async def test_search_limit_is_clamped(sandbox):
    for i in range(3):
        (sandbox["root"] / f"note-{i}.txt").write_text("x")
    assert (await files.search_files(query="note", limit=9999))["count"] == 3
    assert (await files.search_files(query="note", limit=-5))["count"] == 1


async def test_search_rejects_empty_query(sandbox):
    with pytest.raises(ValueError):
        await files.search_files(query="   ")


async def test_run_shortcut_rejects_unknown_name(sandbox, monkeypatch):
    async def fake_names():
        return ["Morning Briefing"]

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(shortcuts, "_names", fake_names)
    with pytest.raises(ValueError, match="No Shortcut named"):
        await shortcuts.run_shortcut(name="Delete Everything", ctx=None)


async def test_run_shortcut_asks_before_running_unapproved(sandbox, monkeypatch):
    """An unknown-to-the-allowlist shortcut must not execute without confirmation."""
    ran = False

    async def fake_names():
        return ["Send Text"]

    async def fake_run(*argv, **kwargs):
        nonlocal ran
        ran = True
        return macos.Completed(0, "", "")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(shortcuts, "_names", fake_names)
    monkeypatch.setattr(macos, "run", fake_run)

    from mcp_server.policy import Refused

    with pytest.raises(Refused):
        await shortcuts.run_shortcut(name="Send Text", ctx=None)
    assert ran is False, "the shortcut executed despite being refused"


async def test_preapproved_shortcut_runs_without_asking(sandbox, monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOWED_SHORTCUTS", "send text")
    calls = []

    async def fake_names():
        return ["Send Text"]

    async def fake_run(*argv, **kwargs):
        calls.append(argv)
        return macos.Completed(0, "done", "")

    monkeypatch.setattr(macos, "is_macos", lambda: True)
    monkeypatch.setattr(shortcuts, "_names", fake_names)
    monkeypatch.setattr(macos, "run", fake_run)

    result = await shortcuts.run_shortcut(name="send text", ctx=None)
    # Name is normalised to the real casing before it reaches the CLI.
    assert result["shortcut"] == "Send Text"
    assert calls[0][:3] == ("shortcuts", "run", "Send Text")


async def test_macos_tools_fail_clearly_off_platform(monkeypatch):
    monkeypatch.setattr(macos, "is_macos", lambda: False)
    from mcp_server.tools import apps, system

    with pytest.raises(macos.NotMacOS, match="needs macOS"):
        await system.system_status()
    with pytest.raises(macos.NotMacOS):
        await apps.open_app(name="Safari")


async def test_run_uses_no_shell():
    """Metacharacters in arguments must reach the program as literal text."""
    result = await macos.run("echo", "$(whoami); rm -rf /")
    assert result.text() == "$(whoami); rm -rf /"


async def test_run_enforces_timeout():
    with pytest.raises(TimeoutError):
        await macos.run("sleep", "5", timeout=0.2)


async def test_probe_swallows_failures():
    async def boom():
        raise OSError("no battery")

    assert await macos.probe(boom()) is None
