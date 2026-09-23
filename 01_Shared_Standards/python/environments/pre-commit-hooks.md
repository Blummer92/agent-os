# Pre-commit Hooks

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black

  - repo: https://github.com/PyCQA/flake8
    rev: 6.0.0
    hooks:
      - id: flake8

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.0
    hooks:
      - id: mypy

  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
        args: ['--cov=src', '--cov-fail-under=80']
```

Install:

```bash
pip install pre-commit
pre-commit install
```

## Agent OS protected-branch safeguard

Agent OS uses a separate repository-local `pre-push` safeguard for the exact remote
ref `refs/heads/main`. It implements
`01_Shared_Standards/github/protected-branch-governance.md` by reference and does
not depend on the optional `pre-commit` framework configuration above.

Install or verify it from the repository root:

```bash
python scripts/protected_branch_push_guard.py install
python scripts/protected_branch_push_guard.py status
```

The installer sets local `core.hooksPath` to `.githooks` only when that setting is
unset or already uses `.githooks`. It refuses to replace another hooks path. The
checker parses Git's standard `pre-push` input, blocks exact updates and deletions
to `refs/heads/main`, and allows similarly named branches and tags.

Emergency recovery requires explicit repository-owner approval plus both variables:

```bash
AGENT_OS_ALLOW_PROTECTED_PUSH=1
AGENT_OS_PROTECTED_PUSH_REASON="approved recovery reason"
```

The safeguard emits a warning when that narrow bypass is used. `--no-verify` is
not authorization. Remove only the configuration installed by this tool with:

```bash
python scripts/protected_branch_push_guard.py remove
```

Local hooks are advisory and are not equivalent to GitHub rulesets or branch
protection. Windows operators should run these commands with Python 3 from Git
Bash; macOS, Linux, and Codespaces use the same entrypoint.
