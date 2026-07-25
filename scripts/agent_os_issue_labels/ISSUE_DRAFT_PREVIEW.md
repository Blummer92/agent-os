# Issue Draft Preview and Validation

## Purpose

Render structured input through the canonical Agent OS issue form and apply
deterministic offline validation. No network request, subprocess, issue creation,
label change, or other mutation occurs.

## Command

```bash
python -m scripts.agent_os_issue_labels.draft_cli \
  --input tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json
```

Use `--input -` for stdin and `--format json` for machine output. Repeat
`--available-label` only for a complete local label set. Repeat
`--candidate-summary` for local advisory duplicate evidence.

## Immutable result

Text and JSON derive from one `IssueDraftValidationResult` containing status,
ordered reason codes, `format_valid`, `submission_eligible`, parser/schema/
duplicate evidence, a normalized report, `write_authorized=false`, and
`mutation_performed=false`.

```text
valid preview != readiness != approval != write authorization
```

## Reason codes

| Code | Outcome |
|---|---|
| `eligible-valid` | pass |
| `eligible-warning` | warning |
| `missing-required-evidence` | manual review |
| `malformed-structured-input` | failure |
| `unknown-or-unsupported-value` | manual review |
| `duplicate-raw-or-canonical-field` | manual review |
| `unavailable-label` | manual review |
| `conflicting-owner-evidence` | manual review |
| `unsafe-external-write-request` | failure |
| `parser-round-trip-ambiguity` | manual review |
| `unsupported-or-drifted-issue-form-schema` | manual review |
| `duplicate-local-candidate-advisory` | warning |

## Exit codes

| Exit | Symbol | Meaning |
|---:|---|---|
| `0` | `ELIGIBLE_SUCCESS` | eligible success |
| `10` | `ELIGIBLE_WARNING` | eligible warning |
| `20` | `MANUAL_REVIEW` | human decision required |
| `30` | `VALIDATION_FAILURE` | hard validation failure |
| `64` | `INVALID_INPUT_OR_USAGE` | invalid input or usage |

Manual review is non-zero. Future #602 outcomes use separate codes.

## Fail-closed evidence

`parse_issue_form_body()` remains the only Markdown parser. Source values,
rendered Markdown, and parsed output are compared. Canonical-looking `###`
headings, duplicate headings, missing/unexpected fields, or changed values emit
`parser-round-trip-ambiguity` and block submission eligibility.

The local form is checked for unsupported controls, attributes, validation
shapes, malformed or duplicate options, duplicate raw/canonical IDs, duplicate
labels, malformed body entries, and unsupported top-level keys. Drift routes to
manual review and never edits the form.

Duplicate evidence uses only supplied local summaries and normalized exact-title
matching. It is advisory and performs no search or issue mutation.

## Write boundary and #602 handoff

Every result preserves:

```text
write_authorized=false
mutation_performed=false
```

Validation, readiness, and passing checks remain evidence only. #602 may consume
only a merged result with `submission_eligible=true`, must reuse these reason and
exit contracts, and must add its separately reviewed confirmation and command
boundary. #601 does not submit an issue.

## Validation

Run focused draft and validation tests, checker and planner regressions, Python
compilation, `bash 07_Agent_Tests/validate-repo-structure.sh`, and
`./scripts/validate-all.sh`.
