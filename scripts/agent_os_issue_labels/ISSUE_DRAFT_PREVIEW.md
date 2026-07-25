# Issue Draft Preview

## Purpose

Render structured local input through the canonical Agent OS issue form before
any GitHub submission is considered. The preview performs no network call,
subprocess execution, label mutation, issue creation, or authorization decision.

## Command

```bash
python -m scripts.agent_os_issue_labels.draft_cli \
  --input tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json
```

Use `--input -` to read the same JSON object from standard input. Add
`--format json` for deterministic machine-readable output.

## Input

The top-level object contains `title` and `fields`:

```json
{
  "title": "Add deterministic preview",
  "fields": {
    "tier": "tier:1-standard-implementation",
    "objective": "Describe the outcome",
    "owner": "owner:github-service-agent",
    "readiness": "status:ready"
  }
}
```

Field keys may use the raw form ID or its existing canonical alias. Supplying
both forms of the same canonical field routes the result to manual review.
Values may be a string, a list of strings, or `null`. Multiline strings and
Unicode are preserved after line-ending normalization.

## Rendering

- The issue title receives the form's configured prefix exactly once.
- Body sections follow the issue-form order.
- Missing fields render as `_No response_`.
- Checkbox options render in schema order with explicit selected state.
- Proposed labels come from the existing declarative label map.
- Form default labels, assignees, type, and projects remain separate evidence.

Unsupported controls, unknown fields or options, missing required inputs,
required unchecked boxes, invalid input types, and duplicate aliases appear as
manual-review evidence rather than being silently ignored.

## Output Boundary

Text and JSON outputs derive from the same immutable result. Both include:

- title and canonical Markdown body;
- metadata-contract classification;
- proposed label evidence;
- form metadata evidence;
- manual-review reasons;
- the reused issue-acceptance report;
- `mutation_performed=false`;
- `write_authorized=false`.

A `pass` preview proves deterministic local formatting only. It does not prove
readiness, approval, correctness, merge authorization, or permission to create
or modify an issue. See the repository write-authorization and protected-branch
standards for the governing boundaries.

## Validation

Run the focused draft, checker, planner, and acceptance-integration tests, then
run `bash 07_Agent_Tests/validate-repo-structure.sh` and
`./scripts/validate-all.sh`.
