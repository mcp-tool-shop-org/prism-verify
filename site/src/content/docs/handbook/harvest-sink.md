---
title: Groundedness harvest sink
description: Opt-in capture of the (claim, evidence, verdict) triples a verification produces — the training corpus for your own local groundedness verifier.
sidebar:
  order: 4.7
---

prism's receipts are a privacy-preserving audit trail: they store artifact **hashes**, not text, and
never keep the per-claim `(claim, evidence, verdict)` triples a verification computes. That makes the
receipt store useless as a *training corpus* — the clean triples exist only for the instant a
verification runs.

The **harvest sink** captures those triples at verify time, before they are discarded — so you can
build the dataset to train your own [self-hosted groundedness verifier](../local-verifier/). It is
opt-in and off by default.

## Enable it

```bash
export PRISM_HARVEST_PATH=~/prism-l4-harvest.jsonl   # any writable path
```

When `PRISM_HARVEST_PATH` is **unset**, nothing is captured, no file is written, and behavior is
exactly unchanged — the hook is a no-op. When it is set, prism appends one JSON record per captured
triple to that file.

## What it captures

- **Citation path** — each *resolved* citation becomes a clean triple: the claim, the retrieved
  supporting span (or full abstract), and the verdict. Existence failures (a fabricated or
  unresolvable identifier) are **skipped** — those train the existence floor, not groundedness.
- **Code/tool path** — the groundedness lens's judgment of an artifact against its intent.

Each record uses the `prism-l4-harvest/v1` schema:

| field | meaning |
|---|---|
| `claim` | the claim being checked |
| `evidence_span` | the retrieved source span (or abstract) it was checked against |
| `verdict` | `supported` · `unsupported` · `abstain` |
| `confidence` | the lens/citation confidence, when available |
| `source` | `prism-citation` or `prism-groundedness` |
| `producer_family` | the caller's model family |
| `artifact_type` | the verified artifact's type — e.g. `citations`, `code`, `tool_call` |
| `receipt_id` | the receipt this triple came from — the provenance join back to the audit trail |
| `multi_hop` | whether the triple spans multiple hops — currently always `false` (reserved) |
| `timestamp` | when it was produced |

Each record also carries its `schema` tag (`prism-l4-harvest/v1`).

The labels mirror prism's own verdict semantics, so the corpus is a faithful distillation of how
prism itself adjudicates: `supported` (accept), `unsupported` (revise/refuse), `abstain` (escalate).

## Privacy

The sink writes artifact-derived text to a **local, operator-controlled** file. A best-effort scrub
redacts a few high-signal secret shapes (API-key/token patterns — OpenAI, AWS, GitHub — bearer
tokens, PEM private keys, emails) before writing — but it is **not** a guarantee against a determined adversary. Keep the harvest file
under the same controls as the artifacts it was derived from. Harvesting is best-effort
instrumentation: it never raises into the verify path, so a write error can never change a verdict.

## The loop it closes

```
harvest verifications  →  train a groundedness model  →  serve it  →  PRISM_LOCAL_VERIFIER_ENDPOINT
```

Run prism with the sink on, collect a corpus from your own traffic, fine-tune a small groundedness
model on it, then point prism back at that model with the [local verifier](../local-verifier/). prism
becomes the source of its own training data.
