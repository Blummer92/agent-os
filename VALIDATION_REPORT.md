# Validation Report

## Current Baseline

- Review root: `Blummer92/agent-os`
- Baseline branch: `main`
- Scope: repository-wide validation after Cloud Build migration
- Primary command: `./scripts/validate-all.sh`
- Structural command: `bash 07_Agent_Tests/validate-repo-structure.sh`
- CI lane: Google Cloud Build using `cloudbuild.yaml`
- Compatibility workflow: `Agent OS Validation Gate` on GitHub-hosted `ubuntu-latest`
- Latest evidence: PR #218 Cloud Build `b68fb2a1-dea4-4989-9c0c-b86aa5464c63` passed

## Decision Record

| Decision | Current choice |
|---|---|
| Validation lane | Cloud Build PR trigger using `cloudbuild.yaml` |
| GitHub Actions role | Lightweight compatibility notice |
| Source of truth | GitHub repository files; Google Cloud Build is execution only |
| Trigger mode | GitHub-connected PR trigger plus manual `/gcbrun` when needed |
| Build image | `python:3.11` |
| Secrets | None stored in repository |
| Logs | Cloud Build History |
| Rollback | Revert `cloudbuild.yaml` or disable the Cloud Build trigger |

## Cloud Build Commands

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

`07_Agent_Tests/validate-repo-structure.sh` runs seven checks:

1. Non-exempt Markdown files, except `CLAUDE.md`, are under 100 lines.
2. Every overlay references `_common-overlay-rules.md`.
3. No filename collisions exist between `00_Governance/` and `04_Registry/`, except each folder's own `README.md`.
4. Every registered agent has a matching overlay file.
5. Every agent test file has a matching overlay.
6. Every overlay has a matching test file.
7. Documentation Dependency Map metadata paths exist.

Expected clean result: 7 passed, 0 failed.

## Aggregate Validation Coverage

`scripts/validate-all.sh` runs structural validation first, then discovers pytest suites and runs each Python test suite. It reports commands executed, check results, failed packages, overall status, and exit code.

## Cloud Build Smoke Tests

| ID | Smoke test | Status |
|---|---|---|
| CB-01 | Config parses and starts from `cloudbuild.yaml`. | Passing |
| CB-02 | Intended repository source is checked out. | Passing |
| CB-03 | Intended PR branch/ref is validated. | Passing |
| CB-04 | `requirements-dev.txt` installs. | Passing |
| CB-05 | Scheduler requirements install. | Passing |
| CB-06 | Materials Coach editable test deps install. | Passing |
| CB-07 | Notion Navigation Client editable test deps install. | Passing |
| CB-08 | Structural validation runs. | Passing |
| CB-09 | Aggregate validation runs. | Passing |
| CB-10 | Structural failures fail the build. | Documented |
| CB-11 | Pytest failures fail the build. | Documented |
| CB-12 | Passing validation returns exit code `0`. | Passing |
| CB-13 | Logs show exact commands. | Passing |
| CB-14 | Build output can be linked from PR reports. | Passing |
| CB-15 | No repository secrets are required. | Passing |
| CB-16 | No Notion, Drive, Sheets, Docs, Slides, Apps Script, memory, or classroom artifacts are modified. | Passing |
| CB-17 | Cloud Build does not mutate GitHub labels, PR state, issue state, or branch protection. | Passing |
| CB-18 | Failure output is actionable. | Passing |

## Current Evidence

- PR #217 merged the Cloud Build validation migration.
- PR #202 validated after PR #217 merged and its branch was refreshed.
- PR #218 Cloud Build succeeded with build `b68fb2a1-dea4-4989-9c0c-b86aa5464c63`.

## Boundaries

This report records validation evidence only. It does not authorize external writes, production writes, readiness-field changes, sharing changes, source-of-truth changes, GitHub label mutation, PR state mutation, branch protection changes, or automatic merging.

## Reproducibility

```bash
./scripts/validate-all.sh
```

For PRs, use Cloud Build from the GitHub-connected trigger and record the build ID in the PR report when available. Use `Agent OS Validation Gate` as a compatibility check, not as aggregate validation source.

## Remaining Follow-Up

- Decide separately whether Cloud Build should become a required branch-protection check.
- Keep Google Cloud trigger settings aligned with `cloudbuild.yaml`.
