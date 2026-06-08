#!/usr/bin/env python
"""Verifier L4 dataset — Phase 2: model-generated FLUENT corruptions + cross-family verification gate.

A GENERATOR model writes a fluent claim (faithful, or with one type-guided error). A DIFFERENT-FAMILY
GATE model independently judges supported/unsupported/abstain. We keep a record only when the gate
CONFIRMS the intended label, and discard the ambiguous ones. That recovers the budgeter's
self-checkability via an external check — and it is prism's own family-different principle applied to
its training data (the generator's reasoning never reaches the judge; a different lineage judges it).

Needs ollama (local models, GPU) — run AFTER the budgeter frees the GPU. Model names below are set
from `ollama list`; pick a GENERATOR and a GATE from DIFFERENT families (e.g. qwen generates, gemma or
granite or mistral judges). Validate the gate's agreement rate on a small batch before scaling — a
generator/judge pair that disagrees too often is unreliable; swap families.
"""
import os
import json
import urllib.request

# Ollama runs on the WINDOWS host (:11434). From WSL, localhost is WSL's loopback — NOT Windows — so set
# OLLAMA_HOST=http://<windows-host-ip>:11434 (the nameserver in /etc/resolv.conf is the Windows host IP
# under WSL2), or just run this script on Windows where localhost reaches Ollama.
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/api/chat"
# Cross-family pair from `ollama list` on this rig (Qwen generates, Mistral judges — different lineages).
# Larger than the kickoff's ≤9B note, but dataset gen is one-time + quality-critical and these are
# VRAM-resident on the 32GB card (safe envelope). Run all-generate THEN all-gate to avoid per-record
# model swaps (ollama loads one at a time). Validate the pair's agreement before scaling; swap if low.
GEN_MODEL = "qwen3.6:latest"        # generator — Qwen family
GATE_MODEL = "mistral-small:24b"    # gate — Mistral family (different from the generator)
TEMP_GEN = 0.5
TEMP_GATE = 0.0

# Type-guided errors so the curriculum has coverage, not just the model's defaults.
ERROR_TYPES = ["entity", "quantifier", "relation-direction", "temporal", "attribution", "scope"]


def chat(model, system, user, temperature, timeout=180):
    # think=False: qwen3.6 (and other Qwen3/hybrid) are REASONING models — left on, a "restate this
    # fact" call burns minutes on a <think> trace and times out. These dataset-gen tasks are mechanical
    # (one sentence / one-word verdict) so reasoning is pure waste. (The TRAINED verifier still emits its
    # own <think> — that lives in the SFT targets, unaffected by this.) Strip any residual think block.
    body = json.dumps({
        "model": model, "stream": False, "think": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature},
    }).encode()
    req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        content = json.loads(r.read())["message"]["content"]
    if "</think>" in content:
        content = content.split("</think>")[-1]
    return content.strip()


def gen_supported(evidence):
    sys = ("You restate a fact as ONE fluent sentence, preserving every entity, number, date, and "
           "relation exactly. Output only the sentence, no preamble.")
    return chat(GEN_MODEL, sys, f"FACT: {evidence}\nRestate it faithfully as one fluent claim.", TEMP_GEN)


def gen_corrupted(evidence, etype):
    sys = (f"You write ONE fluent claim that paraphrases the evidence but introduces a single subtle "
           f"{etype} error, so the claim is no longer supported by the evidence. Keep it natural and "
           f"plausible — NOT an obvious negation or flip. Output only the claim, no preamble.")
    return chat(GEN_MODEL, sys, f"EVIDENCE: {evidence}\nWrite the subtly-{etype}-wrong claim.", TEMP_GEN)


def gate(evidence, claim):
    """Cross-family judge. The generator's reasoning is never shown — only (evidence, claim)."""
    sys = ("You are a strict groundedness judge. Decide whether the EVIDENCE supports the CLAIM. "
           "Reply with exactly ONE word: 'supported', 'unsupported', or 'abstain' (abstain only if the "
           "evidence does not address the claim at all).")
    out = chat(GATE_MODEL, sys, f"EVIDENCE: {evidence}\nCLAIM: {claim}", TEMP_GATE).lower()
    for v in ("unsupported", "supported", "abstain"):
        if v in out:
            return v
    return "abstain"


def make_records(evidence, agree_only=True):
    """Generate + gate one evidence sentence -> a CONTRAST GROUP (shared pair_id): the faithful claim
    (supported) + fluent corruptions (unsupported), all anchored to the SAME evidence so length/fluency
    can't predict the verdict — only the planted error does. flip-consistency = the model gets the whole
    group right. (Abstain + multi-hop + conjunct groups come from the Phase-1 builder; combine both.)"""
    import hashlib
    pid = "vp2-" + hashlib.sha1(("ev2:" + evidence).encode()).hexdigest()[:10]
    out = []
    sc = gen_supported(evidence)
    if not agree_only or gate(evidence, sc) == "supported":
        out.append({"evidence": evidence, "claim": sc, "verdict": "supported",
                    "level": 1, "type": "trace-the-claim", "corruption": "none (faithful paraphrase)",
                    "hard_negative": False, "source": "synthetic-model", "gate_confirmed": True,
                    "pair_id": pid, "contrast": False})
    for etype in ERROR_TYPES:
        cc = gen_corrupted(evidence, etype)
        v = gate(evidence, cc)
        if not agree_only or v == "unsupported":
            out.append({"evidence": evidence, "claim": cc, "verdict": v,
                        "level": 2, "type": "plausible-but-unsupported", "corruption": f"{etype} error",
                        "hard_negative": True, "source": "synthetic-model", "gate_confirmed": v == "unsupported",
                        "pair_id": pid, "contrast": True})
    return out


def validate_pair(evidence_samples, n=8):
    """Before scaling: measure the gate's agreement with generator intent on a small batch.
    High supported-agreement AND high unsupported-agreement => the generator/gate pair is usable."""
    sup_ok = corr_ok = sup_n = corr_n = 0
    for ev in evidence_samples[:n]:
        sup_n += 1
        if gate(ev, gen_supported(ev)) == "supported":
            sup_ok += 1
        for et in ERROR_TYPES[:2]:
            corr_n += 1
            if gate(ev, gen_corrupted(ev, et)) == "unsupported":
                corr_ok += 1
    print(f"gate agreement — supported {sup_ok}/{sup_n}, corrupted {corr_ok}/{corr_n} "
          f"(generator={GEN_MODEL}, gate={GATE_MODEL})")


if __name__ == "__main__":
    # smoke: validate the generator/gate pair on a couple of evidence sentences (run post-budgeter).
    SAMPLES = [
        "Galileo was absorbed into Cisco and Splunk on 2026-05-22.",
        "Prism runs at least three lenses in parallel and ships four in v1.",
    ]
    validate_pair(SAMPLES, n=2)
    print(json.dumps(make_records(SAMPLES[0]), ensure_ascii=False, indent=2))
