---
title: Self-hosted groundedness verifier
description: Back prism's citation-groundedness check with a model you host yourself — opt-in, family-different, and fail-open to your hosted verifiers.
sidebar:
  order: 4.6
---

prism's citation path checks each claim against its retrieved source. The final, LLM-level step of
that check — the **groundedness lens** — can be backed by a model **you host** instead of a hosted
API. It is opt-in: set one environment variable and prism routes the citation check to your endpoint,
falling back to your hosted verifiers if it is unreachable.

Why you'd want it:

- **Zero per-call cost on the highest-frequency check.** Citation groundedness is the check that runs
  most often; moving it to a local model takes it off your hosted-API bill.
- **Evidence stays on your machine.** The claim and the retrieved source never leave your host.
- **A model tuned for the job.** You can serve a model fine-tuned specifically for grounded
  entailment rather than a general-purpose one.

## Where it sits

The citation path is a layered floor — each stage refuses what it can *prove*, else defers:

1. **Existence floor** — live arXiv/Crossref retrieval drops a fabricated identifier.
2. **Numeric/unit floor** — a percentage swap or comparison-direction falsehood is caught arithmetically.
3. **Groundedness lens** — the family-different LLM check against the retrieved abstract. **This is the
   step the local verifier serves.**
4. **NLI floor** *(opt-in, `PRISM_NLI_FLOOR`)* — an orthogonal encoder-NLI veto on a `supported`.

The local verifier registers as a distinct model family, **`local-verifier`**, separate from the
`local` (mistral) family — so Lock 1 (family-different) still holds, and mistral remains a failover
target rather than being displaced.

## Enable it

Point prism at an OpenAI-compatible chat endpoint:

```bash
export PRISM_LOCAL_VERIFIER_ENDPOINT=http://127.0.0.1:8092   # base URL of your served model
export PRISM_LOCAL_VERIFIER_MODEL=qwen3-14b-groundedness     # optional label (this is the default)
```

When `PRISM_LOCAL_VERIFIER_ENDPOINT` is set, prism injects the specialist as the **primary** citation
verifier for every caller, failing over to that caller's existing cross-family verifiers (your hosted
families, then mistral `local`) when its circuit opens. When the variable is **unset**, routing and
behavior are exactly as they were — this changes nothing until you opt in.

### Verdict mapping

The model's three-way verdict maps onto prism's citation outcomes:

| model verdict | prism outcome | action |
|---|---|---|
| `supported` | `supported` | **accept** |
| `unsupported` | `contradicted` | **revise** — fix the claim to match the source |
| `abstain` | `not_addressed` | **escalate** — retrieve the full text |

## Fail-open, by design

If the served model is unreachable, returns a bad body, or produces no readable verdict, the provider
raises an error rather than returning a default. prism's circuit-breaker then **fails over** to the
caller's hosted (or mistral) verifiers. A verifier outage is a loud failover — **never a silent
"escalate everything."**

Because the breaker fails over on **errors**, not on a confident-but-wrong `supported`, pair the local
verifier with the orthogonal NLI floor so a mechanistically-different model can veto a false confirm:

```bash
export PRISM_NLI_FLOOR=1     # recommended alongside the local verifier
```

## Serve your own

The provider talks plain OpenAI-compatible chat: it POSTs to `<endpoint>/v1/chat/completions` and
health-checks `<endpoint>/health`. **You do not need your model to emit JSON or follow prism's prompt
format.** The provider injects the groundedness system prompt, re-templates the source/claim into the
`EVIDENCE: … / CLAIM: …` shape the model expects, strips a leading reasoning (`<think>`) block, reads
the bare `supported | unsupported | abstain` verdict, and emits the JSON prism parses. So all you have
to serve is a chat model that reasons over evidence and a claim and answers with one of those three
words.

Any OpenAI-compatible server works (llama.cpp's server, vLLM, and others). The reference setup serves
a fine-tuned Qwen3-14B groundedness adapter under llama.cpp:

```bash
# llama.cpp server (CUDA), base model + the groundedness LoRA adapter
llama-server -m Qwen3-14B-Q4_K_M.gguf \
  --lora-init-without-apply --lora groundedness-adapter.gguf \
  --host 0.0.0.0 --port 8092

# the adapter is an rsLoRA adapter — apply it at scale 4
curl -s http://127.0.0.1:8092/lora-adapters \
  -H 'Content-Type: application/json' \
  -d '[{"id":0,"scale":4.0}]'
```

Then export `PRISM_LOCAL_VERIFIER_ENDPOINT=http://127.0.0.1:8092` and run `prism verify --type
citations …` as usual.

To **build the training data** for your own groundedness model from prism's own verifications, see the
[groundedness harvest sink](../harvest-sink/).
