# Agent OS Issue Label Checker

Local, fixture-first checker for issue taxonomy labels.

The checker reads the Agent OS issue form output and the declarative label map,
computes expected labels, compares them with fixture labels, and renders an
IA-style report.

## Local usage

```bash
python -m scripts.agent_os_issue_labels.cli \
  --issue tests/agent_os_issue_labels/fixtures/issue_ready.md \
  --labels tests/agent_os_issue_labels/fixtures/labels_ready.txt
```

## Acceptance report integration

Label findings are represented with the existing IA2 `AcceptanceReport` model and
rendered through the IA report shape. The checker adds label-specific checks such
as `label write boundary`, `label governance boundary`, `expected labels`, and
`label manual review` without creating a separate acceptance standard.

Label findings are evidence only. A pass, warning, or manual-review result from
this checker does not authorize merge, readiness changes, approval changes,
source-of-truth changes, or future additive label behavior.

## Report-only workflow

`.github/workflows/agent-os-issue-label-report.yml` runs this checker from issue
events. The workflow writes the issue body and current labels from the event
payload into local temporary files, calls the CLI, and publishes the report to
the job summary.

The workflow uses read-only permissions and does not apply, remove, or replace
labels. Additive label application remains a later review step.

## Boundary

This checker is report-only. It does not call GitHub, apply labels, remove
labels, replace labels, post comments, or touch external systems.

Future workflow integration should call this CLI as a thin wrapper in
report-only mode before any additive label application is considered.
