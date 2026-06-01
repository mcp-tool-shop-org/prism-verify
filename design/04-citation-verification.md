# Prism — Citation Verification (v0.3.0 product layer)

The v0.3 headline layer. Adds a **citation/source artifact type** so prism can adjudicate the
one thing every research-grounded workflow needs verified: *does this cited paper exist, and
does it actually say what the citation claims it says?* This is the verifier the
[research-grounded-advisor protocol] committed prism to be (its Step 4 names prism as the
citation verifier; its ollama-intern + arXiv stopgap is waiting to be deleted once this lands).

It also resolves two questions deferred in `design/01-research-grounding.md`:
- **"L4 Groundedness for non-RAG artifacts"** — made moot by making it *RAG*: the Groundedness
  lens is fed the **retrieved** source, never parametric recall.
- **"Prose/RAG verification track"** — citations are the first prose/RAG artifact track.

## The architecture, in one line

```
parse citations
  -> EXISTENCE FLOOR (deterministic retrieval: arXiv-ID, then DOI)   [ANDON]
  -> NUMERIC GUARD (deterministic numeral extract + compare)         [ANDON]
  -> GROUNDEDNESS (family-different LLM lens on the RETRIEVED source)
  -> per-citation verdict -> aggregate -> signed receipt (retrieval PINs)
```

The load-bearing rule from the whole literature: **existence and groundedness are independent
failure surfaces, and existence is NOT an LLM job.** Keep them as distinct stages — a retrieval
oracle decides existence; the LLM only judges support on what the oracle retrieved.

---

## Research grounding (the empirical floor)

From the v0.3 study-swarm (`wf_ad12e289-16b`, 2026-06-01, 5 parallel agents) plus the empirical
grounding already in hand from the protocol's stopgap run. Each finding is connected to a
specific design decision — citations without architectural connection are noise.

### Existence retrieval (Q1)

1. **arXiv resolves deterministically by exact identifier; versioned IDs are first-class.**
   arXiv API User's Manual 2025 (`export.arxiv.org/api/query?id_list={id}`). A bare ID returns
   the latest version, `vN` returns a specific version; an empty Atom feed (zero `<entry>`) is
   the unambiguous non-resolution. → **arXiv-ID-first is the primary existence probe; empty feed
   = ANDON refuse. Accept `vN` on input, canonicalize by stripping the version. No auth.**
2. **Crossref needs `rows=2` to detect an ambiguous match.** Crossref REST API tips 2025. A
   near-tie between the top-two relevance scores means the match is inconclusive. → **DOI lookup
   (`/works/{doi}`) is the deterministic second probe; bibliographic search is a lower-trust
   fallback whose near-ties map to CANNOT_CONFIRM, never a silent accept. Send `mailto` for the
   polite pool (10 r/s vs 5 r/s single, eff. 2025-12-01).**
3. **Fuzzy metadata matching is inherently lossy.** Guenci et al. 2025 (arXiv:2511.18408): ~39%
   of Crossref's 1.8B references carry no DOI; best parser (GROBID) hits only F1 ≈ 0.89. →
   **Bias the existence stage toward PRECISION: a fuzzy-title-only match can only DOWNGRADE to
   CANNOT_CONFIRM, never upgrade a non-resolving citation to accept.**
4. **Distinguish oracle-down from genuine zero-result.** OpenAlex now returns HTTP 409 on
   missing-key (OurResearch 2026), and 10–20% of references stay UNKNOWN due to
   bot-blocking/paywalls (Rao et al. 2026, arXiv:2604.03173). → **A transient/auth/parse failure
   is UNRESOLVABLE → CANNOT_CONFIRM/escalate, NOT a fabrication refuse. Auto-refusing the unknown
   bucket is a known false-flag failure mode.** Semantic Scholar / OpenAlex are optional,
   key-gated ENRICHMENT only; arXiv + Crossref are the free floor.

### RAG groundedness (Q2)

5. **Existence and support fail independently.** Onweller et al. 2026 (arXiv:2605.06635): in
   deep-research agents, >94% of links are valid and >80% on-topic, yet only 39–77% factually
   support the attached claim. → **Never collapse "resolved" into "verified"; run groundedness as
   a fully separate gate even after retrieval succeeds.**
6. **Feed paragraph-scale evidence, not sentences or whole PDFs.** Wang et al. 2026
   (arXiv:2604.01432): atomic-sentence citation granularity degrades attribution 16–276% vs the
   paragraph optimum. SciFact (Wadden et al. 2020, arXiv:2004.14974) verifies claims against
   abstracts. → **The title+abstract is a near-ideal evidence window; feed the abstract as a
   coherent block. Abstract-only has a real ceiling (VeriSci 46.5 F1), so number-bearing or
   abstract-unsupported claims ESCALATE to full text rather than emit a confident accept.**
7. **Numeric mismatch is NOT an LLM-lens job.** Naik et al. 2018 (arXiv:1806.00692): NLI
   backbones rubber-stamp number swaps ("two children"→"four humans" scored ENTAILMENT).
   QuanTemp (Venktesh et al. 2024, arXiv:2403.17169): best numerical-claim verifier tops out at
   macro-F1 58.32. → **Extract numerals + units + comparators from BOTH the claim and the
   retrieved source and compare DETERMINISTICALLY (Proof-Carrying-Numbers, Solatorio 2025,
   arXiv:2509.06902). A numeric divergence is an ANDON-class mismatch the reasoning-stripped lens
   is structurally blind to — exactly the "95.8% vs 89%" class the protocol already caught.**
8. **Decompose before judging.** RefChecker (Hu et al. 2024, arXiv:2405.14486): claim-triplets
   beat sentence-level by 6.8–26.1 pts; its Zero/Noisy/Accurate context regimes map onto
   CANNOT_CONFIRM / revise / accept. RAGAS (Es et al. 2023, arXiv:2309.15217) flags
   parametric-only statements. → **Normalize the finding-claim to a standalone statement and
   have the lens cite the supporting span (SciFact rationale) before accepting.**

### Self-referential bootstrap (Q3) — the meta-test

9. **Frame prism-on-prism as METAMORPHIC, not self-grading.** Cho et al. 2025
   (arXiv:2511.02108): assert relations across related executions when no oracle exists. →
   **Meta-test metamorphic relations:** MR1 reorder authors/whitespace → verdict unchanged; MR2
   corrupt one identifier char → existence MUST flip resolve→refuse; MR3 swap a contradictory
   number → groundedness MUST move accept→revise/refuse.
10. **N-version diversity needs real family difference.** Knight & Leveson 1986 (IEEE TSE):
    same-spec versions fail coincidentally. Wataoka et al. 2024 (arXiv:2410.21819): judges
    over-rate their OWN FAMILY via familiarity/low-perplexity. → **Meta-test lenses MUST differ
    in family from the doc's authoring model AND vary the prompt (a shared prompt is a shared
    spec). Treat lens DISAGREEMENT differentially (escalate), not as noise to average.**
11. **LLMs cannot self-verify; existence-by-LLM inherits 11–57% fabrication.** Kambhampati et al.
    2024 (arXiv:2402.01817); Huang et al. 2023 (arXiv:2310.01798); Naser et al. 2026
    (arXiv:2603.03299). → **The meta-test is non-circular precisely because existence is grounded
    OUTSIDE any model's memory: prism checks retrieval, not recall. Resolve every design-doc
    citation against live arXiv/Crossref and ANDON-refuse on non-resolution before any lens runs.**

### Local structured output (Q4) — confirms the health-pass pin

12. **Constrained JSON is faster and more accurate; thinking is the trap.** JSONSchemaBench
    (Geng et al. 2025, arXiv:2501.10868): constraining is ~50% faster AND +3% accuracy. Ollama
    issue #10538: `format` zeroes the `<think>` token — incompatible with thinking mode.
    Mistral-Small-3.2-Instruct is tuned for JSON + reduced runaway generation. → **The
    `mistral-small:24b` + `format=json` + `think=false` pin landed in the health pass is the
    correct architecture, not a workaround.**

### Verdict UX (Q5) — the two-axis mapping

13. **Absence of evidence ≠ contradiction.** FEVER (Thorne et al. 2018, arXiv:1803.05355) keeps
    NOT-ENOUGH-INFO distinct from REFUTED; reinforced hesitation (Mohamadi et al. 2025,
    arXiv:2511.11500) argues for a first-class abstain state; RAGTruth (Niu et al. 2024,
    arXiv:2401.00396) splits Evident Conflict (numeric class) from Baseless Information. Clear
    verdict wording moves correct interpretation 82.9%→89.1% (Hettiachchi et al. 2023, CIKM).
    → **Two-axis verdict + a one-line action verb per outcome (below). CANNOT_CONFIRM is
    first-class; collapsing it into refuse silently destroys real-but-unretrieved citations.**

---

## Locked design

### Artifact

`ArtifactType.CITATIONS`. The artifact content is a JSON array of citations; each:

```json
{"id": "khalifa-2601", "title": "...", "authors": "Khalifa et al.", "year": 2026,
 "identifier": "arXiv:2601.14691", "claim": "manipulated CoT inflates judge FPs up to 90%"}
```

`identifier` accepts `arXiv:<id>`, a bare arXiv id (incl. `vN`), or a DOI. `claim` is the
one-sentence finding to ground. `id` is the caller's local handle (echoed in results/receipt).

### Stage 1 — existence floor (deterministic retrieval, ANDON)

`CitationOracle.resolve(citation)` → `ExistenceResult{outcome, source_title, source_abstract,
query, source_sha256, detail}`. Tiered, precision-biased:

1. **arXiv-ID-first** — `GET export.arxiv.org/api/query?id_list={id}` (accept `vN`). One `<entry>`
   → `RESOLVED` (carry title + summary/abstract). Empty feed → `FABRICATED`.
2. **DOI-second** — `GET api.crossref.org/works/{doi}?mailto=...`. 200 + message → `RESOLVED`
   (title; abstract if present). 404 → `FABRICATED`.
3. **No resolvable identifier / transient (timeout, 5xx, 429, parse error, auth)** →
   `UNRESOLVABLE` (oracle-down or fuzzy-only). Never `FABRICATED`.
4. Metadata present but title/author/year disagree with the resolved record →
   `METADATA_MISMATCH`.

`FABRICATED` halts that citation at refuse (ANDON). The oracle is **read-only and external** —
no compensator (see below), but it caches per-identifier within a run and honors rate-limit
etiquette (arXiv ~3 s serialization, Crossref `mailto`).

### Stage 2 — numeric guard (deterministic, ANDON)

`numeric_mismatch(claim, source)` extracts numerals + `%`/comparators from the claim and the
retrieved title+abstract. A number in the claim that contradicts the source (and no number in
the source supports it) is a `CONTRADICTED` finding — emitted **before** the LLM lens, because
the lens is structurally blind to it (finding 7). Only runs when an abstract was retrieved.

### Stage 3 — groundedness (RAG-fed L4 lens, family-different, reasoning-stripped)

Feed the **retrieved** title+abstract (paragraph-scale) + the standalone claim to a
family-different verifier. Outcome ∈ {`SUPPORTED`, `CONTRADICTED`, `NOT_ADDRESSED`}; on
`SUPPORTED` it records the supporting span. Built via the existing `parse_lens_response` +
`compute_prompt_hash` machinery (PIN). Only runs on `RESOLVED` citations with an abstract; a
resolved citation with no abstract → `NOT_ADDRESSED` (escalate to full text).

### Verdict mapping (two-axis)

| Stage outcome | Verdict class | Action verb to the caller |
|---|---|---|
| Existence `FABRICATED` | **REFUSE** (critical) | DROP — no record in arXiv/Crossref |
| Existence `METADATA_MISMATCH` | **REVISE** (major) | FIX METADATA — real paper, wrong title/author/year |
| Existence `UNRESOLVABLE` | **ESCALATE** (uncertain) | RETRIEVE MANUALLY — oracle down/blocked, not refuted |
| Numeric / groundedness `CONTRADICTED` | **REVISE** (major), REFUSE if unfixable | FIX TO MATCH SOURCE (span quoted) |
| Groundedness `NOT_ADDRESSED` | **ESCALATE** (uncertain) | RETRIEVE FULL TEXT — abstract lacks the passage |
| All `SUPPORTED` | **ACCEPT** (pass) | — |

The artifact verdict aggregates per-citation classes through the existing `aggregate_verdict`
(any REFUSE→REFUSE; else any REVISE→REVISE; else any ESCALATE→ESCALATE; else ACCEPT), so the
four-value enum lock (`design/01`) holds. The protocol's **`CANNOT_CONFIRM`** maps to **ESCALATE**
— first-class, never folded into refuse.

### Receipt (schema v3, retrieval PINs)

The receipt gains `artifact_type` and `retrieval_pins` (per-citation `{id, query, source_sha256,
existence_outcome}`). Both are **signed** at schema v3 (`artifact_type` + a SHA-256 of
`retrieval_pins` enter the HMAC payload); v1/v2 receipts still verify against their own
field-set. Migration is the v0.2.0 discipline again: `PRAGMA user_version` + idempotent `ALTER
TABLE ADD COLUMN ... DEFAULT`, legacy rows untouched. This makes a citation verdict replayable:
the query URL + source hash pin exactly what was retrieved.

---

## Standards compliance

Scored against the six [workflow standards]. This layer is part of the prism workflow; the score
is for the citation path specifically.

| Standard | Score | Evidence |
|---|---|---|
| PIN_PER_STEP | **3** | Receipt pins the retrieval query URL + retrieved-source SHA-256 per citation, the groundedness lens prompt hash, and the verifier model — all signed at schema v3. The integration test asserts the pins persist and the signature verifies. |
| ANDON_AUTHORITY | **3** | Three enforced halts: existence `FABRICATED` → refuse, numeric `CONTRADICTED` → revise/refuse, and the oracle-down/`NOT_ADDRESSED` → escalate (never a silent accept). Each is exercised by tests against mocked retrieval. |
| NAMED_COMPENSATORS | **3** | The only irreversible write is the receipt INSERT, compensated by the existing `receipt delete`/`prune` (now exercised end-to-end by the compensate-after-verify flow — see `design/03`). The retrieval oracle is read-only/external: documented no-compensator with caching + rate-limit etiquette. |
| DECOMPOSE_BY_SECRETS | **3** | New `prism.retrieval` package hides the arXiv/Crossref API surfaces; `core/citations.py` hides parsing + numeric extraction; the groundedness prompt hides the lens framing; the engine orchestrates. Each module hides one secret family (Parnas). |
| UNCERTAINTY_GATED_HUMANS | **2** | Citations give prism a genuine uncertainty-gated human handoff: `UNRESOLVABLE`/`NOT_ADDRESSED` → ESCALATE with a contrastive action verb ("you likely expected this citable; the oracle could not confirm it — retrieve manually before relying"). Gated on epistemic uncertainty, not step count. Still caller-surfaced (prism is non-interactive), so held at 2. |
| EXTERNAL_VERIFIER | **3** | This layer is the substrate for the prism-on-prism meta-test (`tests/integration/test_meta_citations.py`): it verifies prism's OWN design-doc citations via a different family + metamorphic relations + retrieval-backed existence. See `design/02` EXTERNAL_VERIFIER 1→3. |

### Irreversible actions & compensators

The citation path performs exactly one irreversible write — the **receipt INSERT** — already
covered by the `receipt delete` / `receipt prune` compensators in `design/03-compensators.md`
(no new row needed). The **retrieval oracle is read-only and external**: a GET against arXiv /
Crossref. It needs no compensator. Etiquette instead of rollback: per-identifier response
caching within a run, arXiv ~3 s serialization, and a Crossref `mailto` for the polite pool — so
the oracle is a courteous, idempotent reader, never a writer.

---

## Out of scope (v0.3)

- Semantic Scholar / OpenAlex enrichment tiers (key-gated; arXiv + Crossref are the free floor).
- Full-text retrieval (the `NOT_ADDRESSED`/numeric path escalates to a human for it).
- Crossref bibliographic title-search fallback (fuzzy-only → `UNRESOLVABLE` for now; a precision
  bias, per finding 3).

[research-grounded-advisor protocol]: ../README.md
[workflow standards]: ./02-standards-compliance.md
