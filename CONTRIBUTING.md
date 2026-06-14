# Contributing to prism-verify

Thanks for helping make the verifier more trustworthy. prism-verify is a runtime adjudication
service: its job is to be *sound* (never confirm a fabrication), so contributions are held to a
test-first, gate-green bar. This file is the short, accurate-to-this-repo runbook.

## Standards compliance

This doc describes two workflows (local verify gate, release runbook). Scored against the six
workflow standards (PIN_PER_STEP, ANDON_AUTHORITY, NAMED_COMPENSATORS, DECOMPOSE_BY_SECRETS,
UNCERTAINTY_GATED_HUMANS, EXTERNAL_VERIFIER):

- **PIN_PER_STEP — 2.** The release tag check pins the published version to `pyproject.toml` /
  `npm/package.json` (release.yml); the local gate pins the dependency set to CI's exact sync flags.
- **ANDON_AUTHORITY — 3.** `scripts/verify.py` exits non-zero on the **first** failing step; CI is
  paths-gated and fails the matrix on any red. Either halts the pipeline before merge/publish.
- **NAMED_COMPENSATORS — 2.** The release section below carries a compensators table for every
  irreversible publish action (PyPI / npm / GitHub Release / tag push).
- **EXTERNAL_VERIFIER — 3.** This is the product: every lens runs a *different* model family than
  the caller, with the generator's reasoning stripped. The verify gate itself is run by CI (a
  separate environment from the author's machine).

DECOMPOSE_BY_SECRETS / UNCERTAINTY_GATED_HUMANS are `skip:` for this doc — it documents a gate, it
is not itself a multi-agent pipeline.

## Dev setup

Requires **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).

```bash
# Sync the dev + non-heavy extras (mirrors CI — all extras except the torch-bearing nli/all).
uv sync --all-extras --no-extra nli --no-extra all
```

The optional `nli` floor (torch + transformers) is heavy and **not** installed by default; its
tests are written to run torch-free, so you do not need it to develop or to get a green gate. Install
it only when working on the NLI floor itself: `uv sync --extra nli`.

## The verify gate

One command runs the **same checks as CI, in the same order, with the same flags** — so "local
green" means "CI green":

```bash
uv run python scripts/verify.py
```

Steps, in order (exits non-zero on the first failure):

1. `uv sync --all-extras --no-extra nli --no-extra all` — the exact dependency set CI installs.
2. `ruff check src/ tests/` — lint.
3. `mypy src/` — `strict = true` type-check.
4. `pytest --tb=short` — the full suite.
5. `uv build` — a clean sdist + wheel (local-only; catches packaging breakage CI's test job skips).

Run it before every push. If `scripts/verify.py`'s sync flags ever drift from `.github/workflows/
ci.yml`, fix both together — they must stay in lockstep.

## Test conventions

- **Test-first for code.** New behavior lands red→green: write the failing test, then the code.
  Soundness-critical paths (the oracle, the lenses) get a test that **fails if the guard is
  removed** — see `tests/unit/test_oracle.py`, whose docstring lists each guard it pins.
- **Layout.** `tests/unit/` for isolated units, `tests/integration/` for engine/HTTP/eval wiring.
- **Async + mocking.** `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed). Network is
  mocked with [`respx`](https://lundberg.github.io/respx/) — tests never hit live arXiv / Crossref.
- **Precision bias.** When in doubt, a test should assert the *safe* outcome: a transient/fuzzy
  result escalates (UNRESOLVABLE / ESCALATE), it never upgrades to RESOLVED / ACCEPT.
- **Optional-extra tests** must pass torch-free (CI does not install `nli`); inject fakes rather
  than depending on the heavy extra — see `tests/unit/test_nli.py`.

## Release runbook

Releases are driven by **`.github/workflows/release.yml`**, which fires on a **published GitHub
Release** (`release: published`). The workflow publishes to PyPI (Trusted Publishing / OIDC), builds
+ uploads the per-platform PyInstaller binaries, then publishes the npm launcher (Trusted
Publishing). No long-lived tokens.

### Preconditions (do these before creating the GitHub Release)

1. **Verify gate is green** locally and on CI for the commit you will tag.
2. **Version bump.** Bump `version` in `pyproject.toml` **and** `npm/package.json` to the same
   value — release.yml hard-fails if the tag (minus a leading `v`) does not match both. Follow
   [SemVer](https://semver.org/); update `CHANGELOG.md` (move `[Unreleased]` to the new version).
3. **README + translations FIRST.** If `README.md` changes are part of the release, regenerate the
   translations **before** tagging — the GitHub Release tag is immutable, so stale translations at
   the tag are permanent. Translations run locally (zero API cost):

   ```bash
   node E:/AI/polyglot-mcp/scripts/translate-all.mjs README.md
   ```

   Stage source + translated READMEs together (`git add README.md README.*.md`) in the release
   commit. **Order: README → CHANGELOG/version bump → translations → commit → tag → push → then
   create the GitHub Release.** Never let translations land in a follow-up commit after the tag.
4. **Tag** matches the version (`vX.Y.Z`), pushed to `main`.
5. **Create the GitHub Release** against that tag — this is what triggers publishing.

### Compensators (irreversible publish actions)

| Action | Undo | Post-rollback state | Owner |
|--------|------|--------------------|-------|
| `git push <tag>` | `git push --delete origin <tag>` (before the Release is created) | tag gone; no publish triggered | releaser |
| GitHub Release published | Delete the Release in the GitHub UI / `gh release delete <tag>` | binaries + notes removed; PyPI/npm already published are NOT reverted | releaser |
| PyPI publish | **No deletion-then-reuse** — a yanked/deleted version number can never be re-used on PyPI. Ship a new patch version instead | bad version yanked, new patch supersedes | releaser |
| npm publish | `npm deprecate @mcptoolshop/prism-verify@<v> "<reason>"` (unpublish is blocked after 72h) | version deprecated, new patch supersedes | releaser |

Because PyPI/npm publishes are effectively irreversible, treat a green gate + correct version match
as the andon stop: if either is wrong, **do not create the Release**.

## Security

Found a vulnerability? See [SECURITY.md](SECURITY.md) — do not open a public issue for it.
