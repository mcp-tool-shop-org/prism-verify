"""Prism CLI — `prism verify` and `prism replay`."""

from __future__ import annotations

import asyncio
import json
import sys

import click

from prism.core.types import (
    Artifact,
    ArtifactType,
    Budget,
    CallerContext,
    ModelFamily,
    VerifyError,
    VerifyRequest,
)


@click.group()
@click.version_option(package_name="prism-verify")
def cli() -> None:
    """Prism — runtime adjudication for agent workflows."""
    pass


@cli.command()
@click.option("--artifact", "-a", required=True, help="Artifact content or @file path")
@click.option("--intent", "-i", required=True, help="What the artifact is supposed to do")
@click.option(
    "--type",
    "artifact_type",
    type=click.Choice(["code", "tool_call"]),
    default="code",
    help="Artifact type",
)
@click.option(
    "--caller-family",
    type=click.Choice(["anthropic", "openai", "google", "local"]),
    default="anthropic",
    help="Caller's model family (will be excluded from verifier)",
)
@click.option("--caller-model", default="claude-sonnet-4-6", help="Caller's model ID")
@click.option(
    "--lenses",
    default="auto",
    help="Comma-separated lens names or 'auto'",
)
@click.option("--max-latency-ms", default=5000, type=int, help="Latency budget in ms")
@click.option("--provider", default="ollama", help="Provider to use (ollama, anthropic)")
def verify(
    artifact: str,
    intent: str,
    artifact_type: str,
    caller_family: str,
    caller_model: str,
    lenses: str,
    max_latency_ms: int,
    provider: str,
) -> None:
    """Verify an artifact against intent through multi-lens adjudication."""
    # Load artifact from file if prefixed with @
    if artifact.startswith("@"):
        filepath = artifact[1:]
        try:
            with open(filepath) as f:
                artifact_content = f.read()
        except FileNotFoundError:
            click.echo(f"Error: file not found: {filepath}", err=True)
            sys.exit(1)
    else:
        artifact_content = artifact

    # Parse lenses
    lens_list: list[str] | str = "auto"
    if lenses != "auto":
        lens_list = [l.strip() for l in lenses.split(",")]

    request = VerifyRequest(
        artifact=Artifact(
            type=ArtifactType(artifact_type),
            content=artifact_content,
        ),
        intent=intent,
        caller=CallerContext(
            model_family=ModelFamily(caller_family),
            model_id=caller_model,
        ),
        lenses=lens_list,
        budget=Budget(max_latency_ms=max_latency_ms),
    )

    result = asyncio.run(_run_verify(request, provider))

    # Output JSON
    if isinstance(result, VerifyError):
        output = {"error": result.model_dump()}
        click.echo(json.dumps(output, indent=2, default=str))
        sys.exit(1)
    else:
        click.echo(json.dumps(result.model_dump(), indent=2, default=str))


async def _run_verify(request: VerifyRequest, provider_name: str):
    """Set up engine and run verification."""
    from prism.core.engine import VerificationEngine
    from prism.lenses.boundary import CrossBoundaryLens
    from prism.lenses.contract import ContractCompletenessLens
    from prism.lenses.groundedness import GroundednessLens
    from prism.lenses.invariant import InvariantLens
    from prism.lenses.registry import register_lens

    # Register default lenses
    register_lens(ContractCompletenessLens())
    register_lens(CrossBoundaryLens())
    register_lens(InvariantLens())
    register_lens(GroundednessLens())

    # Set up provider
    providers = {}
    if provider_name == "ollama":
        from prism.providers.ollama import OllamaProvider

        providers["local"] = OllamaProvider()
    elif provider_name == "anthropic":
        import os

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            click.echo("Error: ANTHROPIC_API_KEY not set", err=True)
            sys.exit(1)
        from prism.providers.anthropic import AnthropicProvider

        providers["anthropic"] = AnthropicProvider(api_key=api_key)

    engine = VerificationEngine(providers=providers)
    return await engine.verify(request)


@cli.command()
@click.argument("receipt_id")
def replay(receipt_id: str) -> None:
    """Replay a verification receipt."""
    from prism.receipts.store import ReceiptStore

    store = ReceiptStore()
    data = store.get_receipt(receipt_id)

    if data is None:
        click.echo(f"Receipt not found: {receipt_id}", err=True)
        sys.exit(1)

    # Verify signature
    valid = store.verify_signature(receipt_id)
    data["signature_valid"] = valid

    click.echo(json.dumps(data, indent=2, default=str))
    store.close()


if __name__ == "__main__":
    cli()
