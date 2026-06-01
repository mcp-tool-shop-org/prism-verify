"""Tests for receipt store."""


import pytest

from prism.core.types import ReasoningVisibility
from prism.receipts.store import ReceiptStore


@pytest.fixture
def store(tmp_path):
    """Create a receipt store with a temp database."""
    db_path = tmp_path / "test_receipts.db"
    s = ReceiptStore(db_path=db_path, signing_secret=b"test-secret")
    yield s
    s.close()


class TestReceiptStore:
    def test_create_receipt(self, store):
        receipt = store.create_receipt(
            pre_strip_hash="aaa",
            post_strip_hash="bbb",
            verifier_models=["gemini-2.5-pro"],
            pairwise_rho={"L1,L2": 0.15},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=0.9,
            retryable=False,
            lens_results_json="[]",
        )
        assert receipt.id.startswith("prism-")
        assert receipt.pre_strip_hash == "aaa"
        assert receipt.post_strip_hash == "bbb"
        assert receipt.signature != ""

    def test_get_receipt(self, store):
        receipt = store.create_receipt(
            pre_strip_hash="xxx",
            post_strip_hash="yyy",
            verifier_models=["model-a"],
            pairwise_rho={},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="refuse",
            confidence=0.95,
            retryable=False,
            lens_results_json="[]",
        )

        fetched = store.get_receipt(receipt.id)
        assert fetched is not None
        assert fetched["id"] == receipt.id
        assert fetched["verdict"] == "refuse"

    def test_get_nonexistent_receipt(self, store):
        assert store.get_receipt("prism-nonexistent") is None

    def test_verify_signature_valid(self, store):
        receipt = store.create_receipt(
            pre_strip_hash="hash1",
            post_strip_hash="hash2",
            verifier_models=["model"],
            pairwise_rho={"L1,L2": 0.1},
            reasoning_visibility_mode=ReasoningVisibility.STRIPPED,
            verdict="accept",
            confidence=0.85,
            retryable=False,
            lens_results_json="[]",
        )
        assert store.verify_signature(receipt.id) is True

    def test_verify_signature_invalid_id(self, store):
        assert store.verify_signature("prism-does-not-exist") is False
