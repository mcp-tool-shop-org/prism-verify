# Named Compensators — Prism

Required by NAMED_COMPENSATORS standard. Documents the reversibility strategy for every irreversible write prism performs.

## Compensator Table

| Irreversible Action | Trigger Condition | Compensator | CLI / API Surface | Notes |
|---------------------|-------------------|-------------|-------------------|-------|
| SQLite receipt INSERT | Every successful `verify()` call | `prism receipt delete <receipt_id>` | CLI: `prism receipt delete <id>` / Python: `store.delete_receipt(id)` | Deletes the row. Cannot un-delete — but receipts are append-only evidence; deletion is an admin escape hatch, not a normal flow. |
| SQLite receipt bulk accumulation | Retention exceeds policy | `prism receipt prune --older-than <duration> --yes` | CLI: `prism receipt prune --older-than 90d --yes` / Python: `store.prune(older_than=timedelta(days=90))` | Bulk removal by age, gated behind `--yes`; prunes on the signed UTC `timestamp` column. Irreversible — export before pruning if audit trail matters. |
| Webhook verdict send (**v0.4**) | An async / `escalate` `verdict` POSTed to a caller endpoint | **`send_cancel_event()`** — a signed `verdict_cancelled` POST to the same endpoint | `prism.http.webhook.send_cancel_event(url, receipt_id=…, secret=…, reason=…)` | Sagas semantic cancellation (Garcia-Molina & Salem 1987): cannot un-send, but withdraws the verdict; same signing + SSRF guard + bounded-retry machinery, a distinct `webhook-id`. The escalate POST is the *last* irreversible step in the verify saga. Owner: prism HTTP runtime. |
| MCP state mutation (future) | Client caches a verdict from MCP tool response | Re-issue `verify()` with same inputs; client invalidates cache | MCP tool: `prism.reverify` | Compensates stale state in the caller's context. Not a true rollback — generates a new receipt that supersedes the old one. |

## Release-process compensators (v0.4 — NO-SKIP)

v0.4 ships to PyPI + cuts a GitHub release + sets repo metadata. These are irreversible
world-touching actions; each has a named compensator + owner (mirrors [[full-treatment]]).

| Irreversible action | Compensator | Command / surface | Owner | Post-rollback state |
|---|---|---|---|---|
| PyPI publish (`prism-verify 0.4.0`) | **Yank** the release | pypi.org → project → release → *Yank* (or `--yank` via API) | release operator (director) | Hidden from new resolves; **already-pinned installs keep resolving it — yank ≠ unpublish/delete.** |
| GitHub Release `v0.4.0` | **Delete** the release | `gh release delete v0.4.0 --yes` | release operator (director) | Release page gone; the **tag remains** (delete separately: `git push origin :refs/tags/v0.4.0`). |
| `gh repo edit` (topics / homepage / description) | Re-set prior metadata | `gh repo edit --add-topic …` / `--homepage …` / `--description …` | release operator | Idempotent overwrite restores the prior values. |
| GitHub Pages deploy (landing/handbook) | Re-deploy prior commit | revert the site commit + re-run Pages, or disable Pages in repo settings | release operator | Prior site (or no site) restored. |

## Read-only external actions (no compensator — documented)

Per the no-skip rule, irreversible *writes* need a named compensator; a *read* needs none — but we
document why, so the absence is a decision, not an omission.

| Action | Why no compensator |
|--------|--------------------|
| Citation existence retrieval (`prism.retrieval` — arXiv / Crossref `GET`, v0.3) | Read-only and external: a GET against a public scholarly API, with no world-state write to undo. The oracle is a courteous, idempotent reader — per-identifier response caching within a run, arXiv's ~3 s serialization, and a Crossref `mailto` for the polite pool — so it has nothing to compensate. The only write the citation path performs is the receipt INSERT, already covered by `receipt delete` / `prune` above. |

## Design Principles

1. **Receipts are evidence, not state.** The primary use of receipts is audit replay, not control flow. Deletion is an escape hatch for GDPR/retention compliance, not a "whoops wrong answer" mechanism.

2. **Semantic compensation over physical rollback.** For network-sent verdicts (webhook, MCP), we cannot un-send. The compensator is a follow-up message that says "disregard previous." The receiver must handle this.

3. **Prism never compensates the caller's actions.** If a caller acts on an `accept` verdict and later prism re-verifies to `refuse`, prism is not responsible for rolling back what the caller did. Prism's compensator scope ends at "I told you the new answer."

## Implementation Status

| Compensator | Status | Tracking |
|-------------|--------|----------|
| `receipt delete` | **Implemented (v0.2.0); undo proven end-to-end (v0.3.0)** | `prism receipt delete <id>` · `store.delete_receipt(id)` — rowcount-backed bool; the compensate-after-verify flow (`tests/integration/test_compensate_after_verify.py`) runs verify → signed receipt → delete → asserts the row is gone |
| `receipt prune` | **Implemented (v0.2.0); undo proven end-to-end (v0.3.0)** | `prism receipt prune --older-than <dur> --yes` · `store.prune(older_than)` — UTC-timestamp, returns count; the same flow prunes a backdated post-verify receipt by age |
| Webhook cancel-event | **Implemented (v0.4)** | `prism.http.webhook.send_cancel_event()` — signed `verdict_cancelled` POST; exercised by `tests/unit/test_webhook.py::TestDelivery::test_send_cancel_event_delivers_signed_compensator` |
| MCP reverify | Design only (v1.5) | Deferred |
| PyPI yank / GitHub-release delete / `gh repo edit` revert | Operator-run at release | See the Release-process compensators table above |

`receipt delete` and `receipt prune` are the **terminal leaves** of the compensation tree:
they undo the receipt INSERT and intentionally have no compensator of their own (a deleted
receipt is gone). `prune` is gated behind `--yes` and keys off the signed UTC `timestamp`,
never the local `created_at`, so the cutoff window is timezone-consistent.
