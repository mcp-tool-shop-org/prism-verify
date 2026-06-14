#!/usr/bin/env python
"""prism verify script — the full local quality gate in one command.

Runs the same checks as CI, in the same order with the same flags, so "local green" means "CI
green": it first SYNCS the same dependency set CI installs (all extras EXCEPT the heavy torch-
bearing `nli` / `all` extras — see ci.yml), then runs lint -> type-check -> tests, plus a real
package build CI does not do. Exits non-zero on the first failure. Cross-platform (no shell-
specific syntax).

    uv run python scripts/verify.py
"""

from __future__ import annotations

import subprocess
import sys

# Use `uv run python -m <tool>` (not the bare `uv run <tool>`): the bare form hits a
# uv-on-Windows trampoline bug ("failed to canonicalize script path").
#
# The `sync` step MUST match ci.yml's install line exactly. CI installs every extra except the two
# that bundle torch + transformers (`nli` and the `all` meta-extra); the NLI floor's tests run
# torch-free, so syncing it here would diverge local from CI. Keep this flag set in lockstep with
# `.github/workflows/ci.yml`.
STEPS: list[tuple[str, list[str]]] = [
    ("sync", ["uv", "sync", "--all-extras", "--no-extra", "nli", "--no-extra", "all"]),
    ("ruff", ["uv", "run", "python", "-m", "ruff", "check", "src/", "tests/"]),
    ("mypy", ["uv", "run", "python", "-m", "mypy", "src/"]),
    ("pytest", ["uv", "run", "python", "-m", "pytest", "--tb=short"]),
    ("build", ["uv", "build"]),  # clean sdist + wheel (top-level uv cmd, not affected)
]


def main() -> int:
    for name, cmd in STEPS:
        print(f"\n=== {name} ===", flush=True)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\nFAILED at: {name}", file=sys.stderr)
            return result.returncode
    print("\nAll verify steps passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
