#!/usr/bin/env python
"""Merge a supplement build-verifier-corpus workflow result into the corpus_*.json files (dedup).
Usage: python merge_corpus.py <workflow_output_file>"""
import sys, os, json, html

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
    obj = clean(json.loads(raw[i:j + 1]))
    return obj.get("result", obj)


def merge(name, new_items, keyfn):
    path = os.path.join(HERE, name)
    ex = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    seen = {keyfn(e) for e in ex}
    added = 0
    for it in new_items:
        k = keyfn(it)
        if k and k not in seen:
            seen.add(k); ex.append(it); added += 1
    json.dump(ex, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{name}: {len(ex)} total (+{added})")


def main():
    d = load_result(sys.argv[1])
    merge("corpus_triples.json", d.get("triples", []), lambda t: (t.get("claim") or "").lower().strip())
    merge("corpus_conjuncts.json", d.get("conjuncts", []), lambda c: (c.get("ev1") or "").lower().strip())
    merge("corpus_hops.json", d.get("hops", []), lambda h: (h.get("bridge_claim") or "").lower().strip())


if __name__ == "__main__":
    main()
