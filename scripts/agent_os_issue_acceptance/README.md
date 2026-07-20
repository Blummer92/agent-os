# Agent OS Issue Acceptance Checker

Fixture-first, report-only checks for local issue, pull-request, changed-file, and
diff evidence under the Agent OS issue-acceptance standard.

## Local usage

```bash
python -m scripts.agent_os_issue_acceptance.cli \
  --issue tests/agent_os_issue_acceptance/fixtures/issue_valid.md \
  --pr-body tests/agent_os_issue_acceptance/fixtures/pr_body_valid.md \
  --changed-files tests/agent_os_issue_acceptance/fixtures/changed_files_valid.txt \
  --diff tests/agent_os_issue_acceptance/fixtures/diff_clean.patch
```

Use `--format json` for stable machine-readable report fields.

## Canonical IssuePlan scanning

`issueplan_scanner.py` is the only acceptance-block candidate discovery and YAML
parsing implementation. It scans all candidates before classification and keeps
source identity, source revision, candidate multiplicity, malformed candidates,
unknown governed fields, profile compatibility, and identity findings distinct.

`parse_issue_metadata()` remains a temporary lossy compatibility facade. It calls
the canonical scanner and projects only one safe candidate into `IssueMetadata`.
It contains no regex, fenced-block, or YAML parser of its own.

Compatibility behavior is fail-closed:

- no candidate remains ordinary missing metadata;
- malformed, duplicate-identical, and conflicting candidates remain distinct;
- partial, inaccessible, unsupported, or stale sources remain distinct;
- unknown governed fields and unsupported versions are not coerced;
- unsafe findings carry bounded `issueplan-scanner:*` manual-review reasons;
- scanner validity, readiness, labels, and approvals never authorize execution.

Policy, readiness, IA5 documentation readiness, and legacy preflight consume this
scanner-backed evidence. Markdown headings remain a separate human-readable input
where their existing contracts require them; they do not rediscover YAML blocks.
Removal of the compatibility facade requires a separately governed public-API
migration after all callers consume scanner results directly.

## Linked-issue parsing

The checker resolves a linked issue only when exactly one unique same-repository
target is introduced by a supported explicit closing keyword.

Supported case-insensitive keywords are `close`, `closes`, `closed`, `fix`,
`fixes`, `fixed`, `resolve`, `resolves`, and `resolved`. Whitespace and optional
colon forms are supported, such as `Closes #223` and `Closes: #223`.

The structured parser returns:

- `resolved`: exactly one unique supported explicit target;
- `none`: no issue-like references;
- `manual-review`: references exist but one authoritative target is not proven.

Bare references and `Addresses #223` are non-authoritative. Fenced code, inline
code, blockquotes, and HTML comments are masked before resolution.
`parse_linked_issue()` remains a lossy wrapper; critical consumers use
`parse_linked_issue_result()`.

## Metadata and issue scanning

`metadata_validation.py` evaluates MD2A fixture evidence offline and report-only.
It never edits issues, labels, readiness fields, workflows, or external systems.

`issue_scanner.py` converts complete paginated retrieval into provenance-preserving
records. `issue_scan_cli.py` provides an explicit local GitHub runner:

```bash
python -m scripts.agent_os_issue_acceptance.issue_scan_cli --repository OWNER/REPO
```

Incomplete retrieval exits nonzero. The runner performs no issue or label writes.

## Workflow boundary

The merged report-only workflow consumes structured linked-issue and acceptance
evidence. It performs issue lookup only for a resolved same-repository target and
keeps all findings non-authoritative.

Outcome meaning remains governed by
`01_Shared_Standards/github/issue-acceptance-automation.md`. The package requires
no Notion, Drive, Sheets, Docs, Apps Script, production credentials, or external
write access.
