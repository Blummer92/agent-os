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

Use `--format json` for stable machine-readable report fields.

## Linked-issue parsing

The checker resolves a linked issue only when exactly one unique same-repository
target is introduced by a supported explicit closing keyword.

Supported keywords are case-insensitive:

- `close`, `closes`, `closed`
- `fix`, `fixes`, `fixed`
- `resolve`, `resolves`, `resolved`

Both whitespace and optional-colon forms are supported, for example
`Closes #223` and `Closes: #223`.

The parser returns one of three states:

- `resolved`: exactly one unique supported explicit target exists;
- `none`: no issue-like references exist;
- `manual-review`: issue references exist, but one authoritative target cannot be
  proven safely.

Bare references such as `#223` or `Related to #223` are non-authoritative. They
do not override one supported explicit target. Bare-only references require
manual review. Repeated explicit references to the same target are deduplicated,
while multiple unique explicit targets and conflicting title/body targets require
manual review.

`Addresses #223` is not an authoritative closing phrase. Repository-qualified
targets such as `owner/repository#223` preserve repository identity and require
manual review until cross-repository issue evaluation is supported end to end.

A small deterministic Markdown masking step prevents references found only in
fenced code, inline code, blockquotes, or HTML comments from silently becoming
authoritative. This is intentionally not a full Markdown parser; uncertain future
contexts should route to manual review rather than adding heuristic confidence
scoring.

`parse_linked_issue()` remains as a lossy compatibility wrapper. It returns an
integer only for `resolved` and returns `None` for both `none` and
`manual-review`. Critical IA2 consumers use `parse_linked_issue_result()` so those
states remain distinct in checks, text reports, and JSON output.

The text report includes `Linked issue status`. JSON output preserves the existing
`linked_issue` field and adds `linked_issue_status`, `linked_issue_reasons`, and
`linked_issue_candidates`.

Outcome meaning and authorization boundaries remain governed by
`01_Shared_Standards/github/issue-acceptance-automation.md`.

## Metadata validation

`metadata_validation.py` evaluates MD2A fixture evidence offline and report-only.
It returns only `pass`, `warn`, `fail`, or `manual-review` checks and never edits
issues, labels, templates, readiness fields, workflows, or external systems.

## Bounded issue scanning

`issue_scanner.py` converts complete paginated issue retrieval into provenance-
preserving scanner records for later report-only counts. It is offline-testable,
fails closed when pagination or required fields are incomplete, and does not edit
issues, labels, readiness fields, templates, workflows, or external systems.

## Workflow rollout

The checker remains local and fixture-first. PR #227 currently owns the proposed
report-only GitHub Actions wrapper and is not yet merged into `main`. Workflow
caller migration is therefore deferred: after that workflow lands, it must use
the structured parser result, perform issue lookup only for a resolved
same-repository target, and retain read-only/report-only behavior.

The checker does not require external credentials, Notion, Google Drive, Sheets,
Docs, Apps Script, or production systems.
