#!/usr/bin/env python
"""Surface a handful of contrast groups per rung for the director eyeball (principle-correctness).
Shows the flip structure (surface-near, verdict-different) so the gold-by-construction is checkable."""
import os, json
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
recs = [json.loads(l) for l in open(os.path.join(HERE, "verifier_records.jsonl"), encoding="utf-8") if l.strip()]
groups = defaultdict(list)
for r in recs:
    groups[r["pair_id"]].append(r)


def show(title, g):
    print(f"\n  [{title}]")
    for m in sorted(g, key=lambda x: x["level"]):
        ev = m["evidence"] if len(m["evidence"]) <= 150 else m["evidence"][:147] + "..."
        cl = m["claim"] if len(m["claim"]) <= 150 else m["claim"][:147] + "..."
        print(f"    L{m['level']} {m['verdict'].upper():11s}  corruption={m['corruption']}")
        print(f"        EVIDENCE: {ev}")
        print(f"        CLAIM   : {cl}")


# 1) Evidence-anchored FLUENT groups (Phase-2): faithful supported vs model-gen subtle corruption.
#    Pick one per distinct corruption type to show the range of L2 traps.
ev_anchored = [g for g in groups.values()
               if any(m.get("source") == "synthetic-model" for m in g)]
print("=" * 90)
print("RUNGS L1 + L2 — EVIDENCE-ANCHORED FLUENT (model-generated, gate-confirmed) — the primary data")
print("  same evidence; faithful claim = supported, one planted error = unsupported (flip pair)")
print("=" * 90)
seen_types = set()
shown = 0
for g in ev_anchored:
    l2 = [m for m in g if m["level"] == 2]
    if not l2:
        continue
    ctype = l2[0]["corruption"]
    if ctype in seen_types:
        continue
    seen_types.add(ctype)
    # show the supported + just this one L2 twin
    sup = [m for m in g if m["level"] == 1]
    show(f"corruption: {ctype}", sup[:1] + l2[:1])
    shown += 1
    if shown >= 6:
        break

# 2) claim-anchored triples (L1/L2/L5): same claim, varied evidence -> supported / unsupported / abstain
claim_groups = [g for g in groups.values()
                if {m["level"] for m in g} & {5} and any(m["level"] == 1 for m in g)]
print("\n" + "=" * 90)
print("RUNGS L1/L2/L5 — CLAIM-ANCHORED (same claim, varied evidence) — strongest anti-shortcut + L5 abstain")
print("=" * 90)
for g in claim_groups[:2]:
    show("claim-anchored triple", g)

# 3) conjunct (L3): both conjuncts trace = supported; one absent = unsupported
conj = [g for g in groups.values() if all(m["level"] == 3 for m in g) and len(g) >= 2]
print("\n" + "=" * 90)
print("RUNG L3 — CONJUNCT (compound claim; every conjunct must trace)")
print("=" * 90)
for g in conj[:2]:
    show("conjunct pair", g)

# 4) hop (L4): both hops present = supported; one hop removed = abstain (silent, not contradicted)
hop = [g for g in groups.values() if all(m["level"] == 4 for m in g) and len(g) >= 2]
print("\n" + "=" * 90)
print("RUNG L4 — MULTI-HOP (true only via two spans; remove a hop -> silent -> abstain)")
print("=" * 90)
for g in hop[:2]:
    show("hop pair", g)
