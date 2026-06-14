"""Prism CLI — `prism verify` and `prism replay`."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import click

from prism import __version__
from prism.core.types import (
    Artifact,
    ArtifactType,
    Budget,
    CallerContext,
    ModelFamily,
    ReasoningVisibility,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.probes.sycophancy import (
    HttpProducer,
    LlmComparator,
    ProbeResult,
    run_active_sycophancy,
)
from prism.providers.base import ModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from prism.core.engine import VerificationEngine
    from prism.eval.corpus import Sample
    from prism.eval.report import ReportData
    from prism.eval.runner import EvalRun
    from prism.receipts.store import ReceiptStore


# Opt-in (--gate) verdict-to-exit-code map for shell gating. Default (no --gate) stays exit 0 on
# any successful verification, preserving the CLI contract.
_GATE_EXIT_CODES = {"accept": 0, "revise": 10, "refuse": 20, "escalate": 30}


@click.group()
@click.version_option(version=__version__, prog_name="prism")  # static — works in the frozen binary
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
        # Running service should log: attach the prism.http stderr handler
        # (access log + dead-letter WARNs). Library imports stay quiet by default.
        app = create_app(configure_logging=True)
    except SigningSecretError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    uvicorn.run(app, host=host, port=port)


def _build_eval_engine(
    offline: bool, out_dir: Path
) -> tuple[VerificationEngine, str, ReceiptStore]:
    """Construct the engine for an eval run. Offline -> a deterministic mock verifier; real ->
    env-configured providers. Receipts go to a dedicated DB under --out (not the user's store).
    Returns the store too, so the caller can sign a run-level receipt and close it."""
    from prism.core.engine import VerificationEngine
    from prism.core.setup import build_providers_from_env, register_default_lenses
    from prism.receipts.store import ReceiptStore

    register_default_lenses()
    db = out_dir / "eval-receipts.db"
    if offline:
        from prism.eval.runner import MockProvider

        store = ReceiptStore(db_path=db, signing_secret=b"eval-offline-secret")
        engine = VerificationEngine(providers={"local": MockProvider()}, receipt_store=store)
        return engine, "offline-mock", store

    providers = build_providers_from_env()
    store = ReceiptStore(db_path=db)  # resolves a signing key from the env (refuses if none)
    label = "+".join(sorted(providers)) or "(no providers)"
    return VerificationEngine(providers=providers, receipt_store=store), label, store


def _write_run_receipt(
    store: ReceiptStore, report: ReportData, corpus_dir: Path, out_dir: Path
) -> None:
    """Sign a run-level receipt pinning the eval config + headline metrics, then export it
    (PIN_PER_STEP: the published numbers trace to a signed, replayable run)."""
    import hashlib

    from prism.core.types import ReasoningVisibility

    manifest = corpus_dir / "MANIFEST.json"
    corpus_hash = (
        hashlib.sha256(manifest.read_bytes()).hexdigest()
        if manifest.exists()
        else "no-corpus-manifest"
    )
    summary = {
        "verifier": report.verifier_label,
        "caller_family": report.caller_family,
        "n_runs": report.n_runs,
        "n_samples": report.n_samples,
        "verdict_accuracy": report.verdict_accuracy_overall,
        "krippendorff_alpha": report.krippendorff_alpha,
        "coverage_gain": report.coverage_gain,
        "ece": report.ece,
    }
    receipt = store.create_receipt(
        pre_strip_hash=corpus_hash,
        post_strip_hash=corpus_hash,
        verifier_models=[report.verifier_label],
        pairwise_rho={},
        reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
        verdict="accept",
        confidence=report.verdict_accuracy_overall,
        retryable=False,
        lens_results_json=json.dumps(summary),
        artifact_type="eval_run",
    )
    row = store.get_receipt(receipt.id)
    if row is not None:
        row["signature_valid"] = store.verify_signature(receipt.id)
        (out_dir / "run-receipt.json").write_text(
            json.dumps(row, indent=2, default=str), encoding="utf-8"
        )


def _build_same_family_control(
    offline: bool, out_dir: Path, caller_family: str
) -> VerificationEngine:
    """A same-family control engine for the Lock-1 A/B: route the caller family back to itself.

    The default router forbids same-family selection — that is Lock 1's whole point — so this is
    the ONLY place that sets the measurement-only ``allow_same_family=True`` bypass. It is scoped
    to this throwaway control engine (a private receipt DB under --out) and is never returned to or
    shared with the production engine / HTTP / MCP / verify path. Offline, the verifier is a
    deterministic SELF-PREFERRING mock (``same_family_self_preferring_policy``) that over-accepts,
    so the offline A/B yields a signed-positive delta proving the wiring (machinery, not data)."""
    from prism.core.engine import VerificationEngine
    from prism.core.routing import FamilyRouter
    from prism.core.setup import build_providers_from_env, register_default_lenses
    from prism.core.types import ModelFamily
    from prism.receipts.store import ReceiptStore

    register_default_lenses()
    fam = ModelFamily(caller_family)
    db = out_dir / "eval-control-receipts.db"
    # allow_same_family=True is the measurement-only Lock-1 bypass; scoped to this control engine.
    router = FamilyRouter(
        routing_map={fam: [(fam, f"{caller_family}-control")]}, allow_same_family=True
    )
    if offline:
        from prism.eval.runner import MockProvider, same_family_self_preferring_policy

        providers: dict[str, ModelProvider] = {
            caller_family: MockProvider(
                same_family_self_preferring_policy,
                family=fam,
                model_id=f"{caller_family}-control",
            )
        }
        store = ReceiptStore(db_path=db, signing_secret=b"eval-offline-secret")
    else:
        configured = build_providers_from_env()
        if caller_family not in configured:
            raise click.ClickException(
                f"--family-ab needs a provider for the caller family '{caller_family}' "
                "(set its API key) to run the same-family control."
            )
        providers = {caller_family: configured[caller_family]}
        store = ReceiptStore(db_path=db)
    return VerificationEngine(providers=providers, router=router, receipt_store=store)


def _run_family_ab(
    report: ReportData,
    treatment_run: EvalRun,
    samples: Sequence[Sample],
    content_hash: str,
    offline: bool,
    out: Path,
    caller_family: str,
    runs: int,
) -> None:
    """Run the same-family control arm and attach the paired Lock-1 A/B result — or SKIP it loudly.

    Fail-loud contract (F-01 1D): we NEVER emit a meaningless delta (the old bug measured
    family_different - 0.0 over zero rows, silently). Instead:
      (i)   pick_ab_pair runs FIRST on the discovered families; if the A/B cannot run (no caller
            provider -> no control, or no cross-family verifier -> no treatment) we print the named
            reason and skip. Offline is a synthetic wiring proof, so it bypasses discovery.
      (ii)  the control run gets the SAME corpus_content_hash and we ANDON-refuse on any mismatch.
      (iii) when n_paired == 0 (the control produced no genuine verdict — e.g. the Lock-1 bypass
            failed) we refuse rather than reporting delta = fd - 0.0.
    """
    from prism.eval.calibrate import compute_family_ab, discover_families, pick_ab_pair
    from prism.eval.runner import run_eval

    if not offline:
        from prism.core.setup import build_providers_from_env

        available = discover_families(build_providers_from_env())
        pair = pick_ab_pair(ModelFamily(caller_family), available)
        if not pair.ok:
            click.echo(f"Skipping --family-ab: {pair.reason}", err=True)
            return

    control = _build_same_family_control(offline, out, caller_family)
    control_run = asyncio.run(
        run_eval(
            control,
            samples,
            caller_family=caller_family,
            n_runs=runs,
            verifier_label="same-family-control",
            corpus_content_hash=content_hash,
        )
    )

    # ANDON: the two arms must be scored over byte-identical corpora or the delta is comparing
    # different things. Refuse on any content-hash mismatch.
    if control_run.corpus_content_hash != treatment_run.corpus_content_hash:
        raise click.ClickException(
            "--family-ab ANDON halt: the control arm's corpus content-hash "
            f"({control_run.corpus_content_hash!r}) does not match the treatment arm's "
            f"({treatment_run.corpus_content_hash!r}); refusing to report a cross-corpus delta."
        )

    ab = compute_family_ab(treatment_run, control_run)
    if ab.n_paired == 0:
        raise click.ClickException(
            "--family-ab ANDON halt: the same-family control arm produced no genuine verdict "
            "(Lock-1 bypass failed?), so there is nothing to pair; refusing to report delta = "
            "family_different - 0.0."
        )
    report.family_ab = ab


def _render_cjb_markdown(summary: object, label: str, runs: int, content_hash: str) -> str:
    """Render the CodeJudgeBench summary as a markdown table, cohesive with the corpus report style.

    ``summary`` is a ``CJBSummary``; typed ``object`` so this module does not eagerly import the
    benchmark harness (lazy-imported only inside ``_run_codejudgebench_cli``).
    """
    from prism.eval.benchmarks.harness import AccuracyPoint, CJBSummary

    assert isinstance(summary, CJBSummary)

    def _pt_row(p: AccuracyPoint) -> str:
        ci = f"[{p.accuracy_ci[0]:.3f}, {p.accuracy_ci[1]:.3f}]"
        return (
            f"| {p.label} | {p.correct}/{p.total} | {p.accuracy:.3f} {ci} | "
            f"{p.ties} | {p.tie_rate:.3f} |"
        )

    pc_lo, pc_hi = summary.position_consistency_ci
    lines: list[str] = []
    lines.append("# CodeJudgeBench - results (prism single-artifact -> pairwise preference)")
    lines.append("")
    lines.append(
        f"Verifier: **{label}** | runs/side: {runs} | scored items: {summary.n_items} | "
        f"unavailable (excluded): {summary.n_unavailable}"
    )
    lines.append(f"Content-hash of scored slice: `{content_hash[:12]}...`")
    lines.append("")
    for note in summary.notes:
        lines.append(f"> WARNING: {note}")
    if summary.notes:
        lines.append("")
    lines.append(
        "- Reduction: prism verifies CHOSEN and REJECTED code separately; `pairwise_prefer` ranks "
        "the two verdicts (accept>escalate>revise>refuse, tie-break by confidence). CORRECT iff "
        "prism prefers the CHOSEN side; a TIE is counted WRONG (real discrimination failure)."
    )
    lines.append(
        f"- **Position consistency (both orders agree): {summary.position_consistency:.3f}** "
        f"[{pc_lo:.3f}, {pc_hi:.3f}] (lower = an order-biased verifier)"
    )
    lines.append("")
    lines.append("## Accuracy (tie counted WRONG in the headline number)")
    lines.append("")
    lines.append("| Bucket | correct | accuracy (95% CI) | ties | tie-rate |")
    lines.append("|---|---|---|---|---|")
    lines.append(_pt_row(summary.overall))
    for p in summary.per_task:
        lines.append(_pt_row(p))
    lines.append("")
    if summary.per_producer:
        lines.append("## Per-producer (the model that wrote the responses)")
        lines.append("")
        lines.append("| Producer | correct | accuracy (95% CI) | ties | tie-rate |")
        lines.append("|---|---|---|---|---|")
        for p in summary.per_producer:
            lines.append(_pt_row(p))
        lines.append("")
    return "\n".join(lines)


def _write_cjb_receipt(
    store: ReceiptStore, summary: object, label: str, content_hash: str, out_dir: Path
) -> None:
    """Sign + export a run-level receipt pinning the CodeJudgeBench headline (PIN_PER_STEP)."""
    from prism.eval.benchmarks.harness import CJBSummary

    assert isinstance(summary, CJBSummary)
    receipt_summary = {
        "benchmark": "codejudgebench",
        "verifier": label,
        "n_items": summary.n_items,
        "n_unavailable": summary.n_unavailable,
        "overall_accuracy": summary.overall.accuracy,
        "tie_rate": summary.overall.tie_rate,
        "position_consistency": summary.position_consistency,
        "content_hash": content_hash,
    }
    receipt = store.create_receipt(
        pre_strip_hash=content_hash,
        post_strip_hash=content_hash,
        verifier_models=[label],
        pairwise_rho={},
        reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
        verdict="accept",
        confidence=summary.overall.accuracy,
        retryable=False,
        lens_results_json=json.dumps(receipt_summary),
        artifact_type="codejudgebench_run",
    )
    row = store.get_receipt(receipt.id)
    if row is not None:
        row["signature_valid"] = store.verify_signature(receipt.id)
        (out_dir / "run-receipt.json").write_text(
            json.dumps(row, indent=2, default=str), encoding="utf-8"
        )


def _run_codejudgebench_cli(
    *,
    offline: bool,
    caller_family: str,
    runs: int,
    out_dir: str,
    bench_task: str | None,
    bench_limit: int,
) -> None:
    """Load CodeJudgeBench, run prism over the pairs, render the table + sign a run receipt.

    Reuses ``_build_eval_engine`` (offline = deterministic mock; real = env providers) and the
    signed-run-receipt pattern. ``--offline`` loads the committed fixture (no network, no datasets).
    """
    from pathlib import Path

    from prism.eval.benchmarks.codejudgebench import cjb_content_hash, load_codejudgebench
    from prism.eval.benchmarks.harness import run_codejudgebench, summarize_codejudgebench
    from prism.receipts.store import SigningSecretError

    if offline and caller_family == "local":
        click.echo(
            "Error: --offline uses a LOCAL mock verifier, so the caller family cannot also be "
            "'local' (Lock 1 would exclude the only provider). Use --caller-family anthropic.",
            err=True,
        )
        sys.exit(1)

    try:
        items = load_codejudgebench(task=bench_task, limit=bench_limit, offline=offline)
    except (FileNotFoundError, ImportError, ValueError) as exc:
        click.echo(f"Error loading CodeJudgeBench: {exc}", err=True)
        sys.exit(1)
    if not items:
        click.echo("Error: CodeJudgeBench loaded 0 items (check --bench-task).", err=True)
        sys.exit(1)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    content_hash = cjb_content_hash(items)

    try:
        engine, label, store = _build_eval_engine(offline, out)
    except SigningSecretError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    try:
        results = asyncio.run(
            run_codejudgebench(engine, items, caller_family=caller_family, n_runs=runs)
        )
        summary = summarize_codejudgebench(results)
        markdown = _render_cjb_markdown(summary, label, runs, content_hash)
        (out / "codejudgebench.md").write_text(markdown, encoding="utf-8")
        _write_cjb_receipt(store, summary, label, content_hash, out)
    finally:
        store.close()
    click.echo(markdown)


@cli.command("eval")
@click.option("--corpus", "corpus_dir", default="eval/corpus", help="Corpus directory")
@click.option(
    "--split", type=click.Choice(["public", "fresh", "all"]), default="public", help="Corpus split"
)
@click.option("--runs", default=3, type=int, help="Runs per sample (variance control; N>=3)")
@click.option(
    "--caller-family",
    type=click.Choice(["anthropic", "openai", "google", "local"]),
    default="anthropic",
    help="Caller family (excluded from the verifier per Lock 1)",
)
@click.option("--report", "report_fmt", type=click.Choice(["md", "json"]), default="md")
@click.option("--out", "out_dir", default="eval/report", help="Directory for the report output")
@click.option(
    "--offline",
    is_flag=True,
    help="Use a deterministic MOCK verifier (smoke/CI; numbers are NOT a real measurement)",
)
@click.option(
    "--family-ab",
    "family_ab_flag",
    is_flag=True,
    help="Also run a same-family control to A/B-test Lock 1 (delta meaningful on real models)",
)
@click.option(
    "--build-corpus", "do_build", is_flag=True, help="(Re)generate the corpus to --corpus and exit"
)
@click.option(
    "--benchmark",
    type=click.Choice(["codejudgebench"]),
    default=None,
    help="Run an EXTERNAL pairwise benchmark instead of the corpus (codejudgebench).",
)
@click.option(
    "--bench-task",
    default=None,
    help="CodeJudgeBench task filter (codegen|codegen_pass5|coderepair|testgen); omit = all.",
)
@click.option(
    "--bench-limit",
    default=50,
    type=int,
    help="Cap items loaded (default 50). both-orders x N>=3 x 2 sides = up to 12 verify "
    "calls/pair, so the cap is load-bearing for spend; a published number needs a full-split run.",
)
def eval_cmd(
    corpus_dir: str,
    split: str,
    runs: int,
    caller_family: str,
    report_fmt: str,
    out_dir: str,
    offline: bool,
    family_ab_flag: bool,
    do_build: bool,
    benchmark: str | None,
    bench_task: str | None,
    bench_limit: int,
) -> None:
    """Measure prism's lenses on the labeled calibration corpus (Slice 1).

    Emits per-lens precision/recall, the inter-lens diversity matrix, submodular coverage-gain,
    verdict accuracy, and confidence calibration. `--offline` runs a deterministic mock for a
    no-cost smoke; a real measurement needs configured providers (Ollama or a hosted family key).
    """
    from pathlib import Path

    from prism.eval.corpus import build_corpus, check_corpus_integrity, load_corpus

    if do_build:
        manifest = build_corpus(Path(corpus_dir))
        click.echo(json.dumps(manifest, indent=2))
        return

    if benchmark == "codejudgebench":
        _run_codejudgebench_cli(
            offline=offline,
            caller_family=caller_family,
            runs=runs,
            out_dir=out_dir,
            bench_task=bench_task,
            bench_limit=bench_limit,
        )
        return

    if offline and caller_family == "local":
        click.echo(
            "Error: --offline uses a LOCAL mock verifier, so the caller family cannot also be "
            "'local' (Lock 1 would exclude the only provider). Use --caller-family anthropic.",
            err=True,
        )
        sys.exit(1)

    try:
        samples = load_corpus(Path(corpus_dir), split)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    if not samples:
        click.echo(f"Error: no samples for split={split!r} in {corpus_dir}", err=True)
        sys.exit(1)

    problems = check_corpus_integrity(samples)
    if problems:
        click.echo("Corpus integrity check FAILED (ANDON halt) - refusing to report:", err=True)
        for problem in problems[:10]:
            click.echo(f"  - {problem}", err=True)
        sys.exit(1)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from prism.eval.report import render_json, render_markdown, summarize
    from prism.eval.runner import run_eval
    from prism.receipts.store import SigningSecretError

    try:
        engine, label, store = _build_eval_engine(offline, out)
    except SigningSecretError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

    from prism.eval.corpus import corpus_content_hash

    content_hash = corpus_content_hash(samples)
    run = asyncio.run(
        run_eval(
            engine,
            samples,
            caller_family=caller_family,
            n_runs=runs,
            verifier_label=label,
            corpus_content_hash=content_hash,
        )
    )
    report = summarize(run)
    if family_ab_flag:
        _run_family_ab(report, run, samples, content_hash, offline, out, caller_family, runs)
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    (out / "report.json").write_text(render_json(report), encoding="utf-8")
    _write_run_receipt(store, report, Path(corpus_dir), out)
    store.close()
    click.echo(render_markdown(report) if report_fmt == "md" else render_json(report))


# ── probe-sycophancy: the v2 ACTIVE probe over a live producer ─────────────────────────────────

# Probe verdict -> prism Verdict.value (signed receipt) and -> exit code (--gate).
_PROBE_VERDICT_MAP = {"sycophantic": "revise", "not_sycophantic": "accept", "abstain": "escalate"}
_PROBE_GATE_EXIT = {"not_sycophantic": 0, "sycophantic": 10, "abstain": 30}


def _load_arg(value: str) -> str:
    """Return the literal, or the file contents when the value is '@path'."""
    if value.startswith("@"):
        try:
            with open(value[1:], encoding="utf-8") as fh:
                return fh.read()
        except FileNotFoundError:
            click.echo(f"Error: file not found: {value[1:]}", err=True)
            sys.exit(1)
    return value


def _build_probe_comparator(name: str, model: str | None) -> LlmComparator:
    """Build the cross-family agreement judge (an LlmComparator over a prism ModelProvider).

    Default 'ollama' is family-different from the hosted producers the probe usually targets; the
    judge only decides whether two COMMITTED answers agree, so a small local model suffices.
    """
    import os

    provider: ModelProvider
    if name == "ollama":
        from prism.providers.ollama import OllamaProvider

        provider = OllamaProvider()
    elif name == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            click.echo("Error: ANTHROPIC_API_KEY not set", err=True)
            sys.exit(1)
        from prism.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key=key)
    elif name == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            click.echo("Error: OPENAI_API_KEY not set", err=True)
            sys.exit(1)
        from prism.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key=key)
    else:  # google
        key = os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            click.echo("Error: GOOGLE_API_KEY not set", err=True)
            sys.exit(1)
        from prism.providers.google import GoogleProvider

        provider = GoogleProvider(api_key=key)
    return LlmComparator(provider, model)


def _sign_probe_receipt(
    context: str,
    answer: str,
    aggregate: ProbeResult,
    per_probe: list[ProbeResult],
    producer_model: str,
    comparator_label: str,
) -> str:
    """Sign + store a replayable receipt for one probe run; return the receipt id.

    The probe is mechanism-diverse (re-querying a producer), so — like a citation receipt — it has
    no lens ensemble; the per-probe results are pinned into lens_results_json.
    """
    store = _open_store()
    try:
        digest = hashlib.sha256(f"{context}\n\n{answer}".encode()).hexdigest()
        receipt = store.create_receipt(
            pre_strip_hash=digest,
            post_strip_hash=digest,
            verifier_models=[producer_model, comparator_label],
            pairwise_rho={},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict=_PROBE_VERDICT_MAP.get(aggregate.verdict, "escalate"),
            confidence=0.9 if aggregate.verdict != "abstain" else 0.5,
            retryable=aggregate.verdict == "sycophantic",
            lens_results_json=json.dumps(
                [
                    {
                        "probe": r.probe,
                        "verdict": r.verdict,
                        "detail": r.detail,
                        "flipped": r.flipped,
                    }
                    for r in per_probe
                ]
            ),
            artifact_type="response",
        )
        return receipt.id
    finally:
        store.close()


@cli.command("probe-sycophancy")
@click.option(
    "--producer-endpoint",
    required=True,
    help="OpenAI-compatible base URL of the producer (model under test) to re-query",
)
@click.option("--producer-model", default="producer", help="Model id sent to the producer")
@click.option("--context", "-c", required=True, help="The user turn / question (or @file)")
@click.option(
    "--answer", required=True, help="The producer's original COMMITTED answer (or @file)"
)
@click.option(
    "--reference",
    default=None,
    help="Correctness reference for the capitulation anchor (or @file)",
)
@click.option(
    "--context-for",
    "context_for",
    default=None,
    help="Counterfactual (INV) probe: user on side A (needs --context-against)",
)
@click.option(
    "--context-against",
    "context_against",
    default=None,
    help="Counterfactual (INV) probe: the same question, user's stance reversed",
)
@click.option(
    "--comparator-provider",
    default="ollama",
    type=click.Choice(["ollama", "anthropic", "openai", "google"]),
    help="Cross-family agreement judge (default ollama)",
)
@click.option("--comparator-model", default=None, help="Override the comparator model id")
@click.option(
    "--receipt/--no-receipt",
    "make_receipt",
    default=False,
    help="Sign + store a replayable receipt (needs a signing key; default off)",
)
@click.option(
    "--gate",
    is_flag=True,
    help="Exit by verdict (0 not_sycophantic, 10 sycophantic, 30 abstain).",
)
def probe_sycophancy(
    producer_endpoint: str,
    producer_model: str,
    context: str,
    answer: str,
    reference: str | None,
    context_for: str | None,
    context_against: str | None,
    comparator_provider: str,
    comparator_model: str | None,
    make_receipt: bool,
    gate: bool,
) -> None:
    """Run the v2 ACTIVE sycophancy probe against a live producer.

    Re-queries the producer under a pinned content-free rebuttal (capitulation, a DIR test) and —
    when --context-for/--context-against are given, under a reversed user stance (a counterfactual
    INV test). A flip is flagged ONLY when anchored to a correctness --reference; otherwise it
    abstains. The agreement judge is a DIFFERENT family by default (decorrelation). Emits JSON.
    """
    ctx = _load_arg(context)
    ans = _load_arg(answer)
    ref = _load_arg(reference) if reference else None

    if (context_for is None) != (context_against is None):
        click.echo("Error: --context-for and --context-against must be given together", err=True)
        sys.exit(1)
    counterfactual: tuple[str, str] | None = None
    if context_for is not None and context_against is not None:
        counterfactual = (_load_arg(context_for), _load_arg(context_against))

    producer = HttpProducer(producer_endpoint, producer_model)
    comparator = _build_probe_comparator(comparator_provider, comparator_model)

    aggregate, per_probe = asyncio.run(
        run_active_sycophancy(
            producer,
            ctx,
            ans,
            comparator=comparator,
            reference=ref,
            counterfactual_contexts=counterfactual,
        )
    )

    out: dict[str, object] = {
        "verdict": aggregate.verdict,
        "probe": aggregate.probe,
        "detail": aggregate.detail,
        "flipped": aggregate.flipped,
        "probes": [
            {"probe": r.probe, "verdict": r.verdict, "detail": r.detail, "flipped": r.flipped}
            for r in per_probe
        ],
    }
    if make_receipt:
        out["receipt_id"] = _sign_probe_receipt(
            ctx, ans, aggregate, per_probe, producer_model, comparator_model or comparator_provider
        )

    click.echo(json.dumps(out, indent=2, default=str))
    if gate:
        sys.exit(_PROBE_GATE_EXIT.get(aggregate.verdict, 0))


@cli.command("calibrate-sycophancy-panel")
@click.option(
    "--votes",
    "votes_path",
    required=True,
    help='JSONL of {"votes": ["sycophantic"|"not_sycophantic"|"abstain", ...], "gold": "..."}',
)
@click.option(
    "--min-clear",
    default=2,
    type=int,
    help="Genuine not_sycophantic votes required to ACCEPT (the panel-clear floor)",
)
def calibrate_sycophancy_panel(votes_path: str, min_clear: int) -> None:
    """Offline calibration sweep for the sycophancy panel emission gate (the deferred alpha-fit).

    Reads recorded panel votes + gold labels and reports, per agreement-threshold k, the false-flag
    rate / recall / coverage / false-clears so the director can pin k (and the target alpha) BEFORE
    the panel is served. The live half — producing the votes from the served panel on the OOD set —
    is Mike-gated.
    """
    from prism.core.sycophancy_panel import outcome_from_str, sweep_agreement_k
    from prism.core.types import LensOutcome

    records: list[tuple[list[LensOutcome], str]] = []
    try:
        with open(votes_path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                obj = json.loads(line)
                votes = [outcome_from_str(str(v)) for v in obj["votes"]]
                records.append((votes, str(obj["gold"])))
    except FileNotFoundError:
        click.echo(f"Error: file not found: {votes_path}", err=True)
        sys.exit(1)
    except (KeyError, ValueError) as exc:
        click.echo(f"Error: malformed votes file: {exc}", err=True)
        sys.exit(1)

    if not records:
        click.echo(f"Error: no records in {votes_path}", err=True)
        sys.exit(1)

    rows = sweep_agreement_k(records, min_clear=min_clear)
    click.echo(json.dumps([asdict(row) for row in rows], indent=2))


if __name__ == "__main__":
    cli()
