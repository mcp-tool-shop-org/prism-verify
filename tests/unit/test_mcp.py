"""Tests for the prism MCP server tool schemas."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")  # the MCP server is an optional extra (prism-verify[mcp])


async def _list_tools(monkeypatch):
    """Build the server (env-configured) and invoke its registered list_tools handler.

    PRISM_DEV=1 lets the receipt store resolve a (dev) signing key so create_server() doesn't
    raise SigningSecretError; no provider keys are needed because we only inspect the schema.
    """
    monkeypatch.setenv("PRISM_DEV", "1")
    monkeypatch.delenv("PRISM_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("PRISM_SIGNING_KEY", raising=False)
    from mcp.types import ListToolsRequest

    from prism.mcp.server import create_server

    server = create_server()
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    return {tool.name: tool for tool in result.root.tools}


async def test_verify_tool_does_not_require_caller_model(monkeypatch):
    """SURF-A-004: caller_model is optional (handler defaults it to 'unknown'), so it must NOT
    appear in the verify tool's `required` array — but it stays an advertised property, and the
    genuinely-required inputs (artifact / intent / caller_family) remain required."""
    tools = await _list_tools(monkeypatch)
    verify = tools["verify"]
    schema = verify.inputSchema
    required = schema["required"]

    assert "caller_model" not in required  # the SURF-A-004 fix
    assert "caller_model" in schema["properties"]  # still advertised, just optional
    assert set(required) == {"artifact", "intent", "caller_family"}


async def test_replay_tool_requires_receipt_id(monkeypatch):
    """Sanity: the replay tool still requires receipt_id (guards against a copy-paste regression
    that loosens the wrong schema)."""
    tools = await _list_tools(monkeypatch)
    assert tools["replay"].inputSchema["required"] == ["receipt_id"]
