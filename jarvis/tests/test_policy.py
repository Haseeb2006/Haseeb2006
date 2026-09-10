import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server import audit, policy
from mcp_server.policy import Refused, Tier, guarded


class FakeCaps:
    def __init__(self, elicitation):
        self.elicitation = elicitation


class FakeResult:
    def __init__(self, action, confirm=None):
        self.action = action
        self.data = policy.ConfirmAction(confirm=confirm) if confirm is not None else None


class FakeContext:
    """Stands in for an MCP client session."""

    def __init__(self, *, supports_elicitation=True, reply=None):
        self.client_capabilities = FakeCaps({} if supports_elicitation else None)
        self._reply = reply
        self.asked = None

    async def elicit(self, message, schema):
        self.asked = message
        return self._reply


async def test_red_refuses_when_client_cannot_prompt(sandbox):
    ctx = FakeContext(supports_elicitation=False)
    with pytest.raises(Refused) as exc:
        await policy.confirm_red(ctx, tool="t", summary="Send a text message")
    assert "refused" in str(exc.value).lower()
    assert "JARVIS_ALLOWED_SHORTCUTS" in str(exc.value)


async def test_red_refuses_when_there_is_no_context_at_all(sandbox):
    with pytest.raises(Refused):
        await policy.confirm_red(None, tool="t", summary="Send a text message")


async def test_red_runs_when_user_accepts(sandbox):
    ctx = FakeContext(reply=FakeResult("accept", confirm=True))
    await policy.confirm_red(ctx, tool="t", summary="Send a text message")
    assert "Send a text message" in ctx.asked


async def test_red_refused_when_user_declines(sandbox):
    ctx = FakeContext(reply=FakeResult("decline"))
    with pytest.raises(Refused, match="Cancelled"):
        await policy.confirm_red(ctx, tool="t", summary="Send a text message")


async def test_red_refused_when_accepted_but_confirm_is_false(sandbox):
    """Accepting the dialog while leaving the box unchecked is still a no."""
    ctx = FakeContext(reply=FakeResult("accept", confirm=False))
    with pytest.raises(Refused, match="Cancelled"):
        await policy.confirm_red(ctx, tool="t", summary="Send a text message")


def _entries(sandbox):
    return [json.loads(line) for line in sandbox["audit"].read_text().splitlines()]


async def test_audit_records_success(sandbox):
    @guarded(Tier.GREEN)
    async def probe(value: str):
        return {"got": value}

    assert await probe(value="x") == {"got": "x"}
    (entry,) = _entries(sandbox)
    assert entry["tool"] == "probe"
    assert entry["tier"] == "GREEN"
    assert entry["outcome"] == "ok"
    assert entry["arguments"] == {"value": "x"}


async def test_audit_records_refusal_error_and_crash(sandbox):
    @guarded(Tier.RED)
    async def denied():
        raise Refused("nope")

    @guarded(Tier.AMBER)
    async def broken():
        raise RuntimeError("boom")

    @guarded(Tier.GREEN)
    async def buggy():
        raise KeyError("secret internals")

    # Refusals and explanatory errors become ToolError so the model can read them.
    with pytest.raises(ToolError, match="nope"):
        await denied()
    with pytest.raises(ToolError, match="boom"):
        await broken()
    # A real bug propagates untouched, for MCP to mask.
    with pytest.raises(KeyError):
        await buggy()

    outcomes = [(e["tool"], e["outcome"]) for e in _entries(sandbox)]
    assert outcomes == [
        ("denied", "refused"),
        ("broken", "error"),
        ("buggy", "crash"),
    ]
    # The audit log keeps the real detail even when the model does not see it.
    assert "secret internals" in _entries(sandbox)[2]["detail"]


async def test_audit_never_logs_the_context_object(sandbox):
    @guarded(Tier.RED)
    async def uses_ctx(name: str, ctx=None):
        return "ok"

    await uses_ctx(name="thing", ctx=FakeContext())
    (entry,) = _entries(sandbox)
    assert entry["arguments"] == {"name": "thing"}


async def test_audit_truncates_huge_arguments(sandbox):
    @guarded(Tier.GREEN)
    async def big(blob: str):
        return "ok"

    await big(blob="x" * 5000)
    (entry,) = _entries(sandbox)
    assert len(entry["arguments"]["blob"]) < 600
    assert "more chars" in entry["arguments"]["blob"]


async def test_broken_audit_log_does_not_break_the_tool(sandbox, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_LOG", "/proc/nonexistent/audit.jsonl")

    @guarded(Tier.GREEN)
    async def probe():
        return "still works"

    assert await probe() == "still works"


def test_guard_preserves_signature_for_schema_generation():
    """If this breaks, MCP silently generates the wrong tool schema."""
    import inspect

    async def original(name: str, limit: int = 5):
        return None

    wrapped = guarded(Tier.GREEN)(original)
    assert inspect.signature(wrapped) == inspect.signature(original)
    assert wrapped.__doc__ == original.__doc__
