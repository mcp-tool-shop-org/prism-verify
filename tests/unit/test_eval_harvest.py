"""Tests for the opt-in L4 capture sink (prism.eval.harvest).

Pins: default-OFF (no env => no capture, no file), the citation/groundedness label mappings,
the position-join from CitationResult back to the input claim, existence-failure skipping,
VerifyError no-op, best-effort secret scrubbing, and the JSONL append shape.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    CitationResult,
    ExistenceOutcome,
    Finding,
    FindingMatch,
    LensOutcome,
    LensResult,
    ModelFamily,
    ReasoningVisibility,
    Receipt,
    RefusalReason,
    Verdict,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.eval.harvest import HARVEST_SCHEMA, build_records, capture, harvest_enabled

# --- builders -------------------------------------------------------------------------------


def _receipt() -> Receipt:
    return Receipt(
        id="prism-test0001",
        pre_strip_hash="pre",
        post_strip_hash="post",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        verifier_models=["g"],
        pairwise_rho={},
        reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
        signature="sig",
    )


def _cite_request(claims: list[str], family: ModelFamily = ModelFamily.ANTHROPIC) -> VerifyRequest:
    content = json.dumps([{"claim": c, "id": f"c{i}"} for i, c in enumerate(claims)])
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CITATIONS, content=content),
        intent="verify each citation exists and the stated finding matches the source",
        caller=CallerContext(model_family=family, model_id="m"),
    )


def _code_request(content: str = "def f():\n    return 1\n", intent: str = "do X") -> VerifyRequest:
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CODE, content=content),
        intent=intent,
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="m"),
    )


def _cr(
    existence: ExistenceOutcome,
    finding_match: FindingMatch = FindingMatch.UNCHECKED,
    *,
    span: str | None = "the source supports the claim",
    abstract: str | None = "abstract text",
    confidence: float | None = 0.9,
) -> CitationResult:
    return CitationResult(
        citation_id="c0",
        identifier="2402.01817",
        existence=existence,
        finding_match=finding_match,
        verdict=Verdict.ACCEPT,
        action="OK",
        detail="d",
        source_abstract=abstract,
        supporting_span=span,
        confidence=confidence,
    )


def _glens(outcome: LensOutcome, findings: list[Finding] | None = None) -> LensResult:
    return LensResult(
        lens="groundedness",
        model_family="google",
        model_id="g",
        outcome=outcome,
        findings=findings or [],
        confidence=0.8,
    )


def _response(
    *,
    citation_results: list[CitationResult] | None = None,
    lens_results: list[LensResult] | None = None,
) -> VerifyResponse:
    return VerifyResponse(
        verdict=Verdict.ACCEPT,
        confidence=0.9,
        retryable=False,
        lens_results=lens_results or [],
        pairwise_rho={},
        citation_results=citation_results or [],
        receipt=_receipt(),
    )


# --- tests ----------------------------------------------------------------------------------


class TestDisabledByDefault:
    def test_capture_is_noop_without_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("PRISM_HARVEST_PATH", raising=False)
        assert harvest_enabled() is False
        req = _cite_request(["a claim"])
        resp = _response(citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED)])
        assert capture(req, resp) == 0
        # nothing created anywhere under tmp
        assert list(tmp_path.iterdir()) == []

    def test_build_records_is_pure_regardless_of_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # build_records never touches the filesystem or the env — it just projects.
        monkeypatch.delenv("PRISM_HARVEST_PATH", raising=False)
        req = _cite_request(["a claim"])
        resp = _response(citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED)])
        recs = build_records(req, resp)
        assert len(recs) == 1


class TestCitationLabels:
    def test_supported(self) -> None:
        req = _cite_request(["transformers scale well"])
        resp = _response(citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED)])
        (rec,) = build_records(req, resp)
        assert rec["verdict"] == "supported"
        assert rec["claim"] == "transformers scale well"
        assert rec["evidence_span"] == "the source supports the claim"
        assert rec["source"] == "prism-citation"
        assert rec["producer_family"] == "anthropic"
        assert rec["receipt_id"] == "prism-test0001"
        assert rec["schema"] == HARVEST_SCHEMA

    def test_contradicted_is_unsupported(self) -> None:
        req = _cite_request(["a claim"])
        resp = _response(
            citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.CONTRADICTED)]
        )
        (rec,) = build_records(req, resp)
        assert rec["verdict"] == "unsupported"

    def test_not_addressed_is_abstain(self) -> None:
        req = _cite_request(["a claim"])
        resp = _response(
            citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.NOT_ADDRESSED)]
        )
        (rec,) = build_records(req, resp)
        assert rec["verdict"] == "abstain"

    def test_unchecked_is_skipped(self) -> None:
        req = _cite_request(["a claim"])
        resp = _response(
            citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.UNCHECKED)]
        )
        assert build_records(req, resp) == []

    @pytest.mark.parametrize(
        "existence",
        [
            ExistenceOutcome.FABRICATED,
            ExistenceOutcome.UNRESOLVABLE,
            ExistenceOutcome.METADATA_MISMATCH,
        ],
    )
    def test_existence_failures_skipped(self, existence: ExistenceOutcome) -> None:
        # These train the existence floor, not groundedness — never captured as L4.
        req = _cite_request(["a claim"])
        resp = _response(citation_results=[_cr(existence, FindingMatch.SUPPORTED)])
        assert build_records(req, resp) == []

    def test_span_falls_back_to_abstract(self) -> None:
        req = _cite_request(["a claim"])
        resp = _response(
            citation_results=[
                _cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED, span=None)
            ]
        )
        (rec,) = build_records(req, resp)
        assert rec["evidence_span"] == "abstract text"

    def test_missing_claim_and_evidence_skipped(self) -> None:
        req = _cite_request(["a claim"])
        resp = _response(
            citation_results=[
                _cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED, span=None, abstract=None)
            ]
        )
        assert build_records(req, resp) == []

    def test_position_join_across_multiple_citations(self) -> None:
        req = _cite_request(["claim zero", "claim one"])
        resp = _response(
            citation_results=[
                _cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED),
                _cr(ExistenceOutcome.RESOLVED, FindingMatch.CONTRADICTED),
            ]
        )
        recs = build_records(req, resp)
        assert [r["claim"] for r in recs] == ["claim zero", "claim one"]
        assert [r["verdict"] for r in recs] == ["supported", "unsupported"]


class TestGroundednessLens:
    def test_pass_no_findings_is_supported_artifact(self) -> None:
        req = _code_request(content="import time\n\ntime.sleep(1)\n", intent="sleep one second")
        resp = _response(lens_results=[_glens(LensOutcome.PASS)])
        (rec,) = build_records(req, resp)
        assert rec["verdict"] == "supported"
        assert rec["claim"] == "import time\n\ntime.sleep(1)\n"
        assert rec["evidence_span"] == "sleep one second"
        assert rec["source"] == "prism-groundedness"

    def test_fail_findings_are_unsupported_claims(self) -> None:
        req = _code_request()
        findings = [
            Finding(
                category="phantom_api", evidence="time.snooze does not exist", severity="major"
            ),
            Finding(
                category="phantom_api", evidence="dict.length() is not real", severity="major"
            ),
        ]
        resp = _response(lens_results=[_glens(LensOutcome.FAIL, findings)])
        recs = build_records(req, resp)
        assert [r["verdict"] for r in recs] == ["unsupported", "unsupported"]
        assert recs[0]["claim"] == "time.snooze does not exist"

    def test_errored_lens_is_skipped(self) -> None:
        req = _code_request()
        lr = LensResult(
            lens="groundedness",
            model_family="google",
            model_id="g",
            outcome=LensOutcome.UNCERTAIN,
            findings=[Finding(category="provider_error", evidence="boom", severity="major")],
            confidence=0.0,
            errored=True,
        )
        assert build_records(req, _response(lens_results=[lr])) == []

    def test_non_groundedness_lenses_ignored(self) -> None:
        req = _code_request()
        other = LensResult(
            lens="contract_completeness",
            model_family="google",
            model_id="g",
            outcome=LensOutcome.FAIL,
            findings=[Finding(category="missing_clause", evidence="x", severity="major")],
            confidence=0.7,
        )
        assert build_records(req, _response(lens_results=[other])) == []


class TestCaptureToFile:
    def test_appends_jsonl_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out = tmp_path / "nested" / "harvest.jsonl"
        monkeypatch.setenv("PRISM_HARVEST_PATH", str(out))
        req = _cite_request(["a claim"])
        resp = _response(citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED)])

        assert capture(req, resp) == 1
        assert capture(req, resp) == 1  # append, not overwrite

        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        rec = json.loads(lines[0])
        assert rec["schema"] == HARVEST_SCHEMA
        assert rec["verdict"] == "supported"

    def test_verify_error_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out = tmp_path / "harvest.jsonl"
        monkeypatch.setenv("PRISM_HARVEST_PATH", str(out))
        req = _cite_request(["a claim"])
        err = VerifyError(reason=RefusalReason.INVALID_ARTIFACT, detail="bad")
        assert capture(req, err) == 0
        assert not out.exists()

    def test_no_signal_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out = tmp_path / "harvest.jsonl"
        monkeypatch.setenv("PRISM_HARVEST_PATH", str(out))
        # a RESOLVED-but-UNCHECKED citation yields no L4 record
        resp = _response(citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.UNCHECKED)])
        assert capture(_cite_request(["a claim"]), resp) == 0
        assert not out.exists()


class TestScrub:
    def test_secrets_redacted_before_write(self) -> None:
        req = _cite_request(["call api with sk-ABCDEF0123456789XYZ now"])
        resp = _response(
            citation_results=[
                _cr(
                    ExistenceOutcome.RESOLVED,
                    FindingMatch.SUPPORTED,
                    span="contact admin@example.com for the bearer abcdef0123456789ABCDEF token",
                )
            ]
        )
        (rec,) = build_records(req, resp)
        assert "sk-ABCDEF0123456789XYZ" not in rec["claim"]
        assert "[REDACTED]" in rec["claim"]
        assert "admin@example.com" not in rec["evidence_span"]

    def test_custom_scrub_is_used(self) -> None:
        req = _cite_request(["a claim"])
        resp = _response(citation_results=[_cr(ExistenceOutcome.RESOLVED, FindingMatch.SUPPORTED)])
        (rec,) = build_records(req, resp, scrub=lambda s: "X")
        assert rec["claim"] == "X"
        assert rec["evidence_span"] == "X"
