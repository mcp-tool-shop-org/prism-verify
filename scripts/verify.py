#!/usr/bin/env python
"""prism verify script — the full local quality gate in one command.

Runs the same checks as CI (lint -> type-check -> tests) plus a real package build, exiting
non-zero on the first failure. Cross-platform (no shell-specific syntax).

    uv run python scripts/verify.py
"""

from __future__ import annotations

import subprocess
import sys

# Use `uv run python -m <tool>` (not the bare `uv run <tool>`): the bare form hits a
# uv-on-Windows trampoline bug ("failed to canonicalize script path").
STEPS: list[tuple[str, list[str]]] = [
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
