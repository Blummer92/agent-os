# Agent OS Scripts

Runnable repository-level scripts. Python packages in this directory are
documented by their own modules and the reusable capability registry
(`04_Registry/reusable-capabilities.yml`).

## verify-repo-state.sh

Reusable repository-state verifier. It replaces the Git preflight block that
was previously pasted into Agent OS prompts: prompts now state the contract
("verify branch X against base Y") while the script owns the Git operations,
retries, validation, and evidence output.

```bash
scripts/verify-repo-state.sh [--create-from-base] <branch> [base]
```

Usage, branch-creation policy, dirty-tree policy, examples, and known
limitations are documented in `scripts/verify-repo-state.md`. The stdout
evidence format, stderr logging contract, exit codes, and retry behavior are in
`scripts/verify-repo-state-contract.md`.

Tests: `tests/test_verify_repo_state.py`.

## validate-all.sh

Aggregate local validation runner: structural validation plus every discovered
pytest suite.

```bash
./scripts/validate-all.sh
```

## protected_branch_push_guard.py

Local advisory guard against pushes to protected branches, installed as a
`pre-push` hook. Policy lives in
`01_Shared_Standards/github/protected-branch-governance.md`.
