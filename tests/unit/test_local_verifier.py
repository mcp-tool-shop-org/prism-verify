"""Unit tests for the LocalVerifierProvider — the Verifier specialist as prism's citation backend.

Covers the bridge logic and, critically, the SILENT-ESCALATE guard: a real verdict must round-trip
through prism's OWN parse_citation_groundedness to the correct outcome (never the safe-default
'not_addressed'), and any failure must RAISE ProviderError (loud circuit-breaker failover), not
return a quiet escalate.
"""

import asyncio
import json

import httpx
import pytest

from prism.core.citations import (
    _VALID_MATCHES,
    build_citation_groundedness_prompts,
    parse_citation_groundedness,
)
from prism.core.routing import DEFAULT_ROUTING_MAP, with_local_verifier
from prism.core.setup import build_default_engine
from prism.core.types import ModelFamily
from prism.providers.base import CompletionRequest, ProviderError
from prism.providers.local_verifier import (
    VERDICT_MAP,
    LocalVerifierProvider,
    parse_verdict,
    retemplate,
)


class _FakeResp:
    def __init__(self, content: str, status: int = 200) -> None:
        self._content, self.status_code = content, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "http", request=httpx.Request("POST", "http://x"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": self._content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }


class _FakeClient:
    def __init__(self, content: str | None = None, raise_exc: Exception | None = None) -> None:
        self._content, self._raise = content, raise_exc

    async def post(self, url, json=None):  # noqa: A002
        if self._raise:
            raise self._raise
        return _FakeResp(self._content or "")

    async def get(self, url):
        return _FakeResp("ok")


def _provider(content=None, raise_exc=None) -> LocalVerifierProvider:
    p = LocalVerifierProvider("http://verifier.local")
    p._client = _FakeClient(content=content, raise_exc=raise_exc)
    return p


def test_retemplate_extracts_source_and_claim():
    _sys, user = build_citation_groundedness_prompts(
        "Vaccine X cut hospitalizations by 40%.",
        "Trial of Vaccine X",
        "A randomized trial; hospitalizations fell 40% in the treated arm.",
    )
    out = retemplate(user)
    assert out.startswith("EVIDENCE:\n")
    assert "Trial of Vaccine X" in out and "hospitalizations fell 40%" in out
    assert "CLAIM:\nVaccine X cut hospitalizations by 40%." in out
    assert "<<<" not in out  # markers stripped


def test_parse_verdict_order_and_none():
    assert parse_verdict("<think>x</think>\n\nunsupported") == "unsupported"  # not 'supported'
    assert parse_verdict("blah\nsupported") == "supported"
    assert parse_verdict("<think>y</think>\n\nabstain") == "abstain"
    assert parse_verdict("<think>reasoning, no verdict word</think>\n\n") is None
    assert parse_verdict("garbage") is None


def test_verdict_map_is_prism_vocab():
    assert set(VERDICT_MAP.values()) <= _VALID_MATCHES
    assert VERDICT_MAP == {
        "supported": "supported",
        "unsupported": "contradicted",
        "abstain": "not_addressed",
    }


@pytest.mark.parametrize(
    "model_out,expected",
    [
        ("<think>every part traces</think>\n\nsupported", "supported"),
        ("<think>the number is swapped</think>\n\nunsupported", "contradicted"),
        ("<think>evidence is silent</think>\n\nabstain", "not_addressed"),
    ],
)
def test_roundtrip_through_prism_parser(model_out, expected):
    # THE silent-escalate guard: a real verdict round-trips to the right prism outcome via prism's
    # parse_citation_groundedness — NOT the safe-default ('not_addressed', None, 0.0).
    _sys, user = build_citation_groundedness_prompts("c", "t", "a")
    p = _provider(content=model_out)
    resp = asyncio.run(
        p.complete(CompletionRequest(system_prompt=_sys, user_prompt=user, model_id="m"))
    )
    outcome, _span, conf = parse_citation_groundedness(resp.content)
    assert outcome == expected
    assert conf > 0.0  # not the garbage default


def test_supported_does_not_silently_escalate():
    # explicit regression for the #1 risk: a 'supported' must NOT degrade to 'not_addressed'
    _sys, user = build_citation_groundedness_prompts("c", "t", "a")
    p = _provider(content="<think>ok</think>\n\nsupported")
    resp = asyncio.run(
        p.complete(CompletionRequest(system_prompt=_sys, user_prompt=user, model_id="m"))
    )
    assert json.loads(resp.content)["outcome"] == "supported"
    assert parse_citation_groundedness(resp.content)[0] == "supported"


def test_http_error_raises_provider_error():
    p = _provider(raise_exc=httpx.ConnectError("down"))
    with pytest.raises(ProviderError):
        asyncio.run(p.complete(CompletionRequest(system_prompt="s", user_prompt="u", model_id="m")))


def test_no_verdict_raises_provider_error():
    # a no-verdict reply must RAISE (-> circuit-breaker failover), not silently escalate
    p = _provider(content="<think>still unsure, no verdict</think>\n\n")
    with pytest.raises(ProviderError):
        asyncio.run(p.complete(CompletionRequest(system_prompt="s", user_prompt="u", model_id="m")))


def test_family_is_local_verifier():
    assert _provider().family == ModelFamily.LOCAL_VERIFIER


def test_with_local_verifier_prepends_and_leaves_default_untouched():
    m = with_local_verifier(DEFAULT_ROUTING_MAP, "qwen3-14b-groundedness")
    for caller, verifiers in m.items():
        if caller == ModelFamily.LOCAL_VERIFIER:
            # Lock 1: a family never verifies itself
            assert all(f != ModelFamily.LOCAL_VERIFIER for f, _ in verifiers)
        else:
            assert verifiers[0] == (ModelFamily.LOCAL_VERIFIER, "qwen3-14b-groundedness")
    # the shipped static map is NOT mutated
    assert DEFAULT_ROUTING_MAP[ModelFamily.ANTHROPIC][0][0] == ModelFamily.GOOGLE


def test_build_default_engine_injects_verifier_only_when_configured(monkeypatch):
    monkeypatch.setenv("PRISM_DEV", "1")  # engine construction needs a receipt-signing config
    monkeypatch.delenv("PRISM_LOCAL_VERIFIER_ENDPOINT", raising=False)
    eng = build_default_engine()
    assert eng._router._routing_map[ModelFamily.ANTHROPIC][0][0] == ModelFamily.GOOGLE  # default

    monkeypatch.setenv("PRISM_LOCAL_VERIFIER_ENDPOINT", "http://localhost:8092")
    eng2 = build_default_engine()
    assert eng2._router._routing_map[ModelFamily.ANTHROPIC][0][0] == ModelFamily.LOCAL_VERIFIER
    assert "local-verifier" in eng2._providers
