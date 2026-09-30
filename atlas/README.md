# prism-verify: how it works

Mapped at 2026-09-30 from commit 94925c6 by Atlas 1.24.0.

## What this is

18 parts, mostly Python (200 files), JavaScript (6), CSS (2), TypeScript (2) and Astro (1). Work enters through 5 doors; CI and Release each reach 9 parts, and CI is followed because a pull request goes through it. It publishes to PyPI and @mcptoolshop/prism-verify to npm. It deploys a site to GitHub Pages. People run prism.

## What changed since 2026-09-25 (a89ace7)

- CI's pull request trigger now also names `codecov.yml`.
- CI's push trigger now also names `codecov.yml`.
- prism (npm/package.json) is a new command. It runs npm/bin/prism.js.
- eval/corpus-familyab-v3 is now written by src/prism/eval/familygen.py.
- eval/corpus-familyab-v3/FAMILYAB_MANIFEST.json is now written by src/prism/eval/familygen.py.
- 1 file added and 3 changed content, across 2 parts.

## What comes in

1. **CI.** On a pull request touching 9 paths; on a push touching 9 paths; or by hand. Checks src/ and tests/.
2. **Release.** When a release is published; or by hand. Builds src/prism/__main__.py; checks npm/bin/prism.js and src/prism/.
3. **Deploy site to GitHub Pages.** On a push to main touching 2 paths; or by hand. Runs site/astro.config.mjs and site/src/.
4. **prism** (a command people run, from pyproject.toml). Runs src/prism/cli/main.py.
5. **prism** (a command people run, from npm/package.json). Runs npm/bin/prism.js.

## What happens through CI

1. The workflow checks tests/ in tests and src/ (8 parts).
2. It uploads coverage to Codecov.

## Who reads the results

CI writes nothing this map can see.

## The other doors

**Release** checks npm/bin/prism.js and src/prism/, publishes to PyPI and @mcptoolshop/prism-verify to npm, and builds src/prism/__main__.py into binaries for darwin-arm64, linux-x64 and win-x64 and uploads them to the release.

**Deploy site to GitHub Pages** runs site/astro.config.mjs and site/src/, and deploys the site.

**prism** (a command people run, from pyproject.toml) runs src/prism/cli/main.py and reaches core, eval-harness, lenses, probes, providers, receipts and servers.

**prism** (a command people run, from npm/package.json) runs npm/bin/prism.js.

## What breaks what

- **core** is imported by 6 parts (cli, eval-harness, lenses, providers, receipts, servers), and by 1 more only from tests; it sits on the path of 3 doors.
- **providers** is imported by 5 parts (cli, core, eval-harness, lenses, probes), and by 1 more only from tests; it sits on the path of 3 doors.
- **eval-harness** is imported by 3 parts (cli, core, eval), and by 1 more only from tests; it sits on the path of 3 doors.
- **receipts** is imported by 3 parts (cli, core, servers), and by 1 more only from tests; it sits on the path of 3 doors.
- **lenses** is imported by 1 part (core), and by 1 more only from tests; it sits on the path of 3 doors.
- **probes** is imported by 1 part (cli), and by 1 more only from tests; it sits on the path of 3 doors.
- **servers** is imported by 1 part (cli), and by 1 more only from tests; it sits on the path of 3 doors.
- **cli** is imported only from tests, by 1 part (tests), and sits on the path of 3 doors.

## What tends to change together

- **src/prism/http/app.py** and **tests/integration/test_http.py** changed together in 5 of 6 commits, and the tests part imports the servers part.
- **src/prism/providers/ollama.py** and **src/prism/providers/openai.py** changed together in 5 of 6 commits, inside the providers part.
- **src/prism/receipts/store.py** and **tests/unit/test_receipts.py** changed together in 9 of 11 commits, and the tests part imports the receipts part.
- **src/prism/providers/anthropic.py** and **src/prism/providers/openai.py** changed together in 4 of 6 commits, inside the providers part.
- **src/prism/providers/anthropic.py** and **src/prism/providers/ollama.py** changed together in 4 of 7 commits, inside the providers part.

1 file changed together with its own test, as expected.

Confidence is low: fewer than 25 source files reach 10 revisions in the window.

Window: 180 days; a pair counts from 3 shared commits, since 7 source files reach 10 revisions; the floor rises to 10 when 25 do.

## What no test touches

- **eval** is imported by no test.
- **npm** is imported by no test.
- **scripts** is imported by no test.

specialist/probes/test_sycophancy_probes.py runs in no workflow.

## Written but never read

- **specialist/dataset/** is written by specialist/dataset/merge_corpus.py and read by nothing else in this repository.
- **specialist/dataset/corpus_conjuncts.json** is written by specialist/dataset/ingest_corpus.py and read by nothing else in this repository.
- **specialist/dataset/corpus_hops.json** is written by specialist/dataset/ingest_corpus.py and read by nothing else in this repository.
- **specialist/dataset/corpus_triples.json** is written by specialist/dataset/ingest_corpus.py and read by nothing else in this repository.
- **specialist/dataset/gate_validation_records.json** is written by specialist/dataset/validate_gate.py and read by nothing else in this repository.
- **specialist/dataset/gate_validation_report.txt** is written by specialist/dataset/validate_gate.py and read by nothing else in this repository.
- **specialist/dataset/verifier_exam_records.jsonl** is written by specialist/dataset/build_verifier_dataset.py and read by nothing else in this repository.
- **specialist/dataset/verifier_train_sft.jsonl** is written by specialist/dataset/build_verifier_dataset.py and read by nothing else in this repository.

## Helpers that look duplicated

No two parts export a helper that looks alike.

## Generated, never hand-edited

- **specialist/dataset/** is written by specialist/dataset/merge_corpus.py.
- **specialist/dataset/corpus_conjuncts.json** is written by specialist/dataset/ingest_corpus.py.
- **specialist/dataset/corpus_evidence.json** is written by specialist/dataset/ingest_corpus.py.
- **specialist/dataset/corpus_hops.json** is written by specialist/dataset/ingest_corpus.py.
- **specialist/dataset/corpus_triples.json** is written by specialist/dataset/ingest_corpus.py.
- **specialist/dataset/gate_validation_records.json** is written by specialist/dataset/validate_gate.py.
- **specialist/dataset/gate_validation_report.txt** is written by specialist/dataset/validate_gate.py.
- **specialist/dataset/gated_phase2.jsonl** has a block written by specialist/dataset/gen_phase2.py.
- **specialist/dataset/gen_phase2.jsonl** has a block written by specialist/dataset/gen_phase2.py.
- **specialist/dataset/phase2_records.jsonl** is written by specialist/dataset/gen_phase2.py.
- **specialist/dataset/verifier_exam_records.jsonl** is written by specialist/dataset/build_verifier_dataset.py.
- **specialist/dataset/verifier_records.jsonl** is written by specialist/dataset/build_verifier_dataset.py.
- **specialist/dataset/verifier_train_sft.jsonl** is written by specialist/dataset/build_verifier_dataset.py.

## Hand-authored

People write .github/, assets/, design/, the repository root and site/; 3 writes with paths built at run time may land here.

## Where to start

Start at src/prism/cli/main.py to follow one run of prism end to end. This path follows prism (a command people run, from pyproject.toml) from its entry, since CI only checks code.

## What this map cannot see

- 2 import sites name a path outside this repository, so what they load is not followed.
- 3 writes and 5 reads use paths built at run time and are not named here.
- 2 writes go to places this repository does not track, so they are not listed as generated.
- 18 writes and 28 reads go to a path their caller passes, not to this repository.
- 1 read goes to the directory the command is run in (eval/), not to this repository.
- There is a Dockerfile at eval/docker/labeler.Dockerfile that no workflow runs; what deploys from it does so from outside this repository, and is not on this page.
- Statistics confidence is low: fewer than 25 source files reach 10 revisions in the window.

Regenerate with `npx --yes @dogfood-lab/atlas map`.
