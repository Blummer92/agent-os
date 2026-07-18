# Agent OS Issue Label Checker

Local, fixture-first tooling for issue taxonomy evidence and safe application
planning.

The checker reads Agent OS issue-form output and the declarative label map,
computes expected labels, compares them with supplied labels, and renders an
IA-style report.

## Local checker

```bash
python -m scripts.agent_os_issue_labels.cli \
  --issue tests/agent_os_issue_labels/fixtures/issue_ready.md \
  --labels tests/agent_os_issue_labels/fixtures/labels_ready.txt
```

## Application planner

The planner is side-effect free. It consumes an issue body, current labels, and
an explicit repository-label catalog, then reports:

- metadata contract and application eligibility;
- candidate and approved additions;
- expected labels already present;
- findings skipped by policy;
- primary-owner and participation-label evidence;
- unknown values and unavailable labels;
- reasons requiring manual review;
- explicit non-authorization fields.

```bash
python -m scripts.agent_os_issue_labels.plan_cli \
  --issue tests/fixtures/agent_os_issue_labels/tiered_ready.md \
  --labels tests/fixtures/agent_os_issue_labels/current_labels.txt \
  --available-labels tests/fixtures/agent_os_issue_labels/available_labels.txt \
  --issue-number 275 \
  --event-type workflow_dispatch:manual \
  --commit-sha local-test
```

The initial application policy can approve only missing `agent-os`. The issue
body remains authoritative for the Primary owner. Existing `owner:*` labels are
non-exclusive participation evidence and remain report-only until a separately
approved taxonomy change defines writable owner semantics.

Every `status:*`, phase, epic, and type finding remains report-only. Recognized
legacy bodies remain parseable for evidence, but are not application-eligible
and produce no approved additions. Incomplete or unknown metadata contracts
route to manual review.

Malformed metadata, unknown values, unavailable safe labels, external-write
signals, and needs-decision values route to manual review. A manual-review plan
contains no approved additions.

Every text and JSON plan states that no mutation occurred, no write is
authorized, L5B is not authorized, and explicit approval is still required.

## Read-only workflows

`.github/workflows/agent-os-issue-label-report.yml` runs the checker from issue
events and publishes its IA-style report.

`.github/workflows/agent-os-issue-label-apply-dry-run.yml` reads the selected
issue and repository-label catalog, calls the application planner, and publishes
an auditable dry-run summary. It supports opened, edited, reopened, and manual
dispatch events, uses read-only permissions, and has per-issue concurrency.

Neither workflow applies, removes, or replaces labels.

## Acceptance-report integration

Label findings use the existing IA2 `AcceptanceReport` model. They are evidence
only and do not authorize merge, readiness changes, approval changes,
source-of-truth changes, issue closure, or future live label behavior.

## Boundary

The checker and planner perform no GitHub API writes and touch no external
systems. Live additive application remains a separately approved follow-up.
