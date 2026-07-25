# Agent OS Issue Label Checker

Local, fixture-first tooling for issue taxonomy evidence, safe label planning, and deterministic offline issue-draft previews.

## Local checker

```bash
python -m scripts.agent_os_issue_labels.cli \
  --issue tests/agent_os_issue_labels/fixtures/issue_ready.md \
  --labels tests/agent_os_issue_labels/fixtures/labels_ready.txt
```

The checker reads issue-form output and the declarative label map, compares expected and supplied labels, and renders an IA-style report.

## Offline issue draft preview

The preview path reads the canonical issue form as its schema contract, accepts structured YAML or JSON, renders title/body in form order, and reuses the existing label and acceptance-report logic.

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
  prior-scope-review: Reviewed issue 599 and issue 600.
  documentation-impact: docs-not-required
  documentation-exemption-reason: No documented behavior changes.
  validation: pytest and compileall
  dependencies: none
  acceptance: deterministic output and no writes
  safety:
    - No direct push to main, automatic merge, or autonomous issue closure is authorized.
    - No production, governed-field, source-of-truth, sharing, or external-system write is authorized without explicit approval.
    - Final implementation reporting will include files changed, tests run, docs updated, blockers, handoffs, and remaining risks.
```

Preview a file or stdin:

```bash
python -m scripts.agent_os_issue_labels.draft_cli \
  --input tests/agent_os_issue_labels/fixtures/issue_draft/valid_tier0.yml

cat draft.yml | python -m scripts.agent_os_issue_labels.draft_cli \
  --input - --format json
```

Output is deterministic for the same normalized input. Malformed input and duplicate mapping keys fail with exit code `1`. Missing required evidence, unsupported form elements, unknown fields/options, required checkbox omissions, `needs-decision` values, and external-write requests route explicitly to review.

Every result states `mutation_performed=false` and `write_authorized=false`. Preview or validation never authorizes issue creation, label or readiness mutation, implementation, merge, or another external write. Submission remains governed by issue #602.

## Application planner

```bash
python -m scripts.agent_os_issue_labels.plan_cli \
  --issue tests/fixtures/agent_os_issue_labels/tiered_ready.md \
  --labels tests/fixtures/agent_os_issue_labels/current_labels.txt \
  --available-labels tests/fixtures/agent_os_issue_labels/available_labels.txt \
  --issue-number 275 --event-type workflow_dispatch:manual --commit-sha local-test
```

The planner is side-effect free. It reports candidate and approved additions, existing and unavailable labels, owner evidence, unknown values, manual-review reasons, and explicit non-authorization fields. Only missing `agent-os` can be approved by the current policy. Owner, status, phase, epic, and type findings remain report-only.

## Read-only workflows

- `.github/workflows/agent-os-issue-label-report.yml` publishes checker evidence.
- `.github/workflows/agent-os-issue-label-apply-dry-run.yml` publishes an auditable application plan.

Neither workflow applies, removes, or replaces labels.

## Validation

```bash
python -m pytest \
  tests/agent_os_issue_labels/test_label_checker.py \
  tests/agent_os_issue_labels/test_acceptance_report_integration.py \
  tests/agent_os_issue_labels/test_issue_metadata.py \
  tests/agent_os_issue_labels/test_issue_draft.py \
  tests/agent_os_issue_labels/test_draft_cli.py
python -m compileall -q scripts/agent_os_issue_labels
./scripts/validate-all.sh
```

Label and draft findings reuse the IA2 `AcceptanceReport` model. They are evidence only and do not authorize merge, readiness, approval, source-of-truth, issue-state, or future live-write changes.
