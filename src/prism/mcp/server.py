"""Prism MCP server — exposes verify and replay tools via MCP protocol."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Literal

from prism.core.engine import VerificationEngine
from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    ModelFamily,
    VerifyError,
    VerifyRequest,
)
from prism.lenses.boundary import CrossBoundaryLens
from prism.lenses.contract import ContractCompletenessLens
from prism.lenses.groundedness import GroundednessLens
from prism.lenses.invariant import InvariantLens
from prism.lenses.registry import register_lens
from prism.providers.base import ModelProvider
from prism.receipts.store import ReceiptStore


def _setup_engine() -> VerificationEngine:
    """Initialize the verification engine with available providers."""
    # Register lenses
    register_lens(ContractCompletenessLens())
    register_lens(CrossBoundaryLens())
    register_lens(InvariantLens())
    register_lens(GroundednessLens())

    providers: dict[str, ModelProvider] = {}

    # Always try Ollama (local, free)
    from prism.providers.ollama import OllamaProvider

    providers["local"] = OllamaProvider()

    # Anthropic if key available
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        from prism.providers.anthropic import AnthropicProvider

        providers["anthropic"] = AnthropicProvider(api_key=anthropic_key)

    # OpenAI if key available
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        from prism.providers.openai import OpenAIProvider

        providers["openai"] = OpenAIProvider(api_key=openai_key)

    # Google if key available
    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key:
        from prism.providers.google import GoogleProvider

        providers["google"] = GoogleProvider(api_key=google_key)

    return VerificationEngine(providers=providers)


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
                            "description": "The code or tool-call content to verify",
                        },
                        "intent": {
                            "type": "string",
                            "description": "What the artifact is supposed to do",
                        },
                        "artifact_type": {
                            "type": "string",
                            "enum": ["code", "tool_call"],
                            "default": "code",
                            "description": "Type of artifact",
                        },
                        "caller_family": {
                            "type": "string",
                            "enum": ["anthropic", "openai", "google", "local"],
                            "description": "Caller's model family (excluded from verifier)",
                        },
                        "caller_model": {
                            "type": "string",
                            "description": "Caller's model ID",
                        },
                        "lenses": {
                            "type": "string",
                            "default": "auto",
                            "description": "Comma-separated lens names or 'auto'",
                        },
                    },
                    "required": ["artifact", "intent", "caller_family", "caller_model"],
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
