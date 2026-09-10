import pytest

from mcp_server import config


def test_accepts_path_inside_root(sandbox):
    target = sandbox["root"] / "notes.md"
    target.write_text("hi")
    assert config.resolve_within_roots(target) == target.resolve()


def test_rejects_dot_dot_escape(sandbox):
    escape = sandbox["root"] / ".." / "Secrets" / "passwords.txt"
    with pytest.raises(config.PathNotAllowed):
        config.resolve_within_roots(escape)


def test_rejects_symlink_escape(sandbox):
    """The check happens after resolution, so a symlink cannot tunnel out."""
    link = sandbox["root"] / "innocent.txt"
    link.symlink_to(sandbox["outside"] / "passwords.txt")
    assert link.exists()  # the link itself lives inside the root
    with pytest.raises(config.PathNotAllowed):
        config.resolve_within_roots(link)


def test_rejects_absolute_path_outside(sandbox):
    with pytest.raises(config.PathNotAllowed):
        config.resolve_within_roots("/etc/passwd")


def test_root_itself_is_allowed(sandbox):
    assert config.resolve_within_roots(sandbox["root"]) == sandbox["root"].resolve()


def test_nonexistent_roots_are_dropped(monkeypatch, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", f"{real},{tmp_path / 'ghost'}")
    assert config.allowed_roots() == [real.resolve()]


def test_shortcut_allowlist_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOWED_SHORTCUTS", "Morning Briefing, Set Focus")
    assert config.allowed_shortcuts() == {"morning briefing", "set focus"}
