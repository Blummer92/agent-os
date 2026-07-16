# Agent OS

Agent OS is a modular knowledge base for engineering-agent standards, governance rules, reusable templates, registry maps, examples, and archive notes.

## Start Here

- `AGENTS.md` — execution entry point and global routing.
- `00_Governance/documentation-dependency-map.md` — documentation index: what exists, who owns it, and recommended reading paths before you build or modify Agent OS.

## Main Folders

- `00_Governance/`
- `01_Shared_Standards/`
- `02_Agent_Overlays/`
- `03_Templates/`
- `04_Registry/`
- `05_Examples/`
- `06_Archive/`
- `07_Agent_Tests/`

## Validation

Run the aggregate local validation command from the repository root:

```bash
./scripts/validate-all.sh
```

Cloud Build also runs repository validation from `cloudbuild.yaml` when configured on the Google Cloud trigger.

The command runs the structural repository checks in `07_Agent_Tests/validate-repo-structure.sh` and every discovered Python pytest suite outside template folders. It prints the commands executed, check results, failed packages, overall status, and exit code.

Exit codes:

- `0` means all structural checks and pytest suites passed.
- `1` means one or more structural checks or pytest suites failed.
- `2` means the runner could not start because of invalid invocation, missing prerequisites, or an unrecoverable runner error.

## Safe Change Workflow

Agent OS changes should use a branch-first workflow instead of direct pushes to `main`:

```text
branch -> pull request -> validation -> merge -> main
```

This keeps `main` protected as the source-of-truth branch while still allowing Cloud Build to run automatically after merges to `main`.

Typical workflow:

1. Create a non-main branch for the change.
2. Commit only related files.
3. Open a pull request into `main`.
4. Review the change and validation results.
5. Merge the pull request.
6. Let Cloud Build validate the resulting `main` push automatically.

Use GitHub pull requests as the control surface. Use Google Cloud Build History only when deeper build logs are needed.

<!-- Cloud Build visible PR check test -->

### GitHub Actions Validation

The `Agent OS Validation Gate` workflow runs the same aggregate validation command for pull requests targeting `main`.

The workflow runs on the self-hosted Agent OS runner labeled `agent-os`, not on GitHub-hosted runner minutes. It can also be started manually with `workflow_dispatch` and runs a weekday scheduled validation check on that same self-hosted runner.

The workflow is validation-only: it checks out the repository, installs test dependencies, and runs `./scripts/validate-all.sh`. It does not commit, push, open pull requests, write to Google Drive, or modify source-of-truth records.

Issue-to-PR automation is not part of this validation workflow.
