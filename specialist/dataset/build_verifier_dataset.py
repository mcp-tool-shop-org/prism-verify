#!/usr/bin/env python
"""Assemble the full Verifier L4 SFT from Phase-2 (model-gen fluent, primary) + Phase-1 structured
groups (claim/conjunct/hop, from the authored corpus), balance, group-atomic split, emit train SFT +
held-out exam, and run the HARD-GATE audit. Cheap + re-runnable (no GPU) — tune balance by re-running.

Inputs (same dir):
  phase2_records.jsonl   gen_phase2.py output: evidence-anchored L1 supported + L2 unsupported groups
  corpus_triples.json    [{claim, ev_support, ev_silent}]   -> claim_group  (L1 sup / L2 contra / L5 abstain)
  corpus_conjuncts.json  [{ev1, traceable_2nd, untraceable_2nd}] -> conjunct_group (L3 sup / L3 unsup)
  corpus_hops.json       [{ev1, ev2, bridge_claim}]         -> hop_group     (L4 sup / L4 abstain)

Outputs:
  verifier_records.jsonl       ALL records (id, split, pair_id, ...)
  verifier_train_sft.jsonl     train split as OpenAI-messages SFT  (point BUDGETER_DATA here for V-B)
  verifier_exam_records.jsonl  exam split records (for V-C certification)

Knobs (env): BUILD_CAP_P2_UNSUP (default 1 = clean 1-sup-1-unsup evidence pairs, best balance),
             BUILD_EXAM_FRAC (default 0.25).
Run: python build_verifier_dataset.py
"""
import os, sys, json, hashlib
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config
import puzzles as P
import audit as A
import synth   # for ERROR_TYPES rotation

CAP = int(os.environ.get("BUILD_CAP_P2_UNSUP", "1"))
EXAM_FRAC = float(os.environ.get("BUILD_EXAM_FRAC", "0.25"))


def _pid(tag, anchor, i):
    return "v-" + hashlib.sha1(f"{tag}:{i}:{anchor}".encode()).hexdigest()[:10]


def load_json(name, default):
    p = os.path.join(HERE, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def build_phase1():
    recs = []
    for i, t in enumerate(load_json("corpus_triples.json", [])):
        g = P.claim_group(t["claim"], t["ev_support"], t["ev_silent"], _pid("cl", t["claim"], i))
        if g:
            recs += g
    for i, c in enumerate(load_json("corpus_conjuncts.json", [])):
        recs += P.conjunct_group(c["ev1"], c["traceable_2nd"], c["untraceable_2nd"], _pid("cj", c["ev1"], i))
    for i, h in enumerate(load_json("corpus_hops.json", [])):
        recs += P.hop_group(h["ev1"], h["ev2"], h["bridge_claim"], _pid("hp", h["bridge_claim"], i))
    for i, v in enumerate(load_json("corpus_voice.json", [])):
        recs += P.voice_group(v["subj"], v["verb_active"], v["verb_passive"], v["obj"],
                              _pid("vc", v["obj"], i))
    return recs


def load_phase2_capped():
    p = os.path.join(HERE, "phase2_records.jsonl")
    if not os.path.exists(p):
        return []
    recs = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    groups = defaultdict(list)
    for r in recs:
        groups[r["pair_id"]].append(r)
    out = []
    for gi, (pid_, members) in enumerate(sorted(groups.items())):
        sup = [m for m in members if m["verdict"] == "supported"]
        cor = [m for m in members if m["verdict"] == "unsupported"]
        if not sup or not cor:
            continue                                  # need both verdicts -> a flip-ready pair
        out.append(sup[0])
        # rotate the kept corruption's error-type across groups so L2 sees all 6 types
        want = synth.ERROR_TYPES[gi % len(synth.ERROR_TYPES)]
        cor_sorted = sorted(cor, key=lambda m: 0 if want in (m.get("corruption") or "") else 1)
        out += cor_sorted[:CAP]
    return out


def split_group_atomic(recs):
    for p in recs:
        h = int(hashlib.sha1(p["pair_id"].encode()).hexdigest()[:8], 16)
        p["split"] = "exam" if (h % 100) < int(EXAM_FRAC * 100) else "train"
    return recs


def main():
    p1 = build_phase1()
    p2 = load_phase2_capped()
    recs = p1 + p2
    for i, p in enumerate(recs):
        p["id"] = f"v-{p['level']}-{i:05d}"
    split_group_atomic(recs)

    # write all records + train SFT + exam records
    with open(os.path.join(HERE, "verifier_records.jsonl"), "w", encoding="utf-8") as f:
        for p in recs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    train = [P.to_sft(p) for p in recs if p["split"] == "train"]
    with open(os.path.join(HERE, "verifier_train_sft.jsonl"), "w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    exam = [p for p in recs if p["split"] == "exam"]
    with open(os.path.join(HERE, "verifier_exam_records.jsonl"), "w", encoding="utf-8") as f:
        for p in exam:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # report
    print(f"phase1={len(p1)}  phase2(capped@{CAP})={len(p2)}  total={len(recs)}  "
          f"train_sft={len(train)}  exam={len(exam)}")
    lvl = Counter(p["level"] for p in recs)
    src = Counter(p.get("source", "?") for p in recs)
    print("level dist : " + ", ".join(f"L{k}={lvl[k]}" for k in sorted(lvl)))
    print("source dist: " + ", ".join(f"{k}={v}" for k, v in src.items()))
    tr_lvl = Counter(p["level"] for p in recs if p["split"] == "train")
    ex_lvl = Counter(p["level"] for p in recs if p["split"] == "exam")
    print("train levels: " + ", ".join(f"L{k}={tr_lvl[k]}" for k in sorted(tr_lvl)))
    print("exam  levels: " + ", ".join(f"L{k}={ex_lvl[k]}" for k in sorted(ex_lvl)))
    print("\n===== AUDIT (hard gate) =====")
    ok = A.audit(recs)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
