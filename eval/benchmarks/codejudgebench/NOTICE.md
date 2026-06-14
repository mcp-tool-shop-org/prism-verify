# CodeJudgeBench — attribution

prism's CodeJudgeBench harness (`src/prism/eval/benchmarks/`) evaluates against:

- **Dataset:** CodeJudgeBench
- **HF:** https://huggingface.co/datasets/mattymchen/codejudgebench
- **Paper:** *CodeJudgeBench: Benchmarking LLM-as-a-Judge for Coding Tasks*, arXiv:2507.10535
- **License:** Apache-2.0

## What is in this directory

`fixture.jsonl` is a **small, hand-authored, ~6-item fixture** in prism's `CJBItem` shape, used for
**offline tests and `prism eval --benchmark codejudgebench --offline`**. It is **NOT a copy or
redistribution of the CodeJudgeBench dataset** — the questions and code are authored by prism's
maintainers to exercise the loader/harness machinery without network access or the HF `datasets`
library. The fixture mirrors the dataset's *structure* (a `question`, a chosen `pos_response`, and a
rejected `neg_response` per task) so the offline path validates the same column contract the real
load enforces.

To run against the **real** dataset, install the optional extra and load on demand:

```bash
pip install 'prism-verify[bench]'
prism eval --benchmark codejudgebench --bench-task codegen --bench-limit 50
```

The real load downloads from Hugging Face on demand; nothing from the upstream dataset is vendored
into this repository.

## Schema (verified 2026-06-14 against the HF dataset card + datasets-server `/info`)

- Configs are the task categories: `codegen`, `codegen_pass5`, `coderepair`, `testgen`.
- Splits are the producing model (e.g. `claude_3.7_sonnet`, `gemini_2.5_pro`).
- Columns: `question_content` (prompt), `pos_response` (chosen), `neg_response` (rejected),
  `starter_code` (optional context; `wrong_code` for coderepair), plus `question_id`,
  `question_title`, `platform`, `difficulty`. There is no explicit preference-label column —
  preference is implicit in pos vs neg.

Apache-2.0 license text: https://www.apache.org/licenses/LICENSE-2.0
