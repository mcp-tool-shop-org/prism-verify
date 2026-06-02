"""Integration tests for the prism HTTP surface (FastAPI TestClient + a fake engine)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from prism.core.types import (
    ReasoningVisibility,
    RefusalReason,
    Verdict,
    VerifyError,
    VerifyResponse,
)
from prism.http.app import create_app
from prism.http.auth import Authenticator, generate_api_key
from prism.http.webhook import verify_webhook
from prism.receipts.store import ReceiptStore

VERIFY_BODY = {"artifact": "x = 1", "intent": "assign one", "caller_family": "anthropic"}


class FakeEngine:
    """Returns a configured verdict (creating a real signed receipt) or a VerifyError."""

    def __init__(
        self, store: ReceiptStore, verdict: str = "accept", error: VerifyError | None = None
    ):
        self._store = store
        self._providers = {"local": object()}
        self.verdict = verdict
        self.error = error

    async def verify(self, _request: Any) -> VerifyResponse | VerifyError:
        if self.error is not None:
            return self.error
        receipt = self._store.create_receipt(
            pre_strip_hash="a",
            post_strip_hash="b",
            verifier_models=["m"],
            pairwise_rho={},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict=self.verdict,
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
        )
        return VerifyResponse(
            verdict=Verdict(self.verdict),
            confidence=0.9,
            retryable=False,
            lens_results=[],
            pairwise_rho={},
            receipt=receipt,
        )


@pytest.fixture
def store(tmp_path):
    s = ReceiptStore(db_path=tmp_path / "http.db", signing_secret=b"http-secret")
    yield s
    s.close()


def make_app(store: ReceiptStore, **kwargs: Any):
    verdict = kwargs.pop("verdict", "accept")
    error = kwargs.pop("error", None)
    kwargs.setdefault("authenticator", Authenticator(set(), allow_no_auth=True))
    return create_app(engine=FakeEngine(store, verdict=verdict, error=error), store=store, **kwargs)


class TestBasics:
    def test_healthz_is_open_and_reports_families(self, store):
        client = TestClient(make_app(store))
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "local" in body["families"]

    def test_verify_accept_returns_receipt_and_ratelimit(self, store):
        client = TestClient(make_app(store))
        resp = client.post("/verify", json=VERIFY_BODY)
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "accept"
        assert body["receipt"]["alg"] == "HMAC-SHA256"
        assert "RateLimit" in resp.headers

    def test_openapi_documents_verify(self, store):
        client = TestClient(make_app(store))
        spec = client.get("/openapi.json").json()
        assert "/verify" in spec["paths"]
        assert "/verify-receipt" in spec["paths"]


class TestAuth:
    def test_fail_closed_when_no_keys_configured(self, store):
        app = make_app(store, authenticator=Authenticator(set(), allow_no_auth=False))
        resp = TestClient(app).post("/verify", json=VERIFY_BODY)
        assert resp.status_code == 401
        assert resp.headers["content-type"].startswith("application/problem+json")

    def test_api_key_required_and_accepted(self, store):
        key, key_hash = generate_api_key()
        client = TestClient(make_app(store, authenticator=Authenticator({key_hash})))
        assert client.post("/verify", json=VERIFY_BODY).status_code == 401
        ok = client.post("/verify", json=VERIFY_BODY, headers={"Authorization": f"Bearer {key}"})
        assert ok.status_code == 200

    def test_failed_auth_is_rate_limited_separately(self, store):
        _key, key_hash = generate_api_key()
        auth = Authenticator({key_hash}, failed_auth_per_minute=2)
        client = TestClient(make_app(store, authenticator=auth))
        bad = {"Authorization": "Bearer prism_wrong"}
        assert client.post("/verify", json=VERIFY_BODY, headers=bad).status_code == 401
        assert client.post("/verify", json=VERIFY_BODY, headers=bad).status_code == 401
        # third failure trips the stricter failed-auth limiter
        assert client.post("/verify", json=VERIFY_BODY, headers=bad).status_code == 429

    def test_replay_and_verify_receipt_also_fail_closed(self, store):
        # The whole authenticated family fails closed, not just /verify.
        app = make_app(store, authenticator=Authenticator(set(), allow_no_auth=False))
        client = TestClient(app)
        assert client.get("/replay/prism-x").status_code == 401
        assert client.post("/verify-receipt", json={"receipt": {}}).status_code == 401


class TestBackPressure:
    def test_artifact_too_large(self, store):
        app = create_app(
            engine=FakeEngine(store),
            store=store,
            authenticator=Authenticator(set(), allow_no_auth=True),
            max_artifact_bytes=8,
        )
        resp = TestClient(app).post(
            "/verify", json={"artifact": "x" * 50, "intent": "y", "caller_family": "local"}
        )
        assert resp.status_code == 413

    def test_rate_limit_429(self, store):
        auth = Authenticator(set(), allow_no_auth=True, requests_per_minute=2)
        client = TestClient(make_app(store, authenticator=auth))
        assert client.post("/verify", json=VERIFY_BODY).status_code == 200
        assert client.post("/verify", json=VERIFY_BODY).status_code == 200
        limited = client.post("/verify", json=VERIFY_BODY)
        assert limited.status_code == 429
        assert "Retry-After" in limited.headers

    def test_all_authenticated_endpoints_share_the_limiter(self, store):
        # rpm=1: the single token is consumed by the first authenticated call; the next call on
        # ANY authenticated endpoint is 429 — proving /replay and /verify-receipt meter too (the
        # family-of-call-sites consistency). The rate check runs before the receipt lookup, so an
        # exhausted /replay is 429 (not 404). /healthz is the only intended unmetered route.
        auth = Authenticator(set(), allow_no_auth=True, requests_per_minute=1)
        client = TestClient(make_app(store, authenticator=auth))
        assert client.post("/verify", json=VERIFY_BODY).status_code == 200
        assert client.get("/replay/prism-anything").status_code == 429
        assert client.post("/verify-receipt", json={"receipt": {"id": "x"}}).status_code == 429
        assert client.get("/healthz").status_code == 200  # unmetered, still ok


class TestErrors:
    def test_verify_error_is_problem_json(self, store):
        err = VerifyError(
            reason=RefusalReason.VERIFIER_UNAVAILABLE, detail="all routes open", retryable=True
        )
        client = TestClient(make_app(store, error=err))
        resp = client.post("/verify", json=VERIFY_BODY)
        assert resp.status_code == 503
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["code"] == "VERIFIER_UNAVAILABLE"
        assert body["type"].endswith("verifier-unavailable")
        assert resp.headers.get("Retry-After") == "2"

    def test_invalid_artifact_maps_to_422(self, store):
        err = VerifyError(reason=RefusalReason.INVALID_ARTIFACT, detail="bad json", retryable=False)
        client = TestClient(make_app(store, error=err))
        assert client.post("/verify", json=VERIFY_BODY).status_code == 422


class TestIdempotency:
    def test_same_key_and_body_replays_not_reruns(self, store):
        client = TestClient(make_app(store))
        headers = {"Idempotency-Key": "abc"}
        first = client.post("/verify", json=VERIFY_BODY, headers=headers)
        second = client.post("/verify", json=VERIFY_BODY, headers=headers)
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["receipt"]["id"] == second.json()["receipt"]["id"]

    def test_same_key_different_body_conflicts(self, store):
        client = TestClient(make_app(store))
        headers = {"Idempotency-Key": "abc"}
        client.post("/verify", json=VERIFY_BODY, headers=headers)
        other = {**VERIFY_BODY, "artifact": "different"}
        resp = client.post("/verify", json=other, headers=headers)
        assert resp.status_code == 422
        assert resp.json()["type"].endswith("idempotency-conflict")


class TestReplayAndVerifyReceipt:
    def test_replay_returns_signed_receipt(self, store):
        client = TestClient(make_app(store))
        receipt_id = client.post("/verify", json=VERIFY_BODY).json()["receipt"]["id"]
        resp = client.get(f"/replay/{receipt_id}")
        assert resp.status_code == 200
        assert resp.json()["signature_valid"] is True

    def test_replay_missing_is_404_problem(self, store):
        client = TestClient(make_app(store))
        resp = client.get("/replay/prism-nope")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")

    def test_verify_receipt_endpoint(self, store):
        client = TestClient(make_app(store))
        receipt_id = client.post("/verify", json=VERIFY_BODY).json()["receipt"]["id"]
        row = json.loads(json.dumps(store.get_receipt(receipt_id), default=str))
        resp = client.post("/verify-receipt", json={"receipt": row})
        assert resp.status_code == 200
        assert resp.json()["signature_valid"] is True


class TestAsync:
    def test_async_requires_webhook(self, store):
        client = TestClient(make_app(store, webhook_secret=b"wh"))
        resp = client.post("/verify", json=VERIFY_BODY, headers={"Prefer": "respond-async"})
        assert resp.status_code == 400
        assert resp.json()["type"].endswith("async-requires-webhook")

    def test_async_rejects_unsafe_webhook(self, store):
        # SSRF guard rejects an internal webhook target at accept-time.
        app = make_app(
            store, webhook_secret=b"wh", webhook_resolver=lambda _h, _p: ["127.0.0.1"]
        )
        client = TestClient(app)
        resp = client.post(
            "/verify",
            json={**VERIFY_BODY, "webhook": "https://evil.example/hook"},
            headers={"Prefer": "respond-async"},
        )
        assert resp.status_code == 400  # blocked address → SSRF problem

    def test_async_delivers_signed_verdict_to_webhook(self, store):
        delivered: list[tuple[str, dict[str, str], str]] = []

        async def sender(url: str, headers: dict[str, str], body: str) -> int:
            delivered.append((url, headers, body))
            return 200

        app = make_app(
            store,
            verdict="escalate",
            webhook_secret=b"wh",
            webhook_sender=sender,
            webhook_resolver=lambda _h, _p: ["93.184.216.34"],
        )
        # Context-manager TestClient runs lifespan; shutdown drains the async delivery task.
        with TestClient(app) as client:
            resp = client.post(
                "/verify",
                json={**VERIFY_BODY, "webhook": "https://hooks.example/x"},
                headers={"Prefer": "respond-async"},
            )
            assert resp.status_code == 202
            assert resp.json()["delivery"] == "webhook"

        assert len(delivered) == 1
        _url, headers, body = delivered[0]
        ts = int(headers["webhook-timestamp"])
        assert verify_webhook(
            b"wh", headers["webhook-id"], ts, body, headers["webhook-signature"], now=ts
        )
        assert json.loads(body)["verdict"] == "escalate"

    def test_async_idempotency_key_prevents_duplicate_delivery(self, store):
        # Two identical async requests with the same Idempotency-Key must schedule ONE verification
        # + ONE webhook delivery — a retry replays the 202, never double-spends a paid run.
        calls: list[str] = []

        async def sender(url: str, headers: dict[str, str], body: str) -> int:
            calls.append(url)
            return 200

        app = make_app(
            store,
            verdict="escalate",
            webhook_secret=b"wh",
            webhook_sender=sender,
            webhook_resolver=lambda _h, _p: ["93.184.216.34"],
        )
        headers = {"Prefer": "respond-async", "Idempotency-Key": "dup-1"}
        body = {**VERIFY_BODY, "webhook": "https://hooks.example/x"}
        with TestClient(app) as client:
            r1 = client.post("/verify", json=body, headers=headers)
            r2 = client.post("/verify", json=body, headers=headers)
            assert r1.status_code == 202 and r2.status_code == 202
        assert len(calls) == 1


class TestFailureModes:
    def test_idempotency_key_not_wedged_when_verify_raises(self, store):
        # A non-VerifyError raise must clear the in-flight marker, or the key wedges at 409 forever.
        class BoomEngine:
            _providers = {"local": object()}

            async def verify(self, _req: Any) -> Any:
                raise RuntimeError("boom")

        app = create_app(
            engine=BoomEngine(), store=store, authenticator=Authenticator(set(), allow_no_auth=True)
        )
        client = TestClient(app, raise_server_exceptions=False)
        headers = {"Idempotency-Key": "k-raise"}
        assert client.post("/verify", json=VERIFY_BODY, headers=headers).status_code == 500
        # A retry reaches the engine again (500), not a wedged 409.
        assert client.post("/verify", json=VERIFY_BODY, headers=headers).status_code == 500

    def test_verify_receipt_malformed_is_not_500(self, store):
        # A malformed caller-supplied receipt must not 500 (that would escape the problem+json
        # contract) — it's simply not validly signed.
        client = TestClient(make_app(store))
        resp = client.post("/verify-receipt", json={"receipt": {"id": "x", "nope": True}})
        assert resp.status_code == 200
        assert resp.json()["signature_valid"] is False


class TestIdempotencyCacheBound:
    """SURF-A-001: the idempotency cache is LRU-capped AND TTL'd — it cannot grow unbounded."""

    def test_lru_overflow_evicts_oldest(self):
        from prism.http.app import IdempotencyCache

        cache = IdempotencyCache(max_entries=3, ttl_s=1000.0)
        for i in range(10):  # drive 10 distinct keys past the cap of 3
            cache.set(f"k{i}", f"fp{i}", {"i": i}, 200)
        # The structure stays bounded at the documented cap, oldest entries evicted.
        assert len(cache._store) == 3
        assert cache.get("k0") is None and cache.get("k6") is None  # evicted
        assert cache.get("k9") is not None  # newest retained
        assert cache.get("k7") is not None and cache.get("k8") is not None

    def test_expired_entries_evicted_on_insert(self):
        from prism.http.app import IdempotencyCache

        clock = {"t": 0.0}
        cache = IdempotencyCache(max_entries=1000, ttl_s=600.0, clock=lambda: clock["t"])
        cache.set("old", "fp", {"v": 1}, 200)
        clock["t"] = 700.0  # advance past the TTL
        assert cache.get("old") is None  # expired on read
        cache.set("new", "fp2", {"v": 2}, 200)  # an insert opportunistically sweeps expired
        assert "old" not in cache._store
        assert len(cache._store) == 1


class TestTrustedProxy:
    """SURF-A-006: X-Forwarded-For is honored ONLY behind a configured trusted proxy."""

    class _FakeClient:
        def __init__(self, host: str) -> None:
            self.host = host

    class _FakeRequest:
        def __init__(self, peer: str, xff: str | None) -> None:
            self.client = TestTrustedProxy._FakeClient(peer)
            self.headers = {"x-forwarded-for": xff} if xff is not None else {}

    def test_no_trusted_proxies_uses_peer_ignores_xff(self):
        # Default (empty PRISM_TRUSTED_PROXIES) → behavior unchanged: the peer IP is authoritative
        # and a (spoofable) X-Forwarded-For from a raw peer is ignored.
        from prism.http.app import _client_ip, _parse_trusted_proxies

        trusted = _parse_trusted_proxies(None)
        assert trusted == []
        req = self._FakeRequest(peer="203.0.113.7", xff="1.2.3.4")
        assert _client_ip(req, trusted) == "203.0.113.7"

    def test_xff_honored_behind_trusted_proxy(self):
        # Peer is within the trusted CIDR → read XFF and return the right-most UNtrusted hop.
        from prism.http.app import _client_ip, _parse_trusted_proxies

        trusted = _parse_trusted_proxies("10.0.0.0/8")
        req = self._FakeRequest(peer="10.0.0.5", xff="9.9.9.9, 10.0.0.9")
        # Right-most hop (10.0.0.9) is itself trusted; the real client is the next out (9.9.9.9).
        assert _client_ip(req, trusted) == "9.9.9.9"

    def test_xff_from_untrusted_peer_is_ignored(self):
        # The direct peer is NOT in the trusted set → XFF is ignored entirely (anti-spoof), so the
        # per-IP failed-auth limiter keys on the real peer, not an attacker-rotated header.
        from prism.http.app import _client_ip, _parse_trusted_proxies

        trusted = _parse_trusted_proxies("10.0.0.0/8")
        req = self._FakeRequest(peer="203.0.113.7", xff="9.9.9.9")
        assert _client_ip(req, trusted) == "203.0.113.7"


class TestDeadLetterLogging:
    """SURF-A-003: a failed async delivery is LOGGED (not silently buried in memory)."""

    def test_failed_async_verify_is_dead_lettered_and_logged(self, store, caplog):
        import logging

        # The async path runs engine.verify(); a VerifyError there must be dead-lettered with a
        # structured ERROR log AND counted in /healthz — never swallowed.
        err = VerifyError(
            reason=RefusalReason.VERIFIER_UNAVAILABLE, detail="all routes open", retryable=True
        )
        app = make_app(
            store,
            error=err,
            webhook_secret=b"wh",
            webhook_resolver=lambda _h, _p: ["93.184.216.34"],
        )
        with caplog.at_level(logging.ERROR, logger="prism.http"):
            with TestClient(app) as client:  # context-manager drains the async task on shutdown
                resp = client.post(
                    "/verify",
                    json={**VERIFY_BODY, "webhook": "https://hooks.example/x"},
                    headers={"Prefer": "respond-async"},
                )
                assert resp.status_code == 202
            # After lifespan shutdown the in-flight delivery has run and dead-lettered.
            health = TestClient(make_app(store)).get("/healthz").json()  # fresh app: own counter
        # The original app logged an ERROR for the dead-letter (assert via caplog, not memory).
        assert any(
            rec.levelno == logging.ERROR and "dead-lettered" in rec.getMessage()
            for rec in caplog.records
        )
        assert "VERIFIER_UNAVAILABLE" in caplog.text
        # Sanity: a clean /healthz still reports a numeric dead_letters counter.
        assert isinstance(health["dead_letters"], int)
