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

## Offline issue draft preview

The draft preview path consumes structured YAML or JSON, reads the canonical
issue form as its schema contract, renders the issue title and Markdown body in
form order, and reuses the existing label and acceptance-report logic.

Input uses exactly two top-level keys:

```yaml
title: Deterministic preview
fields:
  tier: tier:0-small-maintenance
  objective: Build a deterministic preview.
  owner: owner:github-service-agent
  readiness: status:ready
  source-of-truth: GitHub
  external-write: no-external-write
  scope: Preview only
  files: scripts/agent_os_issue_labels
  prior-scope-review: Reviewed #599 and #600.
  documentation-impact: docs-not-required
  documentation-exemption-reason: No documentation behavior changes.
  validation: pytest and compileall
  dependencies: none
  acceptance: deterministic output and no writes
  safety:
    - No direct push to main, automatic merge, or autonomous issue closure is authorized.
    - No production, governed-field, source-of-truth, sharing, or external-system write is authorized without explicit approval.
    - Final implementation reporting will include files changed, tests run, docs updated, blockers, handoffs, and remaining risks.
```

Preview a file:

```bash
python -m scripts.agent_os_issue_labels.draft_cli \
  --input tests/agent_os_issue_labels/fixtures/issue_draft/valid_tier0.yml
```

Preview stdin as stable JSON:

```bash
cat tests/agent_os_issue_labels/fixtures/issue_draft/valid_tier0.yml | \
  python -m scripts.agent_os_issue_labels.draft_cli \
    --input - \
    --format json
```

The same normalized input always produces the same title, body, proposed-label
ordering, status, and serialized output. Duplicate mapping keys and malformed
structured input fail with exit code `1`. A structurally parseable draft that
needs human judgment returns `manual-review` through the shared status model and
retains the existing non-failing acceptance exit-code behavior.

Unsupported form elements, unknown fields or options, missing required fields,
missing required checkbox confirmations, `needs-decision` values, and external
write requests are reported explicitly. They are never silently ignored.

Every preview states:

- `mutation_performed=false`;
- `write_authorized=false`.

A successful preview or validation result does not authorize issue creation,
label mutation, readiness changes, implementation, merge, or any external
write. GitHub submission remains a separate governed capability under #602.

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

## Validation

Changes must pass the executable `Agent OS Validation Gate`, which runs repository
structure validation and `scripts/validate-all.sh` against the pull-request merge
result. Focused planner tests and Python compilation remain required evidence,
but they do not replace aggregate validation.

Focused draft validation:

```bash
python -m pytest \
  tests/agent_os_issue_labels/test_label_checker.py \
  tests/agent_os_issue_labels/test_acceptance_report_integration.py \
  tests/agent_os_issue_labels/test_issue_metadata.py \
  tests/agent_os_issue_labels/test_issue_draft.py \
  tests/agent_os_issue_labels/test_draft_cli.py

python -m compileall -q scripts/agent_os_issue_labels
```

## Acceptance-report integration

Label findings use the existing IA2 `AcceptanceReport` model. They are evidence
only and do not authorize merge, readiness changes, approval changes,
source-of-truth changes, issue closure, or future live label behavior.

## Boundary

The checker, planner, and draft preview perform no GitHub API writes and touch no
external systems. Live issue submission and live additive label application
remain separately approved follow-ups.
