# Dataset publish plan (deferred — pending HF trusted-publishing setup)

Decision (2026-06-06, director): **publish the verifier (groundedness) dataset to Hugging Face Hub;
HOLD the budgeter dataset.** Publishing is **deferred** until HF trusted-publishing / auth is set up
(director handling — ~2026-06-07). This doc makes that a turnkey execution step. Grounded by the
dataset-publish assessment workflow (`wf_48d968c2-551`).

## Verifier groundedness contrast set → HF Hub (GO, once auth is ready)

**Why:** fills confirmed empty space — no public set crosses VitaminC-style contrastive evidence with
Gardner-2020 flip-consistency scoring on a clean 3-way `supported / unsupported / abstain` signal where
`abstain` is a deliberate contrast-group member (not an afterthought NEI bucket). The cross-family
generate-then-gate is itself a reusable methodology contribution. Text is fully fictional → zero
copyright/scrape exposure. The split is verifiably clean (0 `pair_id` and 0 claim-text overlap).

**INCLUDE (train-only + the recipe — lead with the recipe, it's the durable asset):**
- `verifier_train_sft.jsonl` (train-only SFT, ~923 records)
- `verifier_records.jsonl` **filtered to `split == "train"` only**
- the four authored seeds: `corpus_evidence.json`, `corpus_triples.json`, `corpus_conjuncts.json`,
  `corpus_hops.json`
- all generation/gate scripts: `synth.py`, `build_verifier_dataset.py`, `puzzles.py`, `gen_phase2.py`,
  `validate_gate.py`, `config.py`
- a HF dataset card (5-section structure)

**WITHHOLD (do NOT publish — publishing burns the benchmark):**
- `verifier_exam_records.jsonl` (358 records) + the exam `pair_id`s/answers. Keep private +
  regenerable from the scripts. (Benchmark-contamination risk — arXiv:2505.18102.)

**Before release:**
- **Add a BIG-bench-style canary GUID** to every published record (binary contamination detection;
  none is embedded yet).
- **License (dual):** data → **CC-BY-4.0**; generation code → **Apache-2.0**.
- **Dataset card must:** credit Gardner et al. 2020 (arXiv:2004.02709, contrast sets / flip-consistency
  lineage); disclose the cross-family gate (Qwen3 generator / Mistral-Small judge, **generator
  reasoning hidden**); frame it as a **diagnostic contrast set layered on LLM-AggreFact / VitaminC**,
  not a standalone training corpus; disclose model-assisted generation; note small N (~1.3k records /
  539 groups) so the **recipe is the primary durable artifact**, the static dump is a regenerable,
  canaried, train-only companion.

## Budgeter token-budget dataset → HOLD (do not publish now)

Qualified-yes only, GitHub-only + scripts-first, **low confidence — and blocked.**
- **Hard blocker:** ~186/1633 (~11%) of the L2 "which-costs-more" prompts embed **plausibly-real
  internal studio names** (`claude-synergy`, "audit agent", "feature audit"). `source_dispatch_ids` is
  already stripped from the SFT file, but the studio-telemetry fingerprint survives in the prompt
  **text**. Must template/anonymize before any publish.
- Upstream source dataset has **no LICENSE and no card** — must be created first.
- Niche is thin (RouterBench-adjacent); the custom weighted cost model (input×1, cache-write×1.25,
  cache-read×0.1, output×5) limits transfer → the **recipe**, not the static data, is the value.
- If ever published: GitHub scripts-first, withhold `puzzles_exam.jsonl` (305), CDLA-Permissive-2.0 /
  CC-BY-4.0 data + MIT/Apache code. **Default: skip unless the scrub + license/card are done.**
