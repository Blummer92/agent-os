# Agent OS Issue Automation

Pure-local contracts, evidence models, scanners, planners, handoffs, approvals, and reports used by Agent OS issue automation.

## Acceptance-report transport
The report-only transport adapter binds an existing acceptance report to a deterministic workflow summary envelope. It never authorizes execution and remains bounded to 64 KiB.

The supported contract is `agent-os-acceptance-report-transport/v1`. Allowed states are `snapshot-current`, `stale-issue`, `stale-pr-head`, `unsupported-contract`, and `missing-provenance`.

Transport behavior is intentionally strict:
- issue-body identity is preserved exactly from the captured bytes; trailing newlines and empty bodies remain intact;
- real #360 evidence is derived from the captured issue body and the workflow execution context; no fabricated SHA, timestamp, fingerprint, revision, or source identity is used;
- PR-head provenance is separate from evaluator provenance; the workflow uses the live PR head SHA and `git rev-parse HEAD` for the evaluator SHA;
- final snapshot state requires both the final issue-body recheck and the final live PR-head recheck; otherwise the transport fails closed to `missing-provenance`;
- state precedence is deterministic: `unsupported-contract` > `missing-provenance` > `stale-pr-head` > `stale-issue` > `snapshot-current`;
- report hashing is derived from the canonical deterministic representation of the existing acceptance report, not from workflow run identity or the transport envelope.

The workflow stays read-only and job-summary-only. It publishes a report summary and never mutates issues, pull requests, labels, readiness state, or external systems.
