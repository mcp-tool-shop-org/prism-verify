#!/usr/bin/env python
"""Verifier (L4 Groundedness) certification scorer — the budgeter's certify.py adapted to the
groundedness verdict {supported|unsupported|abstain}. Queries a SERVED adapter on the held-out,
group-atomic exam; scores per-rung accuracy + FLIP-CONSISTENCY (the truth metric: whole contrast group
right) + bootstrap 95% CIs, and the COST-ASYMMETRIC safety metric: a false "supported" (gold is
unsupported/abstain, model said supported = shipped a hallucination) is weighted COST_FP_OVER_FN (5)×
worse than any other error. A rung is earned when accuracy clears the bar with non-overlapping CIs
across BOTH seeds AND the dangerous-error rate is low AND lower rungs don't regress. Stdlib only.

Usage: python certify_verifier.py --endpoint http://127.0.0.1:8091 --exam verifier_exam_records.jsonl
                                  --label soup [--out f.json]
"""
import argparse, collections, json, re, random, urllib.request, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config

SYS = config.SYSTEM_PROMPT
COST_FP = config.COST_FP_OVER_FN  # a false "supported" is this many times worse


def query(endpoint, evidence, claim, timeout=120):
    user = f"EVIDENCE:\n{evidence}\n\nCLAIM:\n{claim}"
    body = json.dumps({"messages": [{"role": "system", "content": SYS},
                                    {"role": "user", "content": user}],
                       "max_tokens": 320, "temperature": 0.1}).encode()
    req = urllib.request.Request(endpoint + "/v1/chat/completions", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def parse_verdict(text):
    if "</think>" in text:
        text = text.split("</think>")[-1]
    t = text.lower()
    # ORDER MATTERS: 'unsupported' contains 'supported'; never let a hallucination read as supported.
    if "unsupported" in t:
        return "unsupported"
    if "abstain" in t:
        return "abstain"
    if "supported" in t:
        return "supported"
    return "abstain"   # safe default — never default to the dangerous verdict


def bootstrap_ci(hits, n_iter=2000):
    n = len(hits)
    if n == 0:
        return (0.0, 0.0, 0.0)
    acc = sum(hits) / n
    rng = random.Random(0)
    samp = sorted(sum(hits[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_iter))
    return (acc, samp[int(0.025 * n_iter)], samp[int(0.975 * n_iter)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    recs = [json.loads(l) for l in open(a.exam, encoding="utf-8") if l.strip()]
    by_level = collections.defaultdict(list)
    groups = collections.defaultdict(list)
    group_level = {}
    dangerous = collections.defaultdict(int)   # per-level false-"supported" count
    danger_n = collections.defaultdict(int)     # per-level count of gold != supported (the at-risk denom)
    errors = 0
    for i, p in enumerate(recs):
        gold = p["verdict"]
        try:
            pred = parse_verdict(query(a.endpoint, p["evidence"], p["claim"]))
        except Exception:
            pred, errors = "abstain", errors + 1
        ok = pred == gold
        lvl = p["level"]
        by_level[lvl].append(1 if ok else 0)
        if p.get("pair_id"):
            groups[p["pair_id"]].append(1 if ok else 0)
            group_level[p["pair_id"]] = lvl
        if gold != "supported":
            danger_n[lvl] += 1
            if pred == "supported":
                dangerous[lvl] += 1          # shipped a hallucination as grounded — the costly error
        if (i + 1) % 25 == 0:
            print(f"  [{a.label}] {i+1}/{len(recs)} scored", flush=True)

    res = {"label": a.label, "n": len(recs), "query_errors": errors, "cost_fp_over_fn": COST_FP, "rungs": {}}
    tot_weighted_err = tot_weight = 0.0
    for lvl in sorted(by_level):
        hits = by_level[lvl]
        acc, lo, hi = bootstrap_ci(hits)
        glist = [g for pid, g in groups.items() if group_level[pid] == lvl]
        flip = round(sum(1 for g in glist if all(g)) / len(glist), 3) if glist else None
        dfp = dangerous[lvl]
        res["rungs"][str(lvl)] = {
            "n": len(hits), "acc": round(acc, 3), "ci95": [round(lo, 3), round(hi, 3)],
            "flip_consistency": flip,
            "false_supported": dfp, "at_risk": danger_n[lvl],
            "false_supported_rate": round(dfp / danger_n[lvl], 3) if danger_n[lvl] else 0.0,
        }
    # cost-weighted error: each false-supported counts COST_FP, every other error counts 1
    all_hits = [h for hs in by_level.values() for h in hs]
    n_all = len(all_hits) or 1
    n_err = n_all - sum(all_hits)
    n_fp = sum(dangerous.values())
    weighted_err = (n_fp * COST_FP + (n_err - n_fp) * 1) / (n_all + n_fp * (COST_FP - 1) or 1)
    res["overall"] = round(sum(all_hits) / n_all, 3)
    res["flip_consistency_overall"] = (round(sum(1 for g in groups.values() if all(g)) / len(groups), 3)
                                       if groups else 0.0)
    res["false_supported_total"] = n_fp
    res["false_supported_rate_overall"] = round(n_fp / sum(danger_n.values()), 3) if sum(danger_n.values()) else 0.0
    res["cost_weighted_error"] = round(weighted_err, 4)
    print(json.dumps(res, indent=2))
    if a.out:
        json.dump(res, open(a.out, "w"), indent=2)


if __name__ == "__main__":
    main()
