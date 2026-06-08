#!/usr/bin/env python
"""Cross-family gate validation AT SCALE (n>=20) with PER-ERROR-TYPE agreement rates.

Extends synth.validate_pair (which only sampled n=2 and 2 error types). This:
  * all-GENERATE then all-GATE  -> exactly 2 Ollama model loads, no per-call thrash
  * reports supported-agreement + per-error-type unsupported-confirm rates (the real yield)
  * also reports WHERE non-confirmed records went (gate said 'supported' = false-confirm risk /
    weak corruption;  gate said 'abstain' = just discarded) so we can read quality vs yield
  * persists every generated+gated record -> gate_validation_records.json (a validated run seeds
    the real dataset; nothing is wasted)

Run on the WINDOWS host (Ollama at localhost:11434). Swap families with env:
  GEN_MODEL=qwen3.6:latest GATE_MODEL=granite4.1:30b python validate_gate.py
"""
import os, sys, json, time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth

# allow a gate/generator family swap via env WITHOUT editing synth.py (the budgeter rule:
# validate the pair, swap the family if agreement is low — esp. for quantifier/scope).
synth.GEN_MODEL = os.environ.get("GEN_MODEL", synth.GEN_MODEL)
synth.GATE_MODEL = os.environ.get("GATE_MODEL", synth.GATE_MODEL)

# 24 INVENTED + studio atomic facts (NOT real-world: forces the gate to READ the evidence rather
# than lean on priors — the same reason the budgeter used computable token-economics). Each is
# feature-rich for the 6 error types (entities / quantifiers / relation-direction / temporal /
# attribution / scope) so per-type rates are meaningful.
EVIDENCE = [
    "The Meridian Foundry shipped 1,284 units to the Calderon depot in March.",
    "Velora Systems was acquired by Thorne Industrial on 2027-03-14.",
    "At least sixty percent of Halcyon's revenue comes from enterprise contracts.",
    "Dr. Pell reported that the Aster reactor reached eighty percent efficiency.",
    "The Northwind ferry departs Saltmarsh at 06:40 every weekday.",
    "Only the Tessery division is authorized to sign vendor agreements.",
    "Kestrel Labs raised 52 million dollars in its Series B round.",
    "The Orrin Bridge connects the eastern terminal to the freight yard.",
    "According to the Vance audit, the ledger contained three duplicate entries.",
    "The Sable engine outputs 410 kilowatts at peak load.",
    "Marlowe Freight operates exclusively within the southern corridor.",
    "The Calder treaty was signed before the Henwick accord.",
    "Quill Press published the Aldermere atlas in 2029.",
    "Every courier on the Vesper route carries a sealed manifest.",
    "The data flows from the Brunel sensor into the central aggregator.",
    "Captain Reyes commands the survey vessel Lumen.",
    "The Pell grant funds at most four research fellows per year.",
    "Tannor Mills acquired its rival Greycastle in late 2028.",
    "The eastern spillway releases water only during the monsoon months.",
    "Analyst Howe attributed the outage to a faulty relay in sector nine.",
    "The Ardent's cargo bay holds up to twelve standard containers.",
    "Role OS defines sixty-one roles across ten team packs.",
    "Motif exports a runtime pack for the engine after the cue families are mapped.",
    "Prism runs at least three lenses in parallel and ships four in v1.",
]


def main():
    t0 = time.time()
    gen = []  # {ev, etype|None, claim, intended}
    print(f"[gen] generating with {synth.GEN_MODEL} over {len(EVIDENCE)} evidence ...", flush=True)
    for i, ev in enumerate(EVIDENCE):
        try:
            sc = synth.gen_supported(ev)
            gen.append({"ev": ev, "etype": None, "claim": sc, "intended": "supported"})
        except Exception as e:
            print(f"  [gen-err sup {i}] {e}", flush=True)
        for et in synth.ERROR_TYPES:
            try:
                cc = synth.gen_corrupted(ev, et)
                gen.append({"ev": ev, "etype": et, "claim": cc, "intended": "unsupported"})
            except Exception as e:
                print(f"  [gen-err {et} {i}] {e}", flush=True)
        print(f"  [gen] {i+1}/{len(EVIDENCE)}  ({time.time()-t0:.0f}s)", flush=True)

    print(f"[gate] judging {len(gen)} claims with {synth.GATE_MODEL} ...", flush=True)
    for j, g in enumerate(gen):
        try:
            g["gate"] = synth.gate(g["ev"], g["claim"])
        except Exception as e:
            g["gate"] = f"ERR:{e}"
        if (j + 1) % 25 == 0:
            print(f"  [gate] {j+1}/{len(gen)}  ({time.time()-t0:.0f}s)", flush=True)

    # ---- tally ----
    sup = [g for g in gen if g["etype"] is None]
    sup_ok = sum(1 for g in sup if g["gate"] == "supported")
    sup_over = sum(1 for g in sup if g["gate"] == "unsupported")   # gate too strict -> discards good sup
    sup_abst = sum(1 for g in sup if g["gate"] == "abstain")

    per = defaultdict(lambda: {"unsup": 0, "sup": 0, "abst": 0, "n": 0})
    for g in gen:
        if g["etype"]:
            d = per[g["etype"]]; d["n"] += 1
            v = g["gate"]
            if v == "unsupported": d["unsup"] += 1
            elif v == "supported": d["sup"] += 1
            elif v == "abstain": d["abst"] += 1

    lines = []
    lines.append("\n========== CROSS-FAMILY GATE VALIDATION ==========")
    lines.append(f"generator = {synth.GEN_MODEL}")
    lines.append(f"gate      = {synth.GATE_MODEL}")
    lines.append(f"evidence  = {len(EVIDENCE)}   total generated = {len(gen)}   "
                 f"elapsed = {time.time()-t0:.0f}s")
    lines.append("")
    lines.append(f"SUPPORTED-agreement (gate confirms faithful claim is 'supported'):")
    lines.append(f"  confirmed   {sup_ok}/{len(sup)} = {sup_ok/max(len(sup),1):.2f}   <- yield of L1 sup records")
    lines.append(f"  over-strict {sup_over}/{len(sup)} = {sup_over/max(len(sup),1):.2f}   (gate called a faithful "
                 f"claim UNSUPPORTED -> discarded; high = bad gate)")
    lines.append(f"  abstain     {sup_abst}/{len(sup)} = {sup_abst/max(len(sup),1):.2f}")
    lines.append("")
    lines.append("CORRUPTED per error-type (gate confirms 'unsupported' = kept; else discarded):")
    lines.append(f"  {'type':22s} {'confirm%':>9s} {'unsup':>6s} {'supported':>10s} {'abstain':>8s}  (n)")
    for et in synth.ERROR_TYPES:
        d = per[et]; n = max(d["n"], 1)
        lines.append(f"  {et:22s} {d['unsup']/n:>9.2f} {d['unsup']:>6d} {d['sup']:>10d} {d['abst']:>8d}  ({d['n']})")
    tot_corr = sum(d["n"] for d in per.values())
    tot_keep = sum(d["unsup"] for d in per.values())
    tot_false = sum(d["sup"] for d in per.values())   # gate called a corruption 'supported' = weak corruption
    lines.append("")
    lines.append(f"OVERALL corruption keep-rate: {tot_keep}/{tot_corr} = {tot_keep/max(tot_corr,1):.2f}  "
                 f"(generation multiplier ~= {tot_corr/max(tot_keep,1):.2f}x to hit a target count)")
    lines.append(f"gate-called-'supported' corruptions: {tot_false}/{tot_corr} = {tot_false/max(tot_corr,1):.2f}  "
                 f"(weak/failed corruptions, safely discarded)")
    lines.append("")
    lines.append("VERDICT: usable if SUPPORTED-confirm is high (>~0.85), over-strict is low (<~0.15),")
    lines.append("and most error types keep at a workable rate (down-weight or swap-gate the weak ones).")
    report = "\n".join(lines)
    print(report, flush=True)

    here = os.path.dirname(os.path.abspath(__file__))
    json.dump({"generator": synth.GEN_MODEL, "gate": synth.GATE_MODEL,
               "records": gen,
               "supported": {"confirmed": sup_ok, "over_strict": sup_over, "abstain": sup_abst, "n": len(sup)},
               "per_error_type": {k: dict(v) for k, v in per.items()}},
              open(os.path.join(here, "gate_validation_records.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    with open(os.path.join(here, "gate_validation_report.txt"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print("\n[persisted] gate_validation_records.json + gate_validation_report.txt", flush=True)


if __name__ == "__main__":
    main()
