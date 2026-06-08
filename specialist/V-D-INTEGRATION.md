# V-D — wiring the Verifier specialist into prism-verify (design note)

Written during V-A generation (2026-06-05) after reading prism's lens/provider/citation code, so V-D
moves fast once the adapter is trained + certified. **Correction to the kickoff's framing below.**

## The integration point is the CITATION groundedness lens, NOT the artifact groundedness lens

prism has two distinct "L4" surfaces — pick the right one:

| surface | file | interface | fit for our verifier |
|---|---|---|---|
| **Artifact** groundedness lens | `src/prism/lenses/groundedness.py` | `(artifact, intent) → findings-JSON` (detect fabricated APIs/refs in *code*) | ✗ wrong shape — not (evidence, claim) |
| **Citation** groundedness lens | `src/prism/core/citations.py` (+ engine orchestration) | `(claim, source) → supported \| contradicted \| not_addressed` | ✓ **this is the MiniCheck setting we trained for** |
| NLI encoder floor | `src/prism/lenses/nli.py` | `(claim, source) → supported \| refuted \| insufficient` via a DeBERTa cross-encoder, opt-in `PRISM_NLI_FLOOR` | orthogonal veto, already exists |

Our verifier is a fine-tuned LLM for `(evidence, claim) → {supported, unsupported, abstain}` — the exact
job of prism's **citation groundedness** check (`build_citation_groundedness_prompts` /
`parse_citation_groundedness`). The NLI floor is a separate encoder veto; we are the *LLM* local lens.

## Verdict mapping (clean)

| our verdict | prism citation outcome |
|---|---|
| supported   | supported |
| unsupported | contradicted |
| abstain     | not_addressed |

`parse_citation_groundedness` already fails SAFE — a parse failure → CANNOT_CONFIRM/escalate, never a
fabricated `supported`. Matches our cost-asymmetry (a false "supported" is the costly error).

## Serving (same proven path as the budgeter)

WSL Docker llama.cpp `ghcr.io/ggml-org/llama.cpp:full-cuda`, `-m Qwen3-14B-Q4_K_M.gguf
--lora-init-without-apply --lora verifier-14b600-soup.gguf`, then POST `/lora-adapters [{"id":0,"scale":4.0}]`
(rsLoRA serves at scale 4 — the converter bakes α/r). WSL path only (rig-safety). Never serve while training.

## The bridge (shim or in-process provider) — decide with engine.py open

prism's citation lens calls a provider with ITS prompt+vocab; our model speaks OUR prompt
(`config.SYSTEM_PROMPT`) + verdict words. A thin adapter bridges them. Two options:
- **(A) standalone shim** (like the budgeter's `verify_shim.py`): prism's local provider → shim → our
  llama.cpp; shim reformats (source→EVIDENCE, claim→CLAIM), parses our verdict, maps vocab, returns
  prism's expected content. Pins the served `adapter_id` (mismatch → fail open).
- **(B) in-process `LocalVerifierProvider`** registered as a distinct local family in
  `build_providers_from_env` (`core/setup.py`) — cleaner, no extra process, but edits prism.

Either way the verifier registers as a verifier FAMILY distinct from the generator under audit
(family-different principle — our Qwen verifier ≠ the artifact's author). Confirm the engine's exact
fallback hook (`core/engine.py` — MIN_LENSES, VERIFIER_UNAVAILABLE, circuit breaker in `core/routing.py`)
at V-D time. **Fail-open target = prism's OTHER lenses / API verifier (the generalist verification path),
NOT a deterministic baseline** (that's the budgeter's fallback, not the verifier's).

## Open decision for Mike (V-D time, not now)
New local family `local-verifier` in the routing map vs. repointing the existing `local` Ollama backend
for the citation path. Default lean: a NEW family so the artifact-groundedness lens keeps mistral and only
the citation check uses the specialist. Revisit with engine.py + routing.py open.

---

# V-D IMPLEMENTATION SPEC (code-mapping workflow wf_9b844011, 2026-06-05)

Read of prism's actual engine/routing/citations/providers. **Buildable spec — exact lines.**

## Integration point (NO engine.py change needed)
`engine.py:_verify_citations` resolves the verifier provider at **engine.py:423** via
`self._providers.get(route.family.value)`, where `route = self._router.select_verifier(caller_family, available_families)`.
The prompt is built by `build_citation_groundedness_prompts` (engine.py:594-596), the model is called at
`provider.complete(...)` (engine.py:600-604), and the response parsed by `parse_citation_groundedness(resp.content)`
(engine.py:634). **Wiring is entirely provider + routing-map + ModelFamily enum** — no engine edits.

## Input contract (what our provider receives)
`CompletionRequest(system_prompt, user_prompt, model_id, max_tokens=2000, temperature=0.0)`.
EVIDENCE (source title+abstract) and CLAIM are **embedded in `user_prompt`** inside `<<<SOURCE…>>>` /
`<<<CLAIM…>>>` markers — NOT separate fields. Our provider either feeds prism's system+user verbatim to
the Qwen verifier, OR re-extracts the markered blocks and rebuilds them into the model's trained
EVIDENCE/CLAIM template (must match how the QLoRA was trained — decide at build).

## Output contract — **THE critical requirement**
`parse_citation_groundedness` does `json.loads(_extract_json(content))` and reads `data["outcome"]` ∈
`{supported, contradicted, not_addressed}`. `_extract_json` only strips ```fences``` + slices first `{`…last `}`.
**Our model's native `<think>…</think>\n\n{verdict}` has NO braces → json.loads fails → parser returns the
safe default `("not_addressed", None, 0.0)` → EVERY citation silently escalates.** So the provider MUST emit a
JSON object string:
```json
{"outcome":"supported|contradicted|not_addressed","confidence":0.0-1.0,"supporting_span":"…|null","detail":"…"}
```
**Verdict mapping** (our 3-way → prism's 3-way; our curriculum trained the distinction, so it maps cleanly):
- `supported`   → `supported`    → FindingMatch.SUPPORTED / **Verdict.ACCEPT**
- `unsupported` → `contradicted` → FindingMatch.CONTRADICTED / **Verdict.REVISE** ("FIX TO MATCH SOURCE")
- `abstain`     → `not_addressed`→ FindingMatch.NOT_ADDRESSED / **Verdict.ESCALATE** ("RETRIEVE FULL TEXT")

`confidence` is parsed+stored but NOT thresholded for the LLM lens (only the optional NLI floor + receipts
use it) → emit the model's score if available, else a constant.

## Recommended: Option B — in-process `LocalVerifierProvider`, NEW `local-verifier` family
Why not Option A (reuse OllamaProvider): prism's OllamaProvider hard-codes `format:"json"` + `think:false`,
which **returns EMPTY for thinking models** (documented at ollama.py:54-62, "qwen3:32b returned empty"). Routing
our thinking Qwen through it is the exact failure the code warns about. A dedicated `local-verifier` family
also keeps `local`=mistral as a real cross-family failover target.

**Files to add/edit:**
- NEW `src/prism/providers/local_verifier.py` — `LocalVerifierProvider(ModelProvider)`: `complete()` POSTs to
  llama.cpp (`/v1/chat/completions`, generous `num_predict` independent of prism's max_tokens=2000 so a long
  `<think>` isn't truncated), strips `<think>`, maps vocab, returns `CompletionResponse(content=json.dumps({...}))`,
  raises `ProviderError` on httpx error / empty think / unmappable token; `health_check()` → GET llama.cpp `/health`.
- EDIT `src/prism/core/types.py` (~L18): `ModelFamily.LOCAL_VERIFIER = "local-verifier"`.
- EDIT `src/prism/core/setup.py` build_providers_from_env(): conditionally register
  `providers["local-verifier"] = LocalVerifierProvider(endpoint=os.environ["PRISM_LOCAL_VERIFIER_ENDPOINT"], …)`.
  (Provider key MUST equal `family.value` — engine.py:423 looks up by it.)
- EDIT `src/prism/core/routing.py` DEFAULT_ROUTING_MAP (L20-41): add LOCAL_VERIFIER as a verifier candidate for
  the cloud callers + a LOCAL_VERIFIER caller row, ordered so a circuit-open walk reaches a hosted family.
- NEW tests: vocab round-trip (a real `supported` → Verdict.ACCEPT), think-strip, ProviderError on empty think,
  failover when the circuit opens.

## Fail-open (matches the kickoff: fall over to other lenses / API verifier, not a deterministic baseline)
`complete()` raises `ProviderError` on any served-model failure → engine catches at engine.py:605 →
`router.report_failure` trips the **circuit breaker after 3 fails/60s** (open 30s) → `select_verifier` skips the
open family and **walks to the next cross-family route** (Anthropic/OpenAI/Google if keyed, or mistral `local`).
Limitation: `select_verifier` runs once **per request** (engine.py:413), so within one request a Qwen failure
escalates that citation; cross-family failover kicks in on the next request after the breaker opens. (If
fail-open WITHIN a request is needed, the provider can internally delegate to a hosted provider before raising.)

## Open decisions for Mike (at V-D build)
1. **Vocab semantics:** keep `unsupported→contradicted` (REVISE — our L2 is a planted swap/violation, fits
   "fix to match source") vs the conservative `unsupported→not_addressed` (ESCALATE). Lean: contradicted, but
   **validate empirically on the V-C exam**; make it a one-line constant so it's swappable.
2. **Input templating:** feed prism's prompt verbatim vs re-template to the trained EVIDENCE/CLAIM shape.
3. **Keep mistral `local` registered** alongside `local-verifier` as a same-tier local fallback (recommended).
4. `model_id` plumbing: the new family's routing model_id string; the provider can ignore it and serve its one model.

## Risks (top)
- **SILENT-ESCALATE TRAP (highest):** returning native `<think>…token` unchanged → 100% silent ESCALATE, no error.
  Mitigation: provider emits JSON + a test asserts `supported` round-trips to ACCEPT.
- **Thinking-model empty output** under format:json+think:false → drive llama.cpp directly, own the chat template.
- **max_tokens=2000** may cut a long `<think>` before the verdict → set a generous llama.cpp num_predict.
- **Circuit-breaker masking:** under load, traffic silently shifts off the local verifier to a hosted API
  (good for fail-open, but cost/latency flips with no alert) → log report_failure + surface breaker-open in receipts.
