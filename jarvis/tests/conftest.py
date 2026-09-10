import pytest


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """An isolated allowlisted root plus a private audit log."""
    root = tmp_path / "Documents"
    root.mkdir()
    outside = tmp_path / "Secrets"
    outside.mkdir()
    (outside / "passwords.txt").write_text("hunter2")

    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", str(root))
    monkeypatch.setenv("JARVIS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("JARVIS_ALLOWED_SHORTCUTS", raising=False)
    return {"root": root, "outside": outside, "audit": tmp_path / "audit.jsonl"}
