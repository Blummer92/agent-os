# Effective Gate Reconciliation (#1235)

## Purpose
Before execution preflight or resume surfaces a blocker from stale issue prose,
labels, or comments, reconcile the underlying gate against newer applicable
canonical evidence from its explicit evidence owner.

## Contract
`effective_gate_reconciliation.py` is a pure supplied-evidence decision seam. The
caller follows explicit dependency/evidence links and fetches bounded canonical
GitHub evidence; this module performs no search, network access, persistence, or
lifecycle mutation.

A newer record supersedes a stale marker only when all are provable:
- the gate identity matches;
- the record comes from the marker's explicit evidence owner;
- the record is authoritative rather than informational;
- repository/issue and any required PR/SHA identity match exactly; and
- its canonical timestamp is newer than the marker.

The newest applicable authoritative disposition wins. Conflicting records at the
same newest instant return `manual-review`. A later authoritative blocker reopens
a previously satisfied gate. Duplicate/replayed evidence is idempotent. Closure
alone is not evidence. If no evidence owner or no newer applicable evidence is
available, the result remains fail-closed.

## Authority boundary
The result is effective gate evidence only. It never grants repository
implementation, merge, issue closure, protected-setting, production, or external
write authority and never mutates issue labels/status. Existing authorization,
ownership, exact-head, lifecycle, Scheduler/lease, and source-of-truth contracts
remain independently authoritative.

## Ownership
#1235 owns stale gate/provenance/recency reconciliation. #1237 continues to own
execution-surface continuation after a capable alternative is discovered. This
contract does not add a router, readiness framework, retry engine, Scheduler,
lease, evidence store, or semantic search path.

## Tests
`tests/agent_os_execution_interface/test_effective_gate_reconciliation.py`
covers the ten adversarial cases required by #1235, including stale labels,
non-authoritative comments, wrong identity, conflicts, closure without evidence,
reopened blockers, missing evidence owners, replay idempotency, and excluded
authority.

## Rollback
Remove the module, focused tests, and this document. No persistent or external
state is created by the contract.
