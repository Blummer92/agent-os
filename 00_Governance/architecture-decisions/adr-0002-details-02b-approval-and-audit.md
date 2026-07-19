# ADR 0002 Details 2b: Approval Binding and Rejection Audit

Companion to `adr-0002-ia4d-scheduler-handoff-contract.md` and
`adr-0002-details-02-freshness-and-approval.md`.

## Approval binding

Any future Scheduler approval record must bind to all of:

- task-proposal digest;
- `handoff_digest` (the envelope field defined in
  `adr-0002-details-01d-handoff-digest.md`, not a separately computed
  value);
- `graph_digest`;
- `planning_result_digest`;
- `evaluated_repository_sha`;
- exact `supplied_node_ids`;
- authorization decision identity;
- authorization timestamp.

The handoff exposes these fields read-only; it defines what a future
approval must reference but does not implement approval storage,
issuance, or invalidation logic itself — that is IA5D's scope. Any
mismatch between a stored approval's bound values and current
revalidation output invalidates the approval, requiring new planning
and a new approval; there is no partial-match or best-effort binding.

## Audit evidence on rejection

When a handoff or a bound approval is rejected (`stale`, `invalid`, or
`needs-decision`, per `adr-0002-details-02-freshness-and-approval.md`),
the rejecting consumer must record:

- which of the ten required revalidation checks failed;
- the stored value versus the current value for each failed check;
- the rejection outcome (`stale` / `invalid` / `needs-decision`);
- a timestamp.

This audit record is evidence only; this ADR does not define where it
is persisted — that belongs to the concrete consumer issue (IA5C/IA5D)
that performs the rejection.

## Version

0.2.0

## Changelog

- 0.2.0 pointed the approval-binding `handoff_digest` bullet at its
  concrete envelope-field definition.
- 0.1.0 initial approval binding and rejection audit contract.
