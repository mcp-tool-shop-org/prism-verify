# Standards Compliance — Prism v0.3.0

Scored against the six workflow standards defined in `E:/AI/.claude/rules/workflow-standards.md`.

| Standard | Score | Evidence |
|----------|-------|----------|
| PIN_PER_STEP | 3 | Receipts carry verifier model IDs, pre/post-strip SHA-256, `lens_prompt_hashes` (per-lens prompt hash), AND — for citations (v0.3, receipt schema v3) — the per-citation `retrieval_pins` (the retrieval query URL + retrieved-source SHA-256), all signed. Integration tests prove the pins persist and the signature verifies end-to-end. |
| ANDON_AUTHORITY | 3 | Enforced halts on both paths. Code: `STRIP_VERIFICATION_FAILED`, `VERIFIER_UNAVAILABLE`, `LENS_COLLAPSE`, and now `BUDGET_EXCEEDED` (a hard latency-budget timeout on the lens fan-out, v0.3 — was declared but never raised). Citations: existence-`FABRICATED` → refuse, numeric `CONTRADICTED` → revise, oracle-down → escalate. Each is exercised by tests. |
| NAMED_COMPENSATORS | 3 | `receipt delete` / `prune` undo the only irreversible write (the receipt INSERT). v0.3 adds a compensate-after-verify integration flow (verify → signed receipt → delete/prune → assert undo) proving the compensator end-to-end. The retrieval oracle is read-only/external (documented no-compensator). See `design/03-compensators.md`. |
| DECOMPOSE_BY_SECRETS | 3 | `core/` / `lenses/` / `providers/` / `receipts/` / `mcp/` / `http/` / `cli/` — plus v0.3's `retrieval/` (hides the arXiv/Crossref API surfaces) and `core/citations.py` (hides parsing + the numeric guard + the lens prompt). Each module hides one secret family (Parnas). |
| UNCERTAINTY_GATED_HUMANS | skip | Prism is a non-interactive library/service; humans live in the caller's workflow, reached via the `escalate` verdict. The v0.3 citation path sharpens this — an unresolvable / not-addressed citation escalates with a contrastive action verb (RETRIEVE MANUALLY) gated on epistemic uncertainty, not step count — but the human handoff is still caller-owned, so the standard remains a documented skip. See below. |
| EXTERNAL_VERIFIER | 3 | The prism-on-prism meta-test (`tests/integration/test_meta_citations.py`) verifies prism's own design-doc citations via a different family + retrieval-backed existence + metamorphic relations. Non-circular: it checks retrieval, not recall. Closes the launch bootstrap skip. See below. |

**Total: 15/15 = 100%** (one legitimate skip excluded from the denominator), up from **12/15 (80%)**
at v0.2.0 — **EXTERNAL_VERIFIER 1→3** and **NAMED_COMPENSATORS 2→3**, plus **BUDGET_EXCEEDED**
enforced (ANDON), landed in the v0.3 dogfood pass alongside the citation-verification layer
(`design/04-citation-verification.md`).

## UNCERTAINTY_GATED_HUMANS — skip justification

Prism is a **library/service** consumed by agent workflows. It has no direct human interface.
When prism returns `verdict: escalate`, the calling system (Role OS, shipcheck, CLI user) is
responsible for surfacing the escalation to a human. Prism's contract is: "I will tell you when
I'm uncertain" — the caller's contract is: "I will not proceed without human review when told."

The v0.3 citation layer makes that escalation richer (a distinct action verb per failure mode —
DROP / FIX METADATA / FIX TO MATCH SOURCE / RETRIEVE MANUALLY — and the `CANNOT_CONFIRM`
distinction between "refuted" and "could not verify"), which is the contrastive, uncertainty-
gated framing the standard asks for. But prism still does not *reach* the human itself, so this
remains the correct decomposition and a documented skip rather than a scored row.

## EXTERNAL_VERIFIER — resolved at v0.3 (was a bootstrap skip)

The launch bootstrap problem (the first prism instance cannot be verified by prism) is resolved
by a **metamorphic** meta-test, not a circular self-grade. `tests/integration/test_meta_citations.py`:

- runs prism's **OWN** design-doc citations through the citation pipeline;
- with a verifier of a **different family** from the artifact author (caller=anthropic → the L1
  router excludes anthropic), the generator's reasoning hidden (L2);
- with existence decided by **live retrieval** (mocked arXiv/Crossref in CI), so the test checks
  RETRIEVAL, not the model's recall — the property that makes it non-circular (Naser 2026,
  arXiv:2603.03299; Kambhampati 2024, arXiv:2402.01817);
- asserting **metamorphic relations** (Cho 2025, arXiv:2511.02108) that hold with no
  ground-truth oracle: corrupt an identifier → existence MUST flip resolve→refuse; swap a
  contradictory number → the verdict MUST move off accept; reorder authors → the verdict MUST be
  invariant.

This is a genuine metamorphic / N-version test (the verifier is decorrelated from the author by
construction), not a model grading its own homework — the EXEMPLARY (3) evidence. The remaining
external verification of the engine itself stays:
- 142 tests (deterministic; unit + integration, incl. the citation pipeline against mocked
  retrieval and the prism-on-prism meta-test);
- CI with mypy --strict + ruff (static analysis);
- the research-grounding documents (design review);
- human code review on push.
