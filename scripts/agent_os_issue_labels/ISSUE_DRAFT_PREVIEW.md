# Issue Draft Preview and Validation

## Purpose

Render structured input through the canonical Agent OS issue form and apply
deterministic offline validation. The command performs no network request,
subprocess execution, issue creation, label change, or other mutation.

## Command

```bash
python -m scripts.agent_os_issue_labels.draft_cli \
  --input tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json
```

Use `--input -` for standard input and `--format json` for machine-readable
output. Repeat `--available-label` only when supplying a complete local label
set. Repeat `--candidate-summary` to supply local duplicate-candidate evidence.

## Immutable result

Text and JSON derive from one `IssueDraftValidationResult` containing:

- validation status and stable ordered reason codes;
- `format_valid` and `submission_eligible`;
- parser, schema, and duplicate-candidate evidence;
- normalized report evidence;
- `write_authorized=false`;
- `mutation_performed=false`.

```text
valid preview != readiness != approval != write authorization
```

## Reason codes

| Code | Default outcome |
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

Free-form text is supporting evidence only. Callers consume the stable fields
and codes.

## Exit codes

| Exit | Symbol | Meaning |
|---:|---|---|
| `0` | `ELIGIBLE_SUCCESS` | eligible success |
| `10` | `ELIGIBLE_WARNING` | eligible advisory warning |
| `20` | `MANUAL_REVIEW` | human decision required |
| `30` | `VALIDATION_FAILURE` | hard validation failure |
| `64` | `INVALID_INPUT_OR_USAGE` | invalid input or command usage |

Manual review is non-zero. Future #602 adapter outcomes must use separate codes.

## Parser ambiguity

`parse_issue_form_body()` remains the only Markdown parser. Validation compares
normalized source values, canonical rendered Markdown, and parsed output.
Canonical-looking `###` headings inside multiline values, duplicate headings,
missing or unexpected fields, and changed values produce
`parser-round-trip-ambiguity` and `submission_eligible=false`.

## Schema drift

The local issue-form file is checked for unsupported controls or attributes,
unknown validation shapes, malformed or duplicate options, duplicate raw or
canonical IDs, duplicate labels, malformed body entries, and unsupported
top-level keys. Drift produces manual review. The form is never edited here.

## Duplicate candidates

Duplicate evidence uses only supplied local summaries and normalized exact-title
matching. It is advisory and performs no search or issue mutation.

## Write boundary

Every result preserves:

```text
write_authorized=false
mutation_performed=false
```

Validation, readiness, and passing checks remain evidence only.

## Handoff to #602

#602 may consume only a merged result with `submission_eligible=true`. It must
reuse these reason and exit contracts and add its own separately reviewed
confirmation and command boundary. #601 does not submit an issue.

## Validation

Run focused draft and validation tests, checker and planner regressions, Python
compilation, `bash 07_Agent_Tests/validate-repo-structure.sh`, and
`./scripts/validate-all.sh`.
