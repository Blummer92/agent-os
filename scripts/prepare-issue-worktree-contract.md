# prepare-issue-worktree.sh — Output, Status, And Exit Contract

Detail file for `scripts/prepare-issue-worktree.md`. Describes the stable
machine-readable contract callers may depend on.

## stdout evidence contract

stdout carries exactly one JSON object, keys always present in this order:

```json
{
  "schema": "agent-os.issue-worktree-preparation.v1",
  "status": "prepared",
  "issue_number": 807,
  "repository": "Blummer92/agent-os",
  "requested_ref": "agent/807-checkout-preparation",
  "resolved_ref": "refs/remotes/origin/agent/807-checkout-preparation",
  "resolved_sha": "<40-hex sha>",
  "checkout_mode": "branch",
  "head_state": "detached",
  "worktree_path": "/home/operator/agent-os-worktrees/issue-807",
  "worktree_reused": false,
  "working_tree_clean": true,
  "remote_fetch_performed": true,
  "branch_created": false,
  "side_effects_performed": ["worktree-created", "identity-marker-written"],
  "repository_implementation_authorized": false,
  "execution_authorized": false,
  "github_writes_authorized": false,
  "merge_authorized": false,
  "reason": "<bounded explanation>"
}
```

Every terminal outcome — including rejected input — emits this object, so
failure is as machine-readable as success. `--help` is the sole exception: it
prints usage to stderr and exits 0 with empty stdout.

`checkout_mode` is `branch`, `tag`, or `detached-sha` and describes how the
target was **resolved**. `head_state` is `detached` or `attached` and describes
the prepared worktree's HEAD. `issue_number` is a JSON number, or `null` when
the supplied value was rejected before validation completed.

`side_effects_performed` is bounded to `worktree-root-created`,
`worktree-created`, `branch-created`, and `identity-marker-written`. It is empty
for `already-prepared` and for every failure — the contract's proof that nothing
was mutated. `reason` is at most 200 characters with control characters, quotes,
and backslashes stripped, so the object always parses. `working_tree_clean` is
meaningful for `prepared` and `already-prepared`; on other outcomes it reports
the state observed before the command stopped.

## Authority fields

The four authority fields are literal `false` and are not computed. Preparation
success never changes them; only a separate canonical authorization contract
can grant implementation, execution, GitHub-write, or merge authority.

## stderr logging contract

Every log, note, warning, and error goes to stderr with underlying Git output,
ending in a two-line human summary (`STATUS=…` then `reason:`). Nothing but the
JSON object reaches stdout, so `$(scripts/prepare-issue-worktree.sh …)` is safe
to capture.

## Statuses and exit codes

| Code | Status | Meaning |
|---|---|---|
| 0 | `prepared` | A new worktree was prepared at the resolved commit |
| 0 | `already-prepared` | Every identity field matched; nothing was modified |
| 2 | `blocked` | Invalid arguments, not a work tree, or no `origin` remote |
| 3 | `blocked` | Uncommitted tracked changes in the target worktree |
| 4 | `unavailable` | Fetch failed after bounded retries |
| 5 | `blocked` | Ref missing or unattachable, or refspec too narrow |
| 6 | `blocked`/`unavailable` | Worktree operation or inspection failed |
| 7 | `manual-review` | Identity, path, branch, lock, or ref conflict |
| 8 | `blocked` | Base ref unusable for authorized branch creation |
| 9 | `unavailable`/`manual-review` | Evidence generation or verification failed |

The script exits explicitly on every path, so no incidental final-command
status becomes the contract.

## Idempotency

`already-prepared` is returned only when the path, repository, requested ref,
resolved ref, exact SHA, checkout mode, and HEAD state all match the identity
record stored in the worktree's Git metadata (`agent-os-issue-identity`), and
the worktree is clean. Any other combination is a conflict, never a repair.

## Retries

Only `git fetch --prune --tags origin` is retried, reusing the canonical
repository-state retry contract in `scripts/verify-repo-state-contract.md`: same
`VERIFY_REPO_STATE_RETRY_DELAYS` variable, same default `2 4` schedule. No
second retry framework exists. Deterministic local failures — argument
validation, identity checks, dirty state, ref resolution, collisions — fail
immediately. Fetch failure (`unavailable`, exit 4) is classified separately from
a missing ref (`blocked`, exit 5): remote unavailability is never reported as
absence.
