# Agent OS Issue Acceptance Checker

Fixture-first checker for IA2. It evaluates local issue, PR, changed-file, and
diff inputs against the IA1 issue acceptance standard.

## Local usage

```bash
python -m scripts.agent_os_issue_acceptance.cli \
  --issue tests/agent_os_issue_acceptance/fixtures/issue_valid.md \
  --pr-body tests/agent_os_issue_acceptance/fixtures/pr_body_valid.md \
  --changed-files tests/agent_os_issue_acceptance/fixtures/changed_files_valid.txt \
  --diff tests/agent_os_issue_acceptance/fixtures/diff_clean.patch
```

## Workflow rollout

This v1 is intentionally local and fixture-first. A thin GitHub Actions wrapper
can call the CLI after PR/issue payload collection is approved. The checker does
not require external credentials, Notion, Google Drive, Sheets, Docs, Apps Script,
or production systems.
