# Vendored QuixBugs (trimmed)

A trimmed, offline checkout of the **QuixBugs** benchmark, vendored so prism's
real-bug corpus ingester (`src/prism/eval/realbug.py`) runs with **no network at
runtime**.

## Source

- **Repository:** https://github.com/jkoppel/QuixBugs
- **License:** MIT (see `LICENSE` in this directory — Copyright 2017-2019 James Koppel)
- **Pinned commit:** `4257f44b0ff1181dedaedee6a447e133219fcebf`
- **Vendored:** 2026-06-14

QuixBugs is the benchmark from Derrick Lin, James Koppel, Angela Chen, and Armando
Solar-Lezama, *"QuixBugs: A Multi-Lingual Program Repair Benchmark Set Based on the
Quixey Challenge"* (SPLASH Companion 2017). Each program ships with a single-line
defect (`python_programs/`) and a corrected counterpart (`correct_python_programs/`).

## What was vendored

Only the **Python program pairs** needed for ingestion, plus the upstream `LICENSE`:

- `python_programs/<name>.py` — the BUGGY version (single-line defect).
- `correct_python_programs/<name>.py` — the CORRECTED version.

**25 program pairs** (50 `.py` files), the subset the ingester maps to a code lens
with high confidence. The `_QUIXBUGS_LENS_MAP` / `_QUIXBUGS_INTENT` / `_QUIXBUGS_BUG_CLASS`
dicts in `realbug.py` are the authoritative per-program labels; a program absent from
those maps is simply not ingested.

## What was trimmed (NOT vendored)

- All **Java** sources (`java_programs/`, `correct_java_programs/`).
- All **test harnesses** and `*_test.py` driver files.
- All **JSON testcases** (`json_testcases/`) and the pytest/gradle tooling.
- Doc/build files (`README`, `setup.py`, etc.).

These are not needed: the ingester only reads the buggy/corrected Python source text
to build labeled `Sample`s.

## Contamination note (read before trusting public-split numbers)

QuixBugs is small and famous; verifier models have very likely seen it in
pretraining. The QuixBugs-derived samples are therefore wired into the corpus's
**`public`** split and flagged `contaminated: true` in `eval/corpus/MANIFEST.json`.
A public-split accuracy on these samples is a **CEILING**, not an honest
generalization estimate — the `fresh` split (post-cutoff, deferred to v1.2) is the
honest signal. The report (`render_markdown`) prints a caveat to this effect when a
contaminated sample is present.

## These files are DATA, not package code

The vendored `.py` files live under `eval/vendor/` — outside `src/` and `tests/` — so
they are never linted, type-checked, or collected as tests, and nothing imports them
as modules. They are read as text at corpus-build time only.
