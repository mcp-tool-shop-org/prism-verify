#!/usr/bin/env python
"""Ingest the build-verifier-corpus workflow result -> 4 clean corpus JSON files for the dataset build.
Reads the workflow's task-output file (a JSON object {evidence, triples, conjuncts, hops, stats}),
html-unescapes all strings (the workflow JSON encoded '&' as '&amp;'), dedups, writes:
  corpus_evidence.json   (list[str])
  corpus_triples.json    (list[{claim, ev_support, ev_silent}])
  corpus_conjuncts.json  (list[{ev1, traceable_2nd, untraceable_2nd}])
  corpus_hops.json       (list[{ev1, ev2, bridge_claim}])
and prints stats + a few samples per type for a structural eyeball.

Usage: python ingest_corpus.py <workflow_output_file>
"""
import sys, os, json, html, re

HERE = os.path.dirname(os.path.abspath(__file__))


def clean(x):
    if isinstance(x, str):
        return html.unescape(x).strip()
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    return x


def load_result(path):
    raw = open(path, encoding="utf-8").read()
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j < 0:
        raise SystemExit("no JSON object found in output file")
    return json.loads(raw[i:j + 1])


def main():
    src = sys.argv[1]
    data = clean(load_result(src))
    data = data.get("result", data)   # the task-output file wraps the return value under "result"
    evidence = data.get("evidence", [])
    triples = data.get("triples", [])
    conjuncts = data.get("conjuncts", [])
    hops = data.get("hops", [])

    # dedup evidence by normalized text
    seen, ev = set(), []
    for e in evidence:
        k = re.sub(r"\s+", " ", str(e).lower()).strip()
        if k and k not in seen:
            seen.add(k); ev.append(e)

    json.dump(ev, open(os.path.join(HERE, "corpus_evidence.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(triples, open(os.path.join(HERE, "corpus_triples.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(conjuncts, open(os.path.join(HERE, "corpus_conjuncts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(hops, open(os.path.join(HERE, "corpus_hops.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print(f"evidence : {len(ev)} (deduped from {len(evidence)})")
    print(f"triples  : {len(triples)}")
    print(f"conjuncts: {len(conjuncts)}")
    print(f"hops     : {len(hops)}")
    print("\n--- evidence samples ---")
    for e in ev[:4]:
        print("  •", e)
    print("\n--- triple samples (claim | ev_support | ev_silent) ---")
    for t in triples[:3]:
        print(f"  claim   : {t.get('claim')}")
        print(f"  support : {t.get('ev_support')}")
        print(f"  silent  : {t.get('ev_silent')}\n")
    print("--- conjunct samples (ev1 | traceable_2nd | untraceable_2nd) ---")
    for c in conjuncts[:3]:
        print(f"  ev1        : {c.get('ev1')}")
        print(f"  traceable  : {c.get('traceable_2nd')}")
        print(f"  untraceable: {c.get('untraceable_2nd')}\n")
    print("--- hop samples (ev1 | ev2 | bridge_claim) ---")
    for h in hops[:3]:
        print(f"  ev1   : {h.get('ev1')}")
        print(f"  ev2   : {h.get('ev2')}")
        print(f"  bridge: {h.get('bridge_claim')}\n")


if __name__ == "__main__":
    main()
