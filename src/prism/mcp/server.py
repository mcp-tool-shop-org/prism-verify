"""Prism MCP server — exposes verify and replay tools via MCP protocol."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from prism.core.engine import VerificationEngine
from prism.core.types import (
    Artifact,
    ArtifactType,
    Budget,
    CallerContext,
    ModelFamily,
    ReasoningVisibility,
    VerifyError,
    VerifyRequest,
)
from prism.lenses.boundary import CrossBoundaryLens
from prism.lenses.contract import ContractCompletenessLens
from prism.lenses.groundedness import GroundednessLens
from prism.lenses.invariant import InvariantLens
from prism.lenses.registry import register_lens
from prism.receipts.store import ReceiptStore


def _setup_engine() -> VerificationEngine:
    """Initialize the verification engine with available providers."""
    # Register lenses
    register_lens(ContractCompletenessLens())
    register_lens(CrossBoundaryLens())
    register_lens(InvariantLens())
    register_lens(GroundednessLens())

    providers = {}

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


def create_server():
    """Create the MCP server with verify and replay tools."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError:
        print("Error: mcp package not installed. Install with: pip install prism-verify[mcp]",
              file=sys.stderr)
        sys.exit(1)

    server = Server("prism")
    engine = _setup_engine()
    receipt_store = ReceiptStore()

    @server.list_tools()
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
                description="Replay a verification receipt by ID. Returns the full receipt with signature validation.",
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

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "verify":
            return await _handle_verify(arguments, engine)
        elif name == "replay":
            return await _handle_replay(arguments, receipt_store)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


async def _handle_verify(arguments: dict, engine: VerificationEngine) -> list:
    from mcp.types import TextContent

    # Parse lenses
    lenses_raw = arguments.get("lenses", "auto")
    lens_list: list[str] | str = "auto"
    if lenses_raw != "auto":
        lens_list = [l.strip() for l in lenses_raw.split(",")]

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


async def _handle_replay(arguments: dict, receipt_store: ReceiptStore) -> list:
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

    server = create_server()

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
