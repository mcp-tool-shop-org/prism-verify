"""Phase-1 builder + audit: contrast-grouped groundedness puzzles from real studio facts. Model-free,
runs WITHOUT the GPU. Proves the contrast structure is flip-ready, split-integral, and leak-free before
the Phase-2 model-gen scale-up. Writes train SFT + all records, then runs the hard-gate audit.
Run:  python build_demo.py
"""
import json, hashlib
import puzzles as P
import audit as A

# evidence-anchored groups: each fact -> faithful (supported) + one-swap twin (unsupported)
EVIDENCE = [
    "The TCS Ardent departed Freeport with a crew of forty-three.",
    "Patronus AI has raised approximately 40 million dollars.",
    "Gemini 2.5 Pro is pinned to the GA SKU, never preview.",
    "Galileo was absorbed into Cisco on 2026-05-22.",
    "Prism ships four lenses in v1.",
]
# claim-anchored triples: (claim, supporting evidence, silent filler) -> supported/unsupported/abstain
# (support evidence carries an aux verb so a contradicting twin can be planted)
CLAIM_TRIPLES = [
    ("Stillpoint runs entirely offline with no network calls.",
     "Stillpoint runs entirely offline with no network calls.",
     "The quarterly all-hands is scheduled for the second Tuesday."),
    ("Role OS is licensed under the MIT license.",
     "Role OS is licensed under the MIT license.",
     "Maple syrup grades are sorted by translucency, not sweetness."),
    ("The Ardent has a backup fusion core.",
     "The Ardent has a backup fusion core.",
     "The north warehouse was repainted last spring."),
    ("Motif ships sixteen cue families.",
     "Motif ships sixteen cue families.",
     "Office plants are watered every third day."),
]
# conjunct groups (L3): (ev1, traceable 2nd sentence, untraceable 2nd clause)
CONJUNCTS = [
    ("Motif scores games with adaptive cue families.",
     "Motif exports a runtime pack for the engine.",
     "it was the best-selling audio tool of the year"),
]
# hop groups (L4): (ev1, ev2, bridge claim true only via both)
HOPS = [
    ("Role OS defines sixty-one roles.", "Each role can join one of ten team packs.",
     "Role OS roles can be organized into team packs."),
    ("Sprite Foundry renders the sprite sheets.", "The sheets feed directly into the Godot importer.",
     "Sprite Foundry output feeds the Godot importer."),
]


def _pid(tag, anchor):
    return "vp-" + hashlib.sha1((tag + ":" + anchor).encode()).hexdigest()[:10]


def build():
    out = []
    for ev in EVIDENCE:
        g = P.evidence_group(ev, _pid("ev", ev))
        if g:
            out.extend(g)
    for claim, es, esil in CLAIM_TRIPLES:
        out.extend(P.claim_group(claim, es, esil, _pid("cl", claim)))
    for ev, t, u in CONJUNCTS:
        out.extend(P.conjunct_group(ev, t, u, _pid("cj", ev)))
    for e1, e2, bc in HOPS:
        out.extend(P.hop_group(e1, e2, bc, _pid("hp", bc)))
    for i, p in enumerate(out):
        p["id"] = f"vz-{p['level']}-{i:04d}"
    return out


def split_group_atomic(recs, exam_frac=0.25):
    """Group-atomic: a whole contrast group -> one split (deterministic by pair_id hash). Members stay
    together so a group never leaks its own flipped answer across the split."""
    for p in recs:
        h = int(hashlib.sha1(p["pair_id"].encode()).hexdigest()[:8], 16)
        p["split"] = "exam" if (h % 100) < int(exam_frac * 100) else "train"
    return recs


if __name__ == "__main__":
    import sys
    from collections import defaultdict
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    recs = split_group_atomic(build())
    train = [P.to_sft(p) for p in recs if p["split"] == "train"]
    with open("demo_train_sft.jsonl", "w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open("demo_records.jsonl", "w", encoding="utf-8") as f:
        for p in recs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"built {len(recs)} records ({len(train)} train SFT) -> demo_train_sft.jsonl\n")
    A.audit(recs)
    print("\n--- one of each contrast group type ---")
    groups = defaultdict(list)
    for p in recs:
        groups[p["pair_id"]].append(p)
    shown = set()
    for g in groups.values():
        key = tuple(sorted({m["verdict"] for m in g}))
        if key in shown:
            continue
        shown.add(key)
        print(f"  group {g[0]['pair_id']}:")
        for m in g:
            print(f"    [L{m['level']} {m['verdict']:11s}] {m['claim'][:64]}")
