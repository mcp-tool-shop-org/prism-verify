"""Prism CLI — `prism verify` and `prism replay`."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import click

from prism.core.types import (
    Artifact,
    ArtifactType,
    Budget,
    CallerContext,
    ModelFamily,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.providers.base import ModelProvider

if TYPE_CHECKING:
    from prism.receipts.store import ReceiptStore


# Opt-in (--gate) verdict-to-exit-code map for shell gating. Default (no --gate) stays exit 0 on
# any successful verification, preserving the CLI contract.
_GATE_EXIT_CODES = {"accept": 0, "revise": 10, "refuse": 20, "escalate": 30}


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
    type=click.Choice(["code", "tool_call", "citations"]),
    default="code",
    help="Artifact type (citations = a JSON array of citations to verify)",
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
@click.option(
    "--gate",
    is_flag=True,
    help="Exit by verdict for shell gating (0 accept, 10 revise, 20 refuse, 30 escalate).",
)
def verify(
    artifact: str,
    intent: str,
    artifact_type: str,
    caller_family: str,
    caller_model: str,
    lenses: str,
    max_latency_ms: int,
    provider: str,
    gate: bool,
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
    lens_list: list[str] | Literal["auto"] = "auto"
    if lenses != "auto":
        lens_list = [item.strip() for item in lenses.split(",")]

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

    click.echo(json.dumps(result.model_dump(), indent=2, default=str))
    if gate:
        # Opt-in verdict-coded exit for shell gating; the default stays exit 0 on success.
        sys.exit(_GATE_EXIT_CODES.get(result.verdict.value, 0))


async def _run_verify(request: VerifyRequest, provider_name: str) -> VerifyResponse | VerifyError:
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
    providers: dict[str, ModelProvider] = {}
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

    from prism.receipts.store import SigningSecretError

    try:
        engine = VerificationEngine(providers=providers)
    except SigningSecretError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    return await engine.verify(request)


def _open_store() -> ReceiptStore:
    """Construct a ReceiptStore, surfacing a missing signing secret as a clean error."""
    from prism.receipts.store import ReceiptStore, SigningSecretError

    try:
        return ReceiptStore()
    except SigningSecretError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)


@cli.command()
@click.argument("receipt_id")
def replay(receipt_id: str) -> None:
    """Replay a verification receipt."""
    store = _open_store()
    try:
        data = store.get_receipt(receipt_id)
        if data is None:
            click.echo(f"Receipt not found: {receipt_id}", err=True)
            sys.exit(1)
        data["signature_valid"] = store.verify_signature(receipt_id)
        click.echo(json.dumps(data, indent=2, default=str))
    finally:
        store.close()


@cli.command("verify-receipt")
@click.argument("receipt_file")
@click.option(
    "--public-key",
    "public_key",
    default=None,
    help="Ed25519 public key (PEM or path) — verifies a receipt from a DIFFERENT prism with NO "
    "shared secret. Omit to verify against this deploy's configured key.",
)
def verify_receipt(receipt_file: str, public_key: str | None) -> None:
    """Cryptographically verify a standalone receipt JSON (a `prism replay` / API export).

    With --public-key, an Ed25519 receipt verifies with only the public key — the cross-tool path
    a consumer (e.g. role-os) uses to confirm a prism verdict it did not produce. Exit 0 if the
    signature is valid, 1 if not (or the receipt/key is unreadable).
    """
    try:
        with open(receipt_file) as f:
            receipt = json.load(f)
    except FileNotFoundError:
        click.echo(f"Error: file not found: {receipt_file}", err=True)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        click.echo(f"Error: receipt is not valid JSON: {exc}", err=True)
        sys.exit(1)

    from prism.receipts.signing import ALG_HMAC, SigningSecretError

    alg = receipt.get("alg", ALG_HMAC)
    if public_key is not None:
        from prism.receipts.store import verify_receipt_dict

        try:
            valid = verify_receipt_dict(receipt, public_key_pem=public_key)
        except SigningSecretError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
    else:
        store = _open_store()
        try:
            valid = store.verify_receipt(receipt)
        finally:
            store.close()

    click.echo(
        json.dumps(
            {"receipt_id": receipt.get("id"), "alg": alg, "signature_valid": valid}, indent=2
        )
    )
    sys.exit(0 if valid else 1)


@cli.command()
@click.option("--out", "out_path", default=None, help="Write the private-key PEM here (chmod 600)")
def keygen(out_path: str | None) -> None:
    """Generate an Ed25519 keypair for signing receipts (the production default).

    Set PRISM_SIGNING_KEY to the written private key to sign receipts with it; publish the public
    key (see `prism pubkey`) so consumers can verify your receipts without your secret.
    """
    from prism.receipts.signing import generate_keypair

    private_pem, public_pem, kid = generate_keypair()
    if out_path:
        import os
        import stat
        from pathlib import Path

        path = Path(out_path).expanduser()
        path.write_text(private_pem)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600 (no-op on Windows)
        except OSError:
            pass
        click.echo(
            json.dumps(
                {"private_key_written": str(path), "kid": kid, "public_key": public_pem}, indent=2
            )
        )
        click.echo(f"\nNext: export PRISM_SIGNING_KEY={path}", err=True)
    else:
        click.echo(
            json.dumps({"private_key": private_pem, "public_key": public_pem, "kid": kid}, indent=2)
        )


@cli.command()
def pubkey() -> None:
    """Print the configured Ed25519 public key + key id — the key consumers verify receipts with."""
    from prism.receipts.signing import (
        ALG_ED25519,
        Ed25519Backend,
        SigningSecretError,
        resolve_backends,
    )

    try:
        active, _ = resolve_backends()
    except SigningSecretError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    if not isinstance(active, Ed25519Backend):
        click.echo(
            "Error: the active signing backend is HMAC (symmetric) — there is no public key to "
            "publish. Configure an Ed25519 key (PRISM_SIGNING_KEY) or run `prism keygen`.",
            err=True,
        )
        sys.exit(1)
    click.echo(
        json.dumps(
            {"kid": active.kid, "alg": ALG_ED25519, "public_key": active.public_key_pem()}, indent=2
        )
    )


def _parse_duration(value: str) -> timedelta:
    """Parse a duration like 90d, 24h, 30m, 45s, 2w into a timedelta."""
    match = re.fullmatch(r"\s*(\d+)\s*([smhdw])\s*", value.lower())
    if not match:
        raise click.BadParameter(
            f"invalid duration {value!r}; use forms like 90d, 24h, 30m, 45s, 2w"
        )
    unit_seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return timedelta(seconds=int(match.group(1)) * unit_seconds[match.group(2)])


@cli.group()
def receipt() -> None:
    """Manage stored verification receipts (compensators for the receipt store)."""
    pass


@receipt.command("delete")
@click.argument("receipt_id")
def receipt_delete(receipt_id: str) -> None:
    """Delete a single receipt by ID."""
    store = _open_store()
    try:
        removed = store.delete_receipt(receipt_id)
    finally:
        store.close()

    if not removed:
        click.echo(f"Receipt not found: {receipt_id}", err=True)
        sys.exit(1)
    click.echo(json.dumps({"deleted": receipt_id}, indent=2))


@receipt.command("prune")
@click.option("--older-than", required=True, help="Age threshold, e.g. 90d, 24h, 30m")
@click.option("--yes", is_flag=True, help="Confirm the irreversible bulk deletion")
def receipt_prune(older_than: str, yes: bool) -> None:
    """Delete every receipt older than a duration (irreversible)."""
    duration = _parse_duration(older_than)
    if not yes:
        click.echo(
            f"Refusing to prune receipts older than {older_than} without --yes "
            "(irreversible; export first if the audit trail matters).",
            err=True,
        )
        sys.exit(1)

    store = _open_store()
    try:
        count = store.prune(duration)
    finally:
        store.close()
    click.echo(json.dumps({"pruned": count, "older_than": older_than}, indent=2))


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host (default loopback)")
@click.option("--port", default=8000, type=int, help="Bind port")
def serve(host: str, port: int) -> None:
    """Run the prism HTTP API (requires the [http] extra: pip install prism-verify[http])."""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "Error: HTTP extra not installed. Install with: pip install 'prism-verify[http]'",
            err=True,
        )
        sys.exit(1)

    from prism.http import create_app
    from prism.receipts.store import SigningSecretError

    try:
        app = create_app()
    except SigningSecretError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
