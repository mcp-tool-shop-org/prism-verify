"""Signed-webhook escalate channel (v0.4): Standard-Webhooks HMAC, SSRF guard, cancel-event.

For async / ``escalate`` verdicts that exceed the sync budget, prism POSTs the signed verdict to a
caller-registered endpoint. The signature binds ``id.timestamp.payload`` (Stripe / Standard
Webhooks) so a delivery cannot be replayed; the consumer verifies with a shared webhook secret and
dedups on the stable ``webhook-id``. The **cancel-event** is the NAMED COMPENSATOR for the
(irreversible) send — a new forward POST that semantically withdraws a verdict (Sagas,
Garcia-Molina & Salem 1987). See ``design/05`` §C and ``design/03``.

SSRF (the URL is caller-controlled): require https, resolve the host, reject any resolved IP in
loopback / private / link-local / metadata ranges (v4 + v6), and connect with redirects disabled.
The residual same-instant DNS-rebinding TOCTOU is the named v0.5 hardening (a pinned-IP transport).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

CANCEL_EVENT = "verdict_cancelled"
VERDICT_EVENT = "verdict"
_DEFAULT_RETRY_DELAYS: tuple[float, ...] = (0.5, 2.0, 5.0)


class WebhookError(RuntimeError):
    """A webhook URL is unsafe (SSRF) or otherwise undeliverable by contract."""


# --- Signing (Standard Webhooks: HMAC-SHA256 over "id.timestamp.payload") ---


def sign_payload(secret: bytes, msg_id: str, timestamp: int, payload: str) -> str:
    """Return a ``v1,<base64>`` signature over ``{msg_id}.{timestamp}.{payload}``."""
    signed = f"{msg_id}.{timestamp}.{payload}".encode()
    mac = hmac.new(secret, signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def verify_webhook(
    secret: bytes,
    msg_id: str,
    timestamp: int,
    payload: str,
    signature_header: str,
    *,
    tolerance_s: int = 300,
    now: int | None = None,
) -> bool:
    """Consumer-side verification: timestamp within tolerance + a matching (multi-)signature.

    The header may carry several space-delimited signatures (key rotation); any match passes.
    """
    current = now if now is not None else int(time.time())
    if abs(current - timestamp) > tolerance_s:
        return False
    expected = sign_payload(secret, msg_id, timestamp, payload)
    return any(hmac.compare_digest(candidate, expected) for candidate in signature_header.split())


def webhook_id(receipt_id: str, event: str) -> str:
    """A stable, deterministic delivery id so a retry reuses it (consumer idempotency key).

    The cancel-event shares the receipt_id but is a DISTINCT delivery, so the event is mixed in.
    """
    digest = hashlib.sha256(f"{receipt_id}.{event}".encode()).hexdigest()[:24]
    return f"msg_{digest}"


# --- SSRF guard ---

_EXTRA_BLOCKED = [
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 carrier-grade NAT
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    # Cloud metadata (also link-local, but call it out explicitly as belt-and-suspenders).
    if str(ip) == "169.254.169.254":
        return True
    return any(ip in net for net in _EXTRA_BLOCKED)


# Injectable resolver so the SSRF guard is unit-testable without real DNS.
Resolver = Callable[[str, int], Sequence[str]]


def _default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebhookError(f"cannot resolve webhook host {host!r}: {exc}") from exc
    return [str(info[4][0]) for info in infos]


def assert_safe_url(url: str, *, resolver: Resolver | None = None) -> list[str]:
    """Validate a caller-supplied webhook URL against SSRF; return the resolved (safe) IPs.

    Raises ``WebhookError`` on a non-https scheme, an unresolvable host, or ANY resolved address in
    a loopback / private / link-local / metadata range (IPv4 and IPv6).
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise WebhookError("webhook URL must use https")
    host = parsed.hostname
    if not host:
        raise WebhookError("webhook URL has no host")
    resolve = resolver or _default_resolver
    addresses = list(resolve(host, parsed.port or 443))
    if not addresses:
        raise WebhookError(f"webhook host {host!r} did not resolve")
    safe: list[str] = []
    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if _is_blocked_ip(ip):
            raise WebhookError(f"webhook host resolves to a blocked address: {ip}")
        safe.append(str(ip))
    return safe


# --- Delivery ---


@dataclass
class DeliveryResult:
    delivered: bool
    attempts: int
    status: int | None
    detail: str


# A sender abstracts the POST so tests inject a fake (the SSRF guard is tested separately).
Sender = Callable[[str, dict[str, str], str], Awaitable[int]]


async def _httpx_sender(url: str, headers: dict[str, str], body: str) -> int:
    # follow_redirects=False: a 3xx to an internal host must not be auto-followed past the guard.
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        resp = await client.post(url, headers=headers, content=body.encode())
        return resp.status_code


def build_delivery(
    *,
    event: str,
    receipt_id: str,
    secret: bytes,
    body: dict[str, Any],
    timestamp: int,
) -> tuple[str, dict[str, str], str]:
    """Build the (msg_id, headers, payload) for a signed webhook delivery."""
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    msg_id = webhook_id(receipt_id, event)
    signature = sign_payload(secret, msg_id, timestamp, payload)
    headers = {
        "content-type": "application/json",
        "webhook-id": msg_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": signature,
    }
    return msg_id, headers, payload


async def deliver(
    url: str,
    *,
    event: str,
    receipt_id: str,
    secret: bytes,
    body: dict[str, Any],
    sender: Sender | None = None,
    resolver: Resolver | None = None,
    retry_delays: Sequence[float] = _DEFAULT_RETRY_DELAYS,
    now: int | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> DeliveryResult:
    """Sign + POST a verdict (or cancel-event) to a caller endpoint with bounded retry.

    The SSRF guard runs first (raises before any network touch). 2xx is success; a 4xx fails fast
    (a permanent client error — no retry); timeouts / 5xx retry with the bounded ``retry_delays``.
    On exhaustion the caller dead-letters (this returns ``delivered=False``). ``sender`` /
    ``resolver`` / ``retry_delays`` / ``now`` / ``sleep`` are injectable for tests.
    """
    assert_safe_url(url, resolver=resolver)
    send = sender or _httpx_sender
    do_sleep = sleep or asyncio.sleep
    ts = now if now is not None else int(time.time())
    _msg_id, headers, payload = build_delivery(
        event=event, receipt_id=receipt_id, secret=secret, body=body, timestamp=ts
    )

    attempts = 0
    last_status: int | None = None
    last_detail = ""
    # one initial attempt + one per retry delay
    for attempt_index in range(len(retry_delays) + 1):
        attempts += 1
        try:
            status = await send(url, headers, payload)
        except Exception as exc:  # network/transport error — retry
            last_status, last_detail = None, f"transport error: {exc}"
        else:
            last_status = status
            if 200 <= status < 300:
                return DeliveryResult(True, attempts, status, "delivered")
            if 400 <= status < 500:
                return DeliveryResult(False, attempts, status, f"permanent {status}, not retried")
            last_detail = f"transient {status}"
        if attempt_index < len(retry_delays):
            await do_sleep(retry_delays[attempt_index])
    return DeliveryResult(False, attempts, last_status, f"exhausted retries: {last_detail}")


def verdict_body(receipt: dict[str, Any], verdict: str) -> dict[str, Any]:
    """The webhook payload for an async verdict delivery."""
    return {
        "event": VERDICT_EVENT,
        "receipt_id": receipt.get("id"),
        "verdict": verdict,
        "receipt": receipt,
    }


def cancel_body(receipt_id: str, reason: str) -> dict[str, Any]:
    """The cancel-event compensator payload — semantically withdraws a previously sent verdict."""
    return {"event": CANCEL_EVENT, "receipt_id": receipt_id, "reason": reason}


async def send_cancel_event(
    url: str,
    *,
    receipt_id: str,
    secret: bytes,
    reason: str,
    sender: Sender | None = None,
    resolver: Resolver | None = None,
    retry_delays: Sequence[float] = _DEFAULT_RETRY_DELAYS,
    now: int | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> DeliveryResult:
    """The NAMED COMPENSATOR for a webhook verdict send (design/03).

    You cannot un-send the verdict POST, so the compensator is a NEW forward POST of a signed
    ``verdict_cancelled`` event (Sagas, Garcia-Molina & Salem 1987) — same signing + SSRF guard +
    bounded-retry machinery, a distinct ``webhook-id``. The consumer treats it as "disregard the
    prior verdict"; any residual caller action is the accepted approximation.
    """
    return await deliver(
        url,
        event=CANCEL_EVENT,
        receipt_id=receipt_id,
        secret=secret,
        body=cancel_body(receipt_id, reason),
        sender=sender,
        resolver=resolver,
        retry_delays=retry_delays,
        now=now,
        sleep=sleep,
    )
