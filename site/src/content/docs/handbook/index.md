---
title: prism-verify Handbook
description: Runtime LLM verifier — family-different, reasoning-stripped, multi-lens, with signed Ed25519 receipts.
sidebar:
  order: 0
---

**prism** is a runtime verifier for agent workflows. It adjudicates an artifact — code, a
tool-call, or a set of citations — against a stated intent, and returns one of four verdicts:
`accept`, `revise`, `refuse`, or `escalate`, alongside a signed, replayable receipt.

The point of prism is that its verdict is **trustworthy in a way a self-check is not**. A model
asked to grade its own output tends to pass it. prism removes that failure mode at the API
contract, with four locks:

## The four locks

1. **Family-different.** The caller declares its model family; prism selects a verifier from a
   *different* family by construction. There is no silent same-family fallback — if every
   alternate-family route is unavailable, prism refuses with `VERIFIER_UNAVAILABLE` rather than
   grade with the caller's own family.
2. **Reasoning-stripped.** The producer's chain-of-thought, `<thinking>` blocks, and vendor
   reasoning summaries are stripped from the artifact before it crosses the family boundary. A
   manipulated trace is a known way to inflate a judge's confidence; prism never shows it to the
   verifier, and re-parses the stripped artifact to confirm nothing survived.
3. **Multi-lens, submodularity-aware.** At least three decorrelated lenses run in parallel
   (contract-completeness, cross-boundary information-flow, invariant/test-adequacy,
   groundedness). If the lenses agree *too much* — collapsing to one redundant signal — prism
   refuses with `LENS_COLLAPSE`, because a "multi-lens" claim that's really one lens is fraudulent.
4. **Independently-verifiable receipts.** Every verdict emits a replayable receipt. As of v0.4
   receipts are signed with **Ed25519**, so a *different tool* can verify a prism receipt with
   prism's **public key — no shared secret**.

## Surfaces

The same engine is exposed three ways, with identical guarantees:

- **CLI** — `prism verify` / `replay` / `verify-receipt` / `keygen` / `pubkey` / `serve`.
- **MCP server** — `verify` + `replay` tools for an MCP host.
- **HTTP service** — `prism serve` exposes `POST /verify`, `GET /replay/{id}`,
  `POST /verify-receipt`, `GET /healthz`, and OpenAPI docs.

Start with [Getting started](../getting-started/), then the
[HTTP service](../http-service/), [Receipts &amp; signing](../receipts/), or the full
[Reference](../reference/). To run the citation check against a model you host, see the
[self-hosted groundedness verifier](../local-verifier/).
