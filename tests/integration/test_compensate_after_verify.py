"""NAMED_COMPENSATORS 2->3: a compensate-after-verify flow proving the undo end-to-end.

verify() writes a signed receipt — the irreversible INSERT (design/03). The named compensators
(receipt delete / prune) undo it. This exercises the FULL loop against a receipt produced by a
real verification (not a synthetic row), which is the evidence that elevates NAMED_COMPENSATORS
from PRESENT (2) to EXEMPLARY (3): an irreversible action with a named undo, tested to undo.
"""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import respx

from prism.core.engine import VerificationEngine
from prism.core.routing import FamilyRouter
from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    ModelFamily,
    VerifyRequest,
    VerifyResponse,
)
from prism.lenses.boundary import CrossBoundaryLens
from prism.lenses.contract import ContractCompletenessLens
from prism.lenses.groundedness import GroundednessLens
from prism.lenses.invariant import InvariantLens
from prism.lenses.registry import register_lens
from prism.providers.ollama import OllamaProvider
from prism.receipts.store import ReceiptStore

OLLAMA = "http://test-ollama"


def _engine(tmp_path):
    register_lens(ContractCompletenessLens())
    register_lens(CrossBoundaryLens())
    register_lens(InvariantLens())
    register_lens(GroundednessLens())
    router = FamilyRouter(
        routing_map={ModelFamily.ANTHROPIC: [(ModelFamily.LOCAL, "mistral-small:24b")]}
    )
    store = ReceiptStore(db_path=tmp_path / "receipts.db", signing_secret=b"compensate-secret")
    engine = VerificationEngine(
        providers={"local": OllamaProvider(base_url=OLLAMA)}, router=router, receipt_store=store
    )
    return engine, store


def _request() -> VerifyRequest:
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CODE, content="def add(a, b):\n    return a + b\n"),
        intent="Add two integers and return the sum.",
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="claude-x"),
    )


async def _verify_once(engine) -> VerifyResponse:
    lens_json = json.dumps({"outcome": "pass", "confidence": 0.95, "findings": []})
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{OLLAMA}/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": lens_json}})
        )
        result = await engine.verify(_request())
    assert isinstance(result, VerifyResponse)
    return result


async def test_verify_then_delete_undoes_the_receipt(tmp_path):
    engine, store = _engine(tmp_path)
    result = await _verify_once(engine)
    rid = result.receipt.id

    # 1) The irreversible write landed and is signed.
    assert store.get_receipt(rid) is not None
    assert store.verify_signature(rid) is True
    # 2) The named compensator undoes it.
    assert store.delete_receipt(rid) is True
    # 3) Undo asserted: the receipt is gone, and a second compensate is a no-op.
    assert store.get_receipt(rid) is None
    assert store.delete_receipt(rid) is False
    store.close()


async def test_verify_then_prune_undoes_by_age(tmp_path):
    engine, store = _engine(tmp_path)
    result = await _verify_once(engine)
    rid = result.receipt.id

    # Backdate the signed UTC timestamp so prune's age cutoff selects this receipt.
    store._conn.execute(
        "UPDATE receipts SET timestamp = ? WHERE id = ?",
        ("2020-01-01T00:00:00+00:00", rid),
    )
    store._conn.commit()

    assert store.prune(timedelta(days=30)) == 1
    assert store.get_receipt(rid) is None
    store.close()
