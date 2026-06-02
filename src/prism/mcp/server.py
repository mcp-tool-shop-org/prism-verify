"""Prism MCP server — exposes verify and replay tools via MCP protocol."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Literal

from prism.core.engine import VerificationEngine
from prism.core.setup import build_default_engine
from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    ModelFamily,
    VerifyError,
    VerifyRequest,
)
from prism.receipts.store import ReceiptStore


def _setup_engine() -> VerificationEngine:
    """Initialize the verification engine with env-configured providers (shared factory)."""
    return build_default_engine()


def create_server() -> Any:
    """Create the MCP server with verify and replay tools."""
    try:
        from mcp.server import Server
        from mcp.types import TextContent, Tool
    except ImportError:
        print("Error: mcp package not installed. Install with: pip install prism-verify[mcp]",
              file=sys.stderr)
        sys.exit(1)

    server = Server("prism")
    engine = _setup_engine()
    receipt_store = ReceiptStore()

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="verify",
                description=(
                    "Verify an artifact against intent using family-different multi-lens "
                    "adjudication. Returns verdict (accept/revise/refuse/escalate), "
                    "confidence, findings, and a signed replayable receipt."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "artifact": {
                            "type": "string",
                            "description": (
                                "The artifact to verify: code, a tool-call, or a JSON array "
                                "of citations (when artifact_type=citations)"
                            ),
                        },
                        "intent": {
                            "type": "string",
                            "description": "What the artifact is supposed to do",
                        },
                        "artifact_type": {
                            "type": "string",
                            "enum": ["code", "tool_call", "citations"],
                            "default": "code",
                            "description": (
                                "Type of artifact (citations = a JSON array of citations to verify)"
                            ),
                        },
                        "caller_family": {
                            "type": "string",
                            "enum": ["anthropic", "openai", "google", "local"],
                            "description": "Caller's model family (excluded from verifier)",
                        },
                        "caller_model": {
                            "type": "string",
                            "description": "Caller's model ID (optional; defaults to 'unknown')",
                        },
                        "lenses": {
                            "type": "string",
                            "default": "auto",
                            "description": "Comma-separated lens names or 'auto'",
                        },
                    },
                    # caller_model is omitted: the handler defaults it to "unknown" (CLI/HTTP do
                    # too), so it is not genuinely required. artifact/intent/caller_family DO
                    # KeyError if absent — those stay required.
                    "required": ["artifact", "intent", "caller_family"],
                },
            ),
            Tool(
                name="replay",
                description=(
                    "Replay a verification receipt by ID. "
                    "Returns the full receipt with signature validation."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "receipt_id": {
                            "type": "string",
                            "description": "The receipt ID (prism-...)",
                        },
                    },
                    "required": ["receipt_id"],
                },
            ),
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        if name == "verify":
            return await _handle_verify(arguments, engine)
        elif name == "replay":
            return await _handle_replay(arguments, receipt_store)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


async def _handle_verify(arguments: dict[str, Any], engine: VerificationEngine) -> list[Any]:
    from mcp.types import TextContent

    # Parse lenses
    lenses_raw = arguments.get("lenses", "auto")
    lens_list: list[str] | Literal["auto"] = "auto"
    if lenses_raw != "auto":
        lens_list = [item.strip() for item in lenses_raw.split(",")]

    request = VerifyRequest(
        artifact=Artifact(
            type=ArtifactType(arguments.get("artifact_type", "code")),
            content=arguments["artifact"],
        ),
        intent=arguments["intent"],
        caller=CallerContext(
            model_family=ModelFamily(arguments["caller_family"]),
            model_id=arguments.get("caller_model", "unknown"),
        ),
        lenses=lens_list,
    )

    result = await engine.verify(request)

    if isinstance(result, VerifyError):
        output = {"error": result.model_dump()}
    else:
        output = result.model_dump()

    return [TextContent(type="text", text=json.dumps(output, indent=2, default=str))]


async def _handle_replay(arguments: dict[str, Any], receipt_store: ReceiptStore) -> list[Any]:
    from mcp.types import TextContent

    receipt_id = arguments["receipt_id"]
    data = receipt_store.get_receipt(receipt_id)

    if data is None:
        return [TextContent(type="text", text=f"Receipt not found: {receipt_id}")]

    valid = receipt_store.verify_signature(receipt_id)
    data["signature_valid"] = valid

    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def main() -> None:
    """Run the MCP server via stdio."""
    try:
        from mcp.server.stdio import stdio_server
    except ImportError:
        print("Error: mcp package not installed", file=sys.stderr)
        sys.exit(1)

    from prism.receipts.store import SigningSecretError

    try:
        server = create_server()
    except SigningSecretError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
