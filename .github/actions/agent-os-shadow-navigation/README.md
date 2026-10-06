# Agent OS Shadow Navigation action

This local composite action wraps the existing `scripts/agent-os-shadow-run.py`
production caller. It does not introduce another selector, scheduler, queue, or
routing vocabulary.

## Safety boundary

The action is read-only. The caller must provide a workflow token with read-only
repository permissions. The underlying shadow runner records zero-mutation
evidence in every report and keeps `execution_authorized=false` and
`side_effects_performed=false`.

This action may observe, rank, explain, and emit evidence. It does not authorize
issue execution, comments, labels, branches, pull-request changes, merges,
closures, or any external-system write.

## Inputs

- `repository` — repository in `owner/name` form.
- `campaign_id` — required shadow experiment identifier.
- `candidates` — optional comma-separated deterministic narrowing set.
- `narrowing_criterion` — required when `candidates` is supplied.
- `explicit_order` — optional explicit request order inside the candidate set.
- `mission_id` — optional finite-mission evidence-ledger identifier.

The output `report_path` points to the generated JSON experiment record.

The repository workflow `.github/workflows/agent-os-shadow-navigation.yml`
provides the installable manual GitHub Actions entry point and publishes both a
job summary and a retained JSON artifact.
