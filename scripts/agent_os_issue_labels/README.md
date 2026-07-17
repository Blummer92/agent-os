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

## Boundary

This checker is report-only. It does not call GitHub, apply labels, remove
labels, replace labels, post comments, or touch external systems.

Future workflow integration should call this CLI as a thin wrapper in
report-only mode before any additive label application is considered.
