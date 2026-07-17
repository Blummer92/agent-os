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

The command runs the structural repository checks in `07_Agent_Tests/validate-repo-structure.sh` and every discovered Python pytest suite outside template folders. It prints the commands executed, check results, failed packages, overall status, and exit code.

Exit codes:

- `0` means all structural checks and pytest suites passed.
- `1` means one or more structural checks or pytest suites failed.
- `2` means the runner could not start because of invalid invocation, missing prerequisites, or an unrecoverable runner error.

### Cloud Build Validation

Cloud Build is the current practical PR validation lane for Agent OS. It runs from the repository-owned `cloudbuild.yaml` file and reuses the same validation scripts instead of duplicating validation logic.

The Cloud Build lane installs repository test dependencies, runs `bash 07_Agent_Tests/validate-repo-structure.sh`, and then runs `./scripts/validate-all.sh`.

Cloud Build is an execution surface only. GitHub remains the source of truth for Agent OS governance, standards, overlays, registry files, templates, tests, workflows, and release notes.

Use GitHub pull requests as the control surface. Use Google Cloud Build History when deeper build logs are needed or when a `/gcbrun` trigger comment must be verified.

### GitHub Actions Validation

The `Agent OS Validation Gate` GitHub Actions workflow is a lightweight compatibility check. It no longer depends on the retired self-hosted `agent-os` runner. Its job is to prevent stale queued checks while directing reviewers to the Cloud Build PR trigger and `cloudbuild.yaml` validation lane.

The workflow does not commit, push, open pull requests, write to Google Drive, modify source-of-truth records, mutate GitHub labels, or change PR readiness.

Issue-to-PR automation is not part of this validation workflow.

## Safe Change Workflow

Agent OS changes should use a branch-first workflow instead of direct pushes to `main`:

```text
branch -> pull request -> validation -> merge -> main
```

This keeps `main` protected as the source-of-truth branch while Cloud Build validates pull requests and merged changes.

Typical workflow:

1. Create a non-main branch for the change.
2. Commit only related files.
3. Open a pull request into `main`.
4. Trigger or review Cloud Build validation.
5. Review the change and validation results.
6. Merge the pull request after validation evidence is available.

Use GitHub pull requests as the control surface. Use Google Cloud Build History only when deeper build logs are needed.
