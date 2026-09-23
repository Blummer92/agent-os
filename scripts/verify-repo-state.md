# verify-repo-state.sh

Reusable repository-state verifier. Prompts state the contract; this script
owns the Git operations, retries, validation, and evidence output. Policy is
referenced, not restated: see
`01_Shared_Standards/github/protected-branch-governance.md`.

Output, exit-code, and retry contracts are in
`scripts/verify-repo-state-contract.md`.

## Syntax

```bash
scripts/verify-repo-state.sh [--create-from-base] <branch> [base]
```

- `<branch>` — target branch, short name (no `refs/` prefix). Required.
- `[base]` — base branch for changed-file evidence. Defaults to `main`.
- `--create-from-base` — permit creating a missing `<branch>` from
  `origin/<base>`.

Arguments are validated before any repository state changes.

## What it does

Rejects uncommitted tracked changes; fetches `origin` once with bounded
retries; resolves the branch from local refs (no second network call);
switches, creating a tracking branch when the branch is remote-only;
fast-forwards from the already-fetched `origin/<branch>`; validates the base
ref; prints evidence.

It never pushes, resets, rebases, stashes, cleans, force-updates, or deletes.

## Branch-creation policy

A missing branch fails with exit 5. Branches are created **only** when
`--create-from-base` is passed explicitly — there is no implicit creation and
no correction of misspelled branch names. Creation requires `origin/<base>` to
exist, is local-only (nothing is pushed), and never applies to a branch that
already exists locally or on `origin`.

The base resolves solely as `origin/<base>`; a local-only base is not accepted,
so base resolution is unambiguous.

## Dirty-tree policy

- **Tracked modifications** (staged or unstaged) block the run — exit 3. The
  gate and its diagnostic both use `--untracked-files=no`, so they always agree.
- **Untracked files** are permitted, listed on stderr as a non-blocking note,
  and never modified.
- **Ignored files** are permitted and never inspected or reported.

User work is never discarded.

## Examples

```bash
# Exists locally and on origin: switch, fast-forward, report.
scripts/verify-repo-state.sh claude/repo-state-verification-ylt28e

# Remote-only: an explicit local tracking branch is created.
scripts/verify-repo-state.sh agent/602-gh-issue-create-adapter main

# Local-only: verified and reported; no remote fast-forward occurs.
scripts/verify-repo-state.sh local/experiment

# Missing: fails with exit 5 unless creation is explicitly permitted.
scripts/verify-repo-state.sh --create-from-base agent/700-new-work main
```

## Known limitations

- Assumes the remote is `origin` and that `<branch>` maps to `origin/<branch>`;
  a differently named upstream is not consulted.
- Single-branch clones lack remote-tracking refs; reported as an incomplete
  refspec, not as a missing branch.
- Shallow clones may have no merge base; fails with exit 8 rather than
  reporting misleading changed-file evidence.

Tests: `tests/test_verify_repo_state.py`, run by `./scripts/validate-all.sh`.
