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
