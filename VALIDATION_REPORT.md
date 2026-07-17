# Validation Report

## Current Baseline

- Review root: `Blummer92/agent-os`
- Baseline branch: `main`
- Scope: Agent OS repository-wide validation after Cloud Build migration
- Primary command: `./scripts/validate-all.sh`
- Structural command: `bash 07_Agent_Tests/validate-repo-structure.sh`
- CI lane: Google Cloud Build using repository `cloudbuild.yaml`
- Compatibility workflow: `Agent OS Validation Gate` on GitHub-hosted `ubuntu-latest`
- Latest evidence used for this refresh: PR #218 Cloud Build build `b68fb2a1-dea4-4989-9c0c-b86aa5464c63` passed

## Decision Record

| Decision | Current choice | Rationale |
|---|---|---|
| Validation lane | Cloud Build PR trigger using `cloudbuild.yaml` | Keeps validation off the retired self-hosted runner and reuses repository scripts. |
| GitHub Actions role | Lightweight compatibility notice | Prevents stale queued checks while preserving the familiar `Agent OS Validation Gate` surface. |
| Source of truth | GitHub repository files | Google Cloud Build is execution only. GitHub remains canonical for validation configuration. |
| Trigger mode | GitHub-connected Cloud Build PR trigger, plus manual `/gcbrun` when needed | Supports PR branch validation and explicit reruns. |
| Build image | `python:3.11` | Matches the current repository validation lane. |
| Secrets | None stored in repository | Validation installs repository dependencies and runs local tests. |
| Logs | Cloud Build History | Build logs provide command-level evidence and failure details. |
| Rollback | Revert `cloudbuild.yaml` or disable the Cloud Build trigger | Keeps rollback scoped to CI configuration. |

## Cloud Build Validation Commands

`cloudbuild.yaml` runs these commands:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -r 08_Tooling/workflow-scheduler/requirements.txt
python -m pip install -e "./08_Tooling/instructional-materials-coach[test]"
python -m pip install -e "./08_Tooling/notion-navigation-client[test]"
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

## Structural Validation Checks

`07_Agent_Tests/validate-repo-structure.sh` currently runs seven checks:

1. All non-exempt Markdown files, except `CLAUDE.md`, are under 100 lines.
2. Every overlay references `_common-overlay-rules.md`.
3. No filename collisions exist between `00_Governance/` and `04_Registry/`, except each folder's own `README.md`.
4. Every registered agent has a matching overlay file.
5. Every agent test file has a matching overlay.
6. Every overlay has a matching test file.
7. All Documentation Dependency Map metadata paths exist.

Expected structural result on a clean baseline: 7 passed, 0 failed.

## Aggregate Validation Coverage

`scripts/validate-all.sh` runs structural validation first, then discovers pytest test directories and runs each Python test suite. The runner reports commands executed, check results, failed packages, overall status, and exit code.

Current package suites are discovered from repository `tests/` directories with Python test files. Suites with `src/` are run with `PYTHONPATH=src`; root tests run from the repository root.

## Cloud Build Smoke-Test Checklist

| ID | Smoke test | Evidence expectation | Status |
|---|---|---|---|
| CB-01 | Cloud Build config parses successfully. | Build starts from `cloudbuild.yaml`. | Passing |
| CB-02 | Cloud Build checks out the intended repository source. | Build log shows `Blummer92/agent-os` source checkout. | Passing |
| CB-03 | Cloud Build validates the intended PR branch/ref. | Build log shows the PR branch head SHA. | Passing |
| CB-04 | Cloud Build installs `requirements-dev.txt`. | Build log includes the install command. | Passing |
| CB-05 | Cloud Build installs Scheduler requirements. | Build log includes `08_Tooling/workflow-scheduler/requirements.txt`. | Passing |
| CB-06 | Cloud Build installs Materials Coach editable test deps. | Build log includes `instructional-materials-coach[test]`. | Passing |
| CB-07 | Cloud Build installs Notion Navigation Client editable test deps. | Build log includes `notion-navigation-client[test]`. | Passing |
| CB-08 | Structural validation runs. | Build log includes `bash 07_Agent_Tests/validate-repo-structure.sh`. | Passing |
| CB-09 | Aggregate validation runs. | Build log includes `./scripts/validate-all.sh`. | Passing |
| CB-10 | Structural validation failures fail the build. | Structural script returns nonzero and Cloud Build exits nonzero. | Documented |
| CB-11 | Pytest failures fail the build. | `validate-all.sh` returns nonzero and Cloud Build exits nonzero. | Documented |
| CB-12 | Passing validation returns exit code `0`. | Successful Cloud Build completes without failed steps. | Passing |
| CB-13 | Logs show exact commands executed. | Cloud Build step output includes install and validation commands. | Passing |
| CB-14 | Build output can be linked from PR reports. | Build ID can be recorded in PR evidence. | Passing |
| CB-15 | No repository secrets are required. | `cloudbuild.yaml` has no secret references. | Passing |
| CB-16 | No Notion, Drive, Sheets, Docs, Slides, Apps Script, memory, or classroom artifacts are modified. | Build runs local validation commands only. | Passing |
| CB-17 | Cloud Build does not mutate GitHub labels, PR state, issue state, or branch protection. | Build config has no GitHub write steps. | Passing |
| CB-18 | Failure output is actionable. | `validate-all.sh` reports failed packages, commands, status, and exit code. | Passing |

## Current Evidence

- PR #217 merged the Cloud Build validation migration.
- PR #202 validated successfully after PR #217 was merged and its branch was refreshed.
- PR #218 Cloud Build succeeded with build `b68fb2a1-dea4-4989-9c0c-b86aa5464c63`.

## Boundaries

This report records validation evidence only. It does not authorize issue-to-PR automation, live Google Drive writes, Notion writes, production writes, readiness-field changes, sharing changes, source-of-truth changes, GitHub label mutation, PR state mutation, branch protection changes, or automatic merging.

## Reproducibility

To reproduce the current local validation baseline from a clean checkout:

```bash
./scripts/validate-all.sh
```

For pull requests, use Cloud Build validation from the GitHub-connected trigger and record the build ID in the PR report when available. Use the `Agent OS Validation Gate` GitHub Actions workflow as a compatibility check, not as the aggregate validation source.

## Remaining Follow-Up

- Confirm whether Cloud Build should become a required branch-protection check in a separate approved policy change.
- Keep Google Cloud trigger settings aligned with repository `cloudbuild.yaml`.
- Document any future timeout, log bucket, or service-account changes in the relevant CI operations note.
