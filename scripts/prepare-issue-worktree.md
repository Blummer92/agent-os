# prepare-issue-worktree.sh

Reusable, fail-closed checkout preparation for one Agent OS issue. It prepares
or reuses an isolated Git worktree at an exact revision and stops. It is an
**operator preparation surface only**. Output, exit-code, evidence, and retry
contracts are in `scripts/prepare-issue-worktree-contract.md`.

## Non-authorization

Successful preparation never implies issue readiness, implementation
authorization, execution authorization, validation success, Ready-for-Review,
merge authorization, or issue completion. Every authority field in its evidence
is `false` on every outcome and only a separate canonical authorization
contract can change that.

## Syntax

```bash
scripts/prepare-issue-worktree.sh \
  --issue <n> --repository <owner/name> --ref <branch|tag|sha40> \
  --worktree-root <absolute path> \
  [--attach-branch] [--allow-branch-creation --base-ref <branch>]
```

Run it from inside an existing Agent OS checkout. It never clones and never
discovers a repository: outside a work tree it fails with exit 2, and an
`origin` whose identity differs from `--repository` is identity drift
(`manual-review`). Nothing is inferred from issue prose.

### Desktop and mobile

The same invocation runs unchanged in either. On mobile, read the one-line
`STATUS=` summary on stderr; redirect stdout for a machine-readable record.

```bash
cd ~/agent-os
scripts/prepare-issue-worktree.sh --issue 807 --repository Blummer92/agent-os \
  --ref agent/807-checkout-preparation --worktree-root ~/agent-os-worktrees
cd ~/agent-os-worktrees/issue-807
```

## Branch, tag, and SHA behavior

| `--ref` | Resolution | `checkout_mode` |
|---|---|---|
| Local branch | `refs/heads/<ref>` | `branch` |
| Remote-only branch | `refs/remotes/origin/<ref>` | `branch` |
| Tag (annotated or lightweight) | `refs/tags/<ref>^{commit}` | `tag` |
| Exact lowercase 40-hex SHA | the commit itself | `detached-sha` |

A name that exists as both a branch and a tag is ambiguous and routes to
`manual-review`. A local branch that disagrees with `origin/<branch>` does too;
reconcile it with `scripts/verify-repo-state.sh` first. Hex-only refs of 7+
characters that are not exactly 40 lowercase characters are rejected as
malformed SHAs rather than guessed at.

## Detached HEAD and exact-SHA validation

HEAD is detached at the resolved commit by default in every mode, so validation
evidence is reproducible and no branch is claimed. Prefer `--ref <sha40>` when
producing final validation evidence: requested and resolved SHA are then
identical by construction. `--attach-branch` checks an existing **local** branch
out attached instead; a remote-only branch is never attached, because that would
create a local branch.

## Isolated worktree paths

One issue, one path: `<worktree-root>/issue-<n>`. Several issues may be prepared
concurrently through separate worktrees. The shared primary checkout is never
switched between issue branches as a substitute for isolation, and one branch is
never claimed by two active worktrees.

## Dirty state, collisions, and cleanup handoff

- Tracked modifications in the target worktree block the run (exit 3). No work
  is stashed, reset, cleaned, or checked out over.
- Untracked files are permitted, noted on stderr, and never modified.
- An occupied path, a symlinked root or target, a foreign identity record, a
  missing identity record, HEAD drift, or a conflicting ref for the same issue
  all fail closed without mutation.
- Locked worktrees are **never** taken over, and stale metadata is **never**
  pruned. Both hand off to the Workflow Scheduler cleanup and lease lifecycle.

## Safe return to `main`

The primary checkout is untouched, so returning is `cd ~/agent-os`. Removing a
finished worktree is out of scope: request removal through the Workflow
Scheduler cleanup lifecycle.

## Relationship to other work

`ao checkout` in `$HOME/bin` is a local convenience wrapper only. This script
and `tests/test_prepare_issue_worktree.py` define the reusable contract.
`#330` stays authoritative for the concurrency ladder and Scheduler worktree
lifecycle; this command adds no concurrency. `#749` may consume preparation
evidence without gaining execution authority. `#726` is unchanged by it. `#722`
must obtain separate authorization before acting on preparation evidence.

Tests: `tests/test_prepare_issue_worktree.py`, run by `./scripts/validate-all.sh`.
