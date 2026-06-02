"""Tests for the signed-webhook escalate channel — signing, SSRF guard, delivery, cancel-event."""

from __future__ import annotations

import json

import pytest

from prism.http.webhook import (
    CANCEL_EVENT,
    WebhookError,
    assert_safe_url,
    cancel_body,
    deliver,
    send_cancel_event,
    sign_payload,
    verdict_body,
    verify_webhook,
    webhook_id,
)


def _public(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]  # example.com — a public address


async def _noop_sleep(_seconds: float) -> None:
    return None


class TestSigning:
    def test_sign_verify_roundtrip(self):
        sig = sign_payload(b"whsec", "msg_1", 1000, "payload")
        assert verify_webhook(b"whsec", "msg_1", 1000, "payload", sig, now=1000) is True

    def test_tampered_payload_fails(self):
        sig = sign_payload(b"whsec", "msg_1", 1000, "payload")
        assert verify_webhook(b"whsec", "msg_1", 1000, "TAMPERED", sig, now=1000) is False

    def test_future_skew_fails(self):
        sig = sign_payload(b"whsec", "msg_1", 1000, "p")
        assert verify_webhook(b"whsec", "msg_1", 1000, "p", sig, now=1000 + 400) is False

    def test_past_skew_replay_fails(self):
        # A delivery whose timestamp is far in the PAST (a replay of an old message) is rejected —
        # the tolerance is two-sided, not just future skew.
        sig = sign_payload(b"whsec", "msg_1", 1000, "p")
        assert verify_webhook(b"whsec", "msg_1", 1000, "p", sig, now=1000 - 400) is False

    def test_wrong_secret_fails(self):
        sig = sign_payload(b"a", "msg_1", 1000, "p")
        assert verify_webhook(b"b", "msg_1", 1000, "p", sig, now=1000) is False

    def test_multi_signature_supports_rotation(self):
        # The header may carry old+new sigs (space-delimited); either secret verifies.
        old = sign_payload(b"old", "m", 1000, "p")
        new = sign_payload(b"new", "m", 1000, "p")
        header = f"{old} {new}"
        assert verify_webhook(b"new", "m", 1000, "p", header, now=1000) is True
        assert verify_webhook(b"old", "m", 1000, "p", header, now=1000) is True

    def test_webhook_id_deterministic_and_event_distinct(self):
        assert webhook_id("prism-1", "verdict") == webhook_id("prism-1", "verdict")
        assert webhook_id("prism-1", "verdict") != webhook_id("prism-1", CANCEL_EVENT)


class TestSsrfGuard:
    def test_requires_https(self):
        with pytest.raises(WebhookError):
            assert_safe_url("http://example.com/h", resolver=_public)

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.0.0.5",
            "192.168.1.1",
            "172.16.0.1",
            "100.64.0.1",  # RFC 6598 carrier-grade NAT
            "169.254.169.254",
            "::1",
            "fd00::1",
            "fe80::1",
            # TEST-A-003: IPv4-mapped IPv6 — the ::ffff:0:0/96 range that smuggles an internal v4
            # address through a v6 literal. All three forms must be blocked (the metadata IP, a
            # loopback, and a private v4), incl. the compressed-hex spelling of 127.0.0.1.
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "::ffff:7f00:1",  # == ::ffff:127.0.0.1 in compressed-hex form
        ],
    )
    def test_blocks_internal_and_metadata(self, ip):
        with pytest.raises(WebhookError):
            assert_safe_url("https://evil.example/h", resolver=lambda _h, _p: [ip])

    def test_blocks_if_any_resolved_ip_is_internal(self):
        # Public + internal in the A-record set (a rebind / multi-answer trick) → blocked.
        with pytest.raises(WebhookError):
            assert_safe_url("https://x/h", resolver=lambda _h, _p: ["93.184.216.34", "127.0.0.1"])

    def test_allows_public(self):
        assert assert_safe_url("https://x/h", resolver=_public) == ["93.184.216.34"]

    def test_no_host_raises(self):
        with pytest.raises(WebhookError):
            assert_safe_url("https:///nohost", resolver=_public)


class TestDelivery:
    async def test_success_signs_payload(self):
        sent: list[tuple[str, dict[str, str], str]] = []

        async def sender(url: str, headers: dict[str, str], body: str) -> int:
            sent.append((url, headers, body))
            return 200

        res = await deliver(
            "https://x/h",
            event="verdict",
            receipt_id="prism-1",
            secret=b"s",
            body={"a": 1},
            sender=sender,
            resolver=_public,
            now=1000,
        )
        assert res.delivered is True
        assert res.attempts == 1
        _url, headers, body = sent[0]
        assert verify_webhook(
            b"s", headers["webhook-id"], 1000, body, headers["webhook-signature"], now=1000
        )

    async def test_4xx_fails_fast_no_retry(self):
        async def sender(*_a: object) -> int:
            return 404

        res = await deliver(
            "https://x/h",
            event="verdict",
            receipt_id="r",
            secret=b"s",
            body={},
            sender=sender,
            resolver=_public,
            retry_delays=(0.0, 0.0),
            sleep=_noop_sleep,
        )
        assert res.delivered is False
        assert res.attempts == 1  # a permanent 4xx is not retried

    async def test_5xx_retries_then_exhausts_and_dead_letters(self):
        async def sender(*_a: object) -> int:
            return 503

        slept: list[float] = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)

        res = await deliver(
            "https://x/h",
            event="verdict",
            receipt_id="r",
            secret=b"s",
            body={},
            sender=sender,
            resolver=_public,
            retry_delays=(0.1, 0.2),
            sleep=sleep,
        )
        assert res.delivered is False
        assert res.attempts == 3  # initial + 2 retries
        assert slept == [0.1, 0.2]

    async def test_transport_error_is_retried(self):
        calls = {"n": 0}

        async def sender(*_a: object) -> int:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("connection reset")
            return 200

        res = await deliver(
            "https://x/h",
            event="verdict",
            receipt_id="r",
            secret=b"s",
            body={},
            sender=sender,
            resolver=_public,
            retry_delays=(0.0,),
            sleep=_noop_sleep,
        )
        assert res.delivered is True
        assert res.attempts == 2

    async def test_delivery_pins_to_the_validated_ip(self):
        # Closes the resolve-vs-connect TOCTOU: the sender connects to the validated IP (not the
        # hostname), with the original hostname carried in the Host header for TLS SNI/verification.
        captured: dict[str, object] = {}

        async def sender(url: str, headers: dict[str, str], body: str) -> int:
            captured["url"] = url
            captured["host"] = headers.get("host")
            return 200

        await deliver(
            "https://hooks.example/x",
            event="verdict",
            receipt_id="r",
            secret=b"s",
            body={},
            sender=sender,
            resolver=lambda _h, _p: ["93.184.216.34"],
            now=1000,
        )
        assert "93.184.216.34" in str(captured["url"])
        assert "hooks.example" not in str(captured["url"])  # pinned to the IP, not re-resolvable
        assert captured["host"] == "hooks.example"

    async def test_ssrf_blocks_before_any_send(self):
        async def sender(*_a: object) -> int:
            raise AssertionError("must not send to a blocked address")

        with pytest.raises(WebhookError):
            await deliver(
                "https://x/h",
                event="verdict",
                receipt_id="r",
                secret=b"s",
                body={},
                sender=sender,
                resolver=lambda _h, _p: ["10.0.0.1"],
            )

    def test_cancel_body_is_the_compensator_shape(self):
        body = cancel_body("prism-1", "superseded")
        assert body["event"] == CANCEL_EVENT
        assert body["receipt_id"] == "prism-1"

    async def test_send_cancel_event_delivers_signed_compensator(self):
        sent: list[tuple[str, dict[str, str], str]] = []

        async def sender(url: str, headers: dict[str, str], body: str) -> int:
            sent.append((url, headers, body))
            return 200

        res = await send_cancel_event(
            "https://x/h",
            receipt_id="prism-1",
            secret=b"s",
            reason="superseded by re-verify",
            sender=sender,
            resolver=_public,
            now=1000,
        )
        assert res.delivered is True
        _url, headers, body = sent[0]
        # The compensator is signed like any delivery; the consumer can verify it.
        assert verify_webhook(
            b"s", headers["webhook-id"], 1000, body, headers["webhook-signature"], now=1000
        )
        assert json.loads(body)["event"] == CANCEL_EVENT

    def test_verdict_body_carries_receipt(self):
        body = verdict_body({"id": "prism-1"}, "escalate")
        assert body["event"] == "verdict"
        assert body["verdict"] == "escalate"
        assert body["receipt"]["id"] == "prism-1"
