#!/usr/bin/env python
"""Phase-2 scale generation: model-gen FLUENT corruptions + cross-family gate over the corpus evidence.

The PRIMARY data (fluent corruptions are primary; deterministic corrupt.py is a seed only). For each
evidence: a faithful paraphrase (intended supported) + one corruption per error-type (intended
unsupported), all anchored to the SAME evidence -> an evidence-anchored CONTRAST GROUP (shared pair_id)
so length/fluency cannot predict the verdict, only the planted error. A DIFFERENT-FAMILY gate
(mistral-small) confirms each; only gate-confirmed records are kept (the external-verifier discipline —
kept records are correct by construction; the cost is YIELD, not quality).

Design:
  * all-GENERATE then all-GATE -> exactly 2 Ollama model loads (no per-record swap thrash).
  * resumable + checkpointed: gen_phase2.jsonl (candidates), gated_phase2.jsonl (+verdict),
    phase2_records.jsonl (confirmed, grouped, in puzzles._rec schema). Re-run resumes from checkpoints.
  * self-validating: the gate phase prints running per-error-type confirm rates (the gate validation
    at full scale) so a broken gate shows up early.

Run on the WINDOWS host (Ollama localhost:11434):  python gen_phase2.py [gen|gate|assemble|all]
"""
import os, sys, json, hashlib, time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import synth, config, puzzles as P

EV = json.load(open(os.path.join(HERE, "corpus_evidence.json"), encoding="utf-8"))
# Which corruption types to generate per evidence (env override lets us drop weak-yield types like
# quantifier/scope after the gate validation — they mostly get discarded anyway, so skipping them
# saves generation time without hurting the kept dataset). Default = all 6 from synth.
GEN_TYPES = [t.strip() for t in os.environ.get("GEN_TYPES", ",".join(synth.ERROR_TYPES)).split(",") if t.strip()]
GEN_F = os.path.join(HERE, "gen_phase2.jsonl")
GATE_F = os.path.join(HERE, "gated_phase2.jsonl")
OUT_F = os.path.join(HERE, "phase2_records.jsonl")


def pid_for(ev):
    return "vp2-" + hashlib.sha1(("ev2:" + ev).encode()).hexdigest()[:10]


def _reason_sup():
    return "The claim restates the evidence faithfully; every load-bearing part traces to it."


def _reason_unsup(etype):
    return (f"The claim reads fluently but introduces a subtle {etype} error the evidence never "
            f"states; the surrounding match is the red herring — partial match is not support.")


def phase_gen():
    done = set()
    if os.path.exists(GEN_F):
        for l in open(GEN_F, encoding="utf-8"):
            if l.strip():
                r = json.loads(l); done.add((r["idx"], r["role"], r.get("etype")))
    t0 = time.time()
    with open(GEN_F, "a", encoding="utf-8") as f:
        for idx, ev in enumerate(EV):
            if (idx, "sup", None) not in done:
                try:
                    c = synth.gen_supported(ev)
                    f.write(json.dumps({"idx": idx, "ev": ev, "role": "sup", "etype": None,
                                        "claim": c}, ensure_ascii=False) + "\n"); f.flush()
                except Exception as e:
                    print(f"[gen-err sup {idx}] {e}", flush=True)
            for et in GEN_TYPES:
                if (idx, "corrupt", et) in done:
                    continue
                try:
                    c = synth.gen_corrupted(ev, et)
                    f.write(json.dumps({"idx": idx, "ev": ev, "role": "corrupt", "etype": et,
                                        "claim": c}, ensure_ascii=False) + "\n"); f.flush()
                except Exception as e:
                    print(f"[gen-err {et} {idx}] {e}", flush=True)
            if (idx + 1) % 10 == 0:
                print(f"[gen] {idx+1}/{len(EV)} evidence  ({time.time()-t0:.0f}s)", flush=True)
    print(f"[gen] DONE {len(EV)} evidence ({time.time()-t0:.0f}s)", flush=True)


def phase_gate():
    cands = [json.loads(l) for l in open(GEN_F, encoding="utf-8") if l.strip()]
    done = 0
    if os.path.exists(GATE_F):
        done = sum(1 for l in open(GATE_F, encoding="utf-8") if l.strip())
    print(f"[gate] {len(cands)} candidates, resuming at {done}", flush=True)
    t0 = time.time()
    per = defaultdict(lambda: {"keep": 0, "n": 0})       # running per-type confirm
    sup = {"ok": 0, "n": 0}
    if done:                                              # re-tally what's already gated for live stats
        for l in open(GATE_F, encoding="utf-8"):
            if not l.strip():
                continue
            c = json.loads(l)
            if c["role"] == "sup":
                sup["n"] += 1; sup["ok"] += c["verdict"] == "supported"
            else:
                d = per[c["etype"]]; d["n"] += 1; d["keep"] += c["verdict"] == "unsupported"
    with open(GATE_F, "a", encoding="utf-8") as f:
        for j, c in enumerate(cands):
            if j < done:
                continue
            try:
                v = synth.gate(c["ev"], c["claim"])
            except Exception as e:
                v = f"ERR:{e}"
            c["verdict"] = v
            f.write(json.dumps(c, ensure_ascii=False) + "\n"); f.flush()
            if c["role"] == "sup":
                sup["n"] += 1; sup["ok"] += v == "supported"
            else:
                d = per[c["etype"]]; d["n"] += 1; d["keep"] += v == "unsupported"
            if (j + 1) % 25 == 0:
                rates = " ".join(f"{et[:4]}={per[et]['keep']}/{per[et]['n']}" for et in synth.ERROR_TYPES)
                print(f"[gate] {j+1}/{len(cands)} ({time.time()-t0:.0f}s)  sup={sup['ok']}/{sup['n']}  {rates}",
                      flush=True)
    print(f"[gate] DONE  sup-confirm={sup['ok']}/{sup['n']}", flush=True)
    for et in synth.ERROR_TYPES:
        d = per[et]
        print(f"  {et:20s} unsup-confirm {d['keep']}/{d['n']} = {d['keep']/max(d['n'],1):.2f}", flush=True)


def phase_assemble():
    gated = [json.loads(l) for l in open(GATE_F, encoding="utf-8") if l.strip()]
    by_ev = defaultdict(lambda: {"sup": None, "corrupt": []})
    for c in gated:
        if c["role"] == "sup" and c.get("verdict") == "supported":
            by_ev[c["idx"]]["sup"] = c
        elif c["role"] == "corrupt" and c.get("verdict") == "unsupported":
            by_ev[c["idx"]]["corrupt"].append(c)
    recs = []
    for idx, d in by_ev.items():
        ev = EV[idx]; pid = pid_for(ev)
        if d["sup"]:
            recs.append(P._rec(1, "trace-the-claim", ev, d["sup"]["claim"], "supported", _reason_sup(),
                               pair_id=pid, contrast=False, corruption="none (faithful paraphrase)",
                               hard_negative=False, source="synthetic-model"))
        for c in d["corrupt"]:
            recs.append(P._rec(2, "plausible-but-unsupported", ev, c["claim"], "unsupported",
                               _reason_unsup(c["etype"]), pair_id=pid, contrast=True,
                               corruption=f"{c['etype']} error", hard_negative=True,
                               source="synthetic-model"))
    with open(OUT_F, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    sup = sum(1 for r in recs if r["verdict"] == "supported")
    uns = sum(1 for r in recs if r["verdict"] == "unsupported")
    groups = len({r["pair_id"] for r in recs})
    print(f"[assemble] {len(recs)} confirmed records ({sup} supported / {uns} unsupported) "
          f"in {groups} evidence groups -> {OUT_F}", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("gen", "all"):
        phase_gen()
    if mode in ("gate", "all"):
        phase_gate()
    if mode in ("assemble", "all"):
        phase_assemble()
