"""prism HTTP/FastAPI surface (v0.4) — the same guarantees as the CLI/MCP, over HTTP.

A thin transport over ``engine.verify()``: family-different routing, reasoning-stripping, ANDON
refusals (as RFC 9457 problem+json), and signed replayable receipts are all the engine's — the
HTTP layer adds auth, idempotency, rate-limit/size back-pressure, an async-via-webhook escalate
path, and ``POST /verify-receipt`` for cross-tool receipt verification. See ``design/05``.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any, Literal

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from prism import __version__
from prism.core.engine import VerificationEngine
from prism.core.setup import build_providers_from_env, register_default_lenses
from prism.core.types import (
    Artifact,
    ArtifactType,
    Budget,
    CallerContext,
    ModelFamily,
    VerifyError,
    VerifyRequest,
)
from prism.http.auth import Authenticator, load_key_hashes
from prism.http.errors import ProblemError, install_problem_handler
from prism.http.webhook import (
    Resolver,
    Sender,
    WebhookError,
    assert_safe_url,
    deliver,
    verdict_body,
)
from prism.receipts.store import ReceiptStore, verify_receipt_dict

DEFAULT_MAX_ARTIFACT_BYTES = 256 * 1024

# Idempotency cache bounds (SURF-A-001). Idempotency only matters for the client retry window, so
# completed entries expire after IDEMPOTENCY_TTL_S; the LRU ceiling caps memory even within the TTL
# (a caller with a valid key could otherwise stream unbounded distinct Idempotency-Keys). 10k keys
# over a 10-minute window is generous for a single-process v0.4 service.
IDEMPOTENCY_MAX = 10_000
IDEMPOTENCY_TTL_S = 600.0

# Dead-letter ring bound (SURF-A-003) — most-recent async failures kept for /healthz visibility;
# every append also emits a structured log so nothing is silently buried.
DEAD_LETTER_MAX = 1000

logger = logging.getLogger("prism.http")


class IdempotencyCache:
    """Bounded, TTL'd idempotency store (SURF-A-001).

    Holds ``key -> (fingerprint, payload | None-while-in-flight, status, stored_at)`` so a replay
    returns a byte-identical body at the original status (200 sync, 202 async). Entries expire
    ``ttl_s`` after they are stored and the map is LRU-capped at ``max_entries`` — expired entries
    are evicted opportunistically on every insert, and overflow drops the oldest.
    """

    def __init__(
        self,
        *,
        max_entries: int = IDEMPOTENCY_MAX,
        ttl_s: float = IDEMPOTENCY_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_entries
        self._ttl = ttl_s
        self._clock = clock
        self._store: OrderedDict[str, tuple[str, dict[str, Any] | None, int, float]] = OrderedDict()

    def get(self, key: str) -> tuple[str, dict[str, Any] | None, int] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        fingerprint, payload, status, stored_at = entry
        if self._clock() - stored_at >= self._ttl:
            del self._store[key]
            return None
        # NB: no move_to_end here — entries expire by store-time TTL regardless of access, so the
        # map stays ordered by stored_at, which keeps _evict_expired's early-break correct.
        return fingerprint, payload, status

    def set(self, key: str, fingerprint: str, payload: dict[str, Any] | None, status: int) -> None:
        self._evict_expired()
        self._store[key] = (fingerprint, payload, status, self._clock())
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)  # drop the oldest (LRU overflow)

    def pop(self, key: str) -> None:
        self._store.pop(key, None)

    def _evict_expired(self) -> None:
        now = self._clock()
        for k in list(self._store):
            if now - self._store[k][3] >= self._ttl:
                del self._store[k]
            else:
                break  # OrderedDict is insertion-ordered; the rest are newer


class VerifyHttpRequest(BaseModel):
    """POST /verify body — mirrors the CLI/MCP verify arguments."""

    artifact: str
    intent: str = Field(min_length=1, max_length=4000)
    artifact_type: Literal["code", "tool_call", "citations"] = "code"
    caller_family: Literal["anthropic", "openai", "google", "local"]
    caller_model: str = "unknown"
    lenses: str = "auto"
    max_latency_ms: int = Field(default=5000, ge=1000, le=30000)
    webhook: str | None = Field(
        default=None,
        description="https endpoint for async (Prefer: respond-async) escalate delivery",
    )


class VerifyReceiptHttpRequest(BaseModel):
    """POST /verify-receipt body — verify a standalone receipt (a replay/export)."""

    receipt: dict[str, Any]
    public_key: str | None = Field(
        default=None,
        description="Ed25519 public-key PEM to verify a receipt from a different prism (no secret)",
    )


_IpNetworks = list[ipaddress.IPv4Network | ipaddress.IPv6Network]


def _parse_trusted_proxies(value: str | None) -> _IpNetworks:
    """Parse ``PRISM_TRUSTED_PROXIES`` (comma-separated CIDRs) into networks.

    Default/empty → an empty list = today's exact behavior (no ``X-Forwarded-For`` trust). A bare
    address (``10.0.0.1``) is accepted and treated as a /32 (or /128). Unparseable entries are
    skipped so one typo cannot silently disable the limiter for every other configured proxy.
    """
    if not value:
        return []
    networks: _IpNetworks = []
    for part in value.split(","):
        cidr = part.strip()
        if not cidr:
            continue
        with suppress(ValueError):
            networks.append(ipaddress.ip_network(cidr, strict=False))
    return networks


def _is_trusted(ip_str: str, trusted: _IpNetworks) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in trusted)


def _client_ip(request: Request, trusted_proxies: _IpNetworks) -> str:
    """Resolve the rate-limit client IP, honoring ``X-Forwarded-For`` ONLY behind a trusted proxy.

    The direct TCP peer (``request.client.host``) is authoritative. When (and only when) that peer
    is within a configured ``PRISM_TRUSTED_PROXIES`` CIDR do we read ``X-Forwarded-For`` and return
    the right-most hop NOT in the trusted set — the real client just beyond our trusted proxy tier.
    XFF from an untrusted peer is IGNORED: trusting it would let an attacker rotate the header per
    request to dodge the per-IP failed-auth limiter. With no trusted proxies configured (default),
    this is exactly ``request.client.host``.
    """
    peer = request.client.host if request.client else "unknown"
    if not trusted_proxies or not _is_trusted(peer, trusted_proxies):
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    # Walk hops right-to-left; the first one outside the trusted set is the real client.
    for hop in reversed([h.strip() for h in forwarded.split(",") if h.strip()]):
        if not _is_trusted(hop, trusted_proxies):
            return hop
    # Every listed hop is itself trusted (a chain of our own proxies) → fall back to the peer.
    return peer


def _to_core_request(body: VerifyHttpRequest) -> VerifyRequest:
    lenses: list[str] | Literal["auto"] = "auto"
    if body.lenses != "auto":
        lenses = [item.strip() for item in body.lenses.split(",")]
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType(body.artifact_type), content=body.artifact),
        intent=body.intent,
        caller=CallerContext(
            model_family=ModelFamily(body.caller_family), model_id=body.caller_model
        ),
        lenses=lenses,
        budget=Budget(max_latency_ms=body.max_latency_ms),
    )


def _fingerprint(body: VerifyHttpRequest) -> str:
    canonical = json.dumps(
        {
            "artifact": body.artifact,
            "intent": body.intent,
            "artifact_type": body.artifact_type,
            "caller_family": body.caller_family,
            "lenses": body.lenses,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_app(
    *,
    engine: VerificationEngine | None = None,
    store: ReceiptStore | None = None,
    authenticator: Authenticator | None = None,
    webhook_secret: bytes | None = None,
    webhook_sender: Sender | None = None,
    webhook_resolver: Resolver | None = None,
    max_artifact_bytes: int | None = None,
) -> FastAPI:
    """Build the prism FastAPI app. Dependencies are injectable for testing.

    Without injection: the receipt store + providers resolve from the environment (fail-closed —
    a missing signing key raises at construction, exactly like the CLI/MCP).
    """
    if store is None:
        store = ReceiptStore()
    if engine is None:
        register_default_lenses()
        engine = VerificationEngine(providers=build_providers_from_env(), receipt_store=store)
    if authenticator is None:
        authenticator = Authenticator(
            load_key_hashes(),
            allow_no_auth=os.environ.get("PRISM_HTTP_ALLOW_NO_AUTH") == "1",
        )
    if webhook_secret is None:
        configured = os.environ.get("PRISM_WEBHOOK_SECRET")
        webhook_secret = configured.encode() if configured else None
    max_bytes = max_artifact_bytes or int(
        os.environ.get("PRISM_MAX_ARTIFACT_BYTES", DEFAULT_MAX_ARTIFACT_BYTES)
    )
    # Opt-in trusted-proxy CIDRs (SURF-A-006). Default empty → X-Forwarded-For is never trusted, so
    # the per-IP failed-auth limiter keys on the real peer. Only when the direct peer is within one
    # of these CIDRs do we honor XFF (see _client_ip), preventing a shared-proxy IP from collapsing
    # every client into one bucket while never trusting attacker-supplied headers from a raw peer.
    trusted_proxies = _parse_trusted_proxies(os.environ.get("PRISM_TRUSTED_PROXIES"))

    # In-memory state (single-process v0.4): idempotency cache + async task set + dead-letter ring.
    # The cache is bounded + TTL'd (SURF-A-001); the dead-letter ring is bounded and every append
    # is logged (SURF-A-003) so async failures reach the operator log pipeline, not just memory.
    idempotency = IdempotencyCache()
    background: set[asyncio.Task[Any]] = set()
    dead_letter: list[dict[str, Any]] = []

    def record_dead_letter(entry: dict[str, Any]) -> None:
        """Log a structured ERROR and append to the bounded dead-letter ring (SURF-A-003).

        Every append emits an ERROR so failures reach the operator log pipeline rather than being
        silently buried in memory; the in-memory ring is capped at the most recent DEAD_LETTER_MAX.
        """
        logger.error("async delivery dead-lettered: %s", json.dumps(entry, default=str))
        dead_letter.append(entry)
        if len(dead_letter) > DEAD_LETTER_MAX:
            del dead_letter[:-DEAD_LETTER_MAX]

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # Await in-flight async deliveries, then close the store handle.
        for task in list(background):
            with suppress(Exception):
                await task
        store.close()

    app = FastAPI(
        title="prism-verify",
        version=__version__,
        description="Runtime adjudication for agent workflows — family-different, "
        "reasoning-stripped, multi-lens verification with signed replayable receipts.",
        lifespan=lifespan,
    )
    install_problem_handler(app)

    def _authn(request: Request) -> dict[str, str]:
        """Authenticate AND meter every protected endpoint (the shared dependency).

        Returns RateLimit headers to attach to the response; raises 401/429 on auth/limit failure.
        Folding auth→rate into one helper keeps the authenticated family ({/verify, /replay,
        /verify-receipt}) consistently metered — /healthz is the only intended unmetered route.
        """
        identity = authenticator.authenticate(
            request.headers.get("authorization"), _client_ip(request, trusted_proxies)
        )
        return authenticator.check_rate(identity)

    async def _deliver_async(body: VerifyHttpRequest, webhook_url: str) -> None:
        assert webhook_secret is not None  # checked before scheduling
        result = await engine.verify(_to_core_request(body))
        if isinstance(result, VerifyError):
            record_dead_letter({"reason": result.reason.value, "detail": result.detail})
            return
        row = store.get_receipt(result.receipt.id) or {}
        outcome = await deliver(
            webhook_url,
            event="verdict",
            receipt_id=result.receipt.id,
            secret=webhook_secret,
            body=verdict_body(_jsonable(row), result.verdict.value),
            sender=webhook_sender,
            resolver=webhook_resolver,
        )
        if not outcome.delivered:
            record_dead_letter(
                {
                    "receipt_id": result.receipt.id,
                    "detail": outcome.detail,
                    "status": outcome.status,
                }
            )

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "families": sorted(engine._providers.keys()),  # configured verifier families
            "dead_letters": len(dead_letter),  # async deliveries that failed (also logged at ERROR)
        }

    @app.post("/verify")
    async def verify(body: VerifyHttpRequest, request: Request) -> Response:
        rate_headers = _authn(request)

        if len(body.artifact.encode()) > max_bytes:
            raise ProblemError(
                413,
                "artifact-too-large",
                "Payload Too Large",
                f"Artifact exceeds the {max_bytes}-byte limit; reject before any provider call.",
            )

        idem_key = request.headers.get("idempotency-key")
        fingerprint = _fingerprint(body)
        if idem_key is not None:
            cached = idempotency.get(idem_key)
            if cached is not None:
                cached_fp, cached_payload, cached_status = cached
                if cached_fp != fingerprint:
                    raise ProblemError(
                        422,
                        "idempotency-conflict",
                        "Unprocessable Entity",
                        "Idempotency-Key reused with a different request body.",
                    )
                if cached_payload is None:
                    raise ProblemError(
                        409, "idempotency-in-flight", "Conflict", "Original request is in flight."
                    )
                return _json(cached_payload, rate_headers, status=cached_status)

        prefer_async = "respond-async" in request.headers.get("prefer", "").lower()
        if prefer_async:
            if not body.webhook:
                raise ProblemError(
                    400,
                    "async-requires-webhook",
                    "Bad Request",
                    "Prefer: respond-async requires a 'webhook' URL for delivery in v0.4 "
                    "(polling-based async is a v0.5 item).",
                )
            if webhook_secret is None:
                raise ProblemError(
                    400,
                    "webhook-not-configured",
                    "Bad Request",
                    "Server has no PRISM_WEBHOOK_SECRET configured to sign deliveries.",
                )
            try:
                assert_safe_url(body.webhook, resolver=webhook_resolver)  # fail fast on SSRF
            except WebhookError as exc:
                raise ProblemError(400, "unsafe-webhook", "Bad Request", str(exc)) from exc
            async_body = {"status": "accepted", "delivery": "webhook", "webhook": body.webhook}
            # Honor Idempotency-Key on the async path too: cache the 202 BEFORE scheduling so a
            # retry replays it (via the check above) instead of double-spending a paid verification
            # + double-delivering the webhook (a fresh receipt id would dodge consumer dedup).
            if idem_key is not None:
                idempotency.set(idem_key, fingerprint, async_body, 202)
            task = asyncio.create_task(_deliver_async(body, body.webhook))
            background.add(task)
            task.add_done_callback(background.discard)
            return _json(async_body, rate_headers, status=202)

        if idem_key is not None:
            idempotency.set(idem_key, fingerprint, None, 200)  # in-flight
        try:
            result = await engine.verify(_to_core_request(body))
        except Exception:
            # Any failure (incl. a non-VerifyError raise) must clear the in-flight marker, or the
            # key wedges permanently at 409 and every retry is refused.
            if idem_key is not None:
                idempotency.pop(idem_key)
            raise
        if isinstance(result, VerifyError):
            if idem_key is not None:
                idempotency.pop(idem_key)  # do not cache a refusal as a committed result
            return verify_error_response_with_headers(result, rate_headers)
        payload = _jsonable(result.model_dump())
        if idem_key is not None:
            idempotency.set(idem_key, fingerprint, payload, 200)
        return _json(payload, rate_headers)

    @app.get("/replay/{receipt_id}")
    async def replay(receipt_id: str, request: Request) -> Response:
        rate_headers = _authn(request)
        row = store.get_receipt(receipt_id)
        if row is None:
            raise ProblemError(
                404, "receipt-not-found", "Not Found", f"No receipt {receipt_id!r}."
            )
        return _json(_replay_payload(row, store), rate_headers)

    @app.post("/verify-receipt")
    async def verify_receipt(body: VerifyReceiptHttpRequest, request: Request) -> Response:
        rate_headers = _authn(request)
        if body.public_key is not None:
            valid = verify_receipt_dict(body.receipt, public_key_pem=body.public_key)
        else:
            valid = store.verify_receipt(body.receipt)
        return _json(
            {
                "receipt_id": body.receipt.get("id"),
                "alg": body.receipt.get("alg", "HMAC-SHA256"),
                "signature_valid": valid,
            },
            rate_headers,
        )

    return app


def verify_error_response_with_headers(err: VerifyError, headers: dict[str, str]) -> JSONResponse:
    from prism.http.errors import verify_error_response

    resp = verify_error_response(err)
    for key, value in headers.items():
        resp.headers[key] = value
    return resp


def _replay_payload(row: dict[str, Any], store: ReceiptStore) -> dict[str, Any]:
    payload = _jsonable(dict(row))
    payload["signature_valid"] = store.verify_receipt(row)
    return payload


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce a row/model dict to JSON-safe values (datetimes -> isoformat)."""
    coerced: dict[str, Any] = json.loads(json.dumps(data, default=str))
    return coerced


def _json(content: dict[str, Any], headers: dict[str, str], *, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=content, headers=headers)
