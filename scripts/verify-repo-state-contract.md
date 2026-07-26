# verify-repo-state.sh — Output And Exit Contract

Detail file for `scripts/verify-repo-state.md`. Describes the stable
machine-readable contract callers may depend on.

## stdout evidence contract

stdout carries only this, in this order:

```
HEAD_REF=<branch>
HEAD_SHA=<40-hex sha>
BASE_REF=origin/<base>
BASE_SHA=<40-hex sha>
CHANGED_FILES_BEGIN
path/to/file
CHANGED_FILES_END
```

Field names mirror the repository-state vocabulary already used by
`scripts/agent_os_execution_capabilities/models.py` (`head_ref`, `head_sha`,
`base_ref`, `base_sha`).

Changed files come from `git diff --name-only origin/<base>...HEAD` — the
merge-base comparison, so a base branch that moved on its own is not reported
as branch work. An **empty** block means HEAD introduces no changes relative to
the merge base with `origin/<base>`.

Paths are newline-separated with `core.quotePath=false`; filenames containing
newlines are not representable in this format.

## stderr logging contract

Every log, note, warning, and error goes to stderr, along with underlying Git
command output. Nothing but the evidence contract reaches stdout, so
`$(scripts/verify-repo-state.sh "$BRANCH")` is safe to capture.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Invalid arguments, not a work tree, or no `origin` remote |
| 3 | Uncommitted tracked changes |
| 4 | Fetch failed after bounded retries |
| 5 | Branch missing without `--create-from-base`, or refspec too narrow |
| 6 | Branch switch or creation failed |
| 7 | Fast-forward failed (diverged branch) |
| 8 | Base ref missing, or no merge base (e.g. shallow clone) |
| 9 | Evidence generation failed |

The script exits explicitly on every path, so no incidental final-command
status becomes the contract.

## Retries

Only `git fetch --prune origin` is retried; it is the sole genuinely transient
operation. Deterministic local operations — switch, fast-forward, ref checks,
dirty-tree checks, argument validation — fail immediately without retry.

Default backoff is 2s then 4s (three attempts total). The delay list is the
whole configuration, so there is no unreachable cap constant. Tests inject
`VERIFY_REPO_STATE_RETRY_DELAYS` to exercise bounded retries without sleeping
for real backoff durations.
