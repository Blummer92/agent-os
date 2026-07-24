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

## Documentation ownership and relevance advisory
The optional `--documentation-advisory` flag attaches bounded DOC5 evidence to the existing acceptance report before the transport computes `report_sha256`. The repository workflow enables this flag so the job summary identifies the exact augmented report shown to the operator.

The advisory reuses only the canonical `IssueMetadata` projection and the existing `required docs` check. It reports the declared owner value, declared documentation-path count, existing coverage-check status, and whether an expected-change declaration is present. It does not parse registries, infer path ownership, score documentation quality, or decide semantic relevance or sufficiency.

The evidence is advisory only:
- a declared `owner_agent` is not proof of canonical ownership, write authorization, or responsibility for a path;
- required-documentation path coverage does not prove relevance, sufficiency, correctness, or quality;
- ownership, semantic relevance, and sufficiency remain human-review decisions;
- the adapter never changes acceptance status, readiness, ordinary checks, blockers, manual-review items, exit codes, merge eligibility, or governed fields;
- no comments, checks, statuses, labels, artifacts, external calls, or persistent writes are introduced;
- omitting the flag preserves legacy text and JSON output byte-for-byte;
- `docs-not-required` produces a fresh but value-equivalent report with no advisory evidence.

## Local acceptance usage
```bash
python -m scripts.agent_os_issue_acceptance.cli \
  --issue tests/agent_os_issue_acceptance/fixtures/issue_valid.md \
  --pr-body tests/agent_os_issue_acceptance/fixtures/pr_body_valid.md \
  --changed-files tests/agent_os_issue_acceptance/fixtures/changed_files_valid.txt \
  --diff tests/agent_os_issue_acceptance/fixtures/diff_clean.patch
```
Use `--format json` for stable machine-readable report fields.

## Canonical domains
| Domain | Canonical modules |
|---|---|
| IssuePlan scanning and compatibility projection | `issueplan_scanner.py`, `parse_issue.py` |
| Acceptance and readiness evidence | `policy.py`, `readiness.py`, `models.py`, `report.py` |
| Connected issue retrieval and pagination evidence | `issue_scanner.py`, `github_issue_source.py` |
| Batch graph, conflict checks, extensions, and planning | `batch_graph.py`, `batch_checks.py`, `batch_extensions.py`, `batch_planning.py`, related check modules |
| Scheduler planning-handoff contracts | `scheduler_handoff.py` |
| IssuePlan current-state evidence | `issueplan_current_state.py` |
| Approval records and approved-execution projection | `approval_records.py`, `approved_execution_projection.py` |
| Sprint governance and reporting | `sprint_dashboard.py` |

This map documents the current package; it does not create new APIs or authorize a physical split.

## Permitted dependency direction
```text
IssuePlan scanner -> acceptance/readiness and current-state evidence
acceptance primitives -> batch graph/planning -> Scheduler handoff
current-state + handoff + repository evidence -> approvals -> execution projection
Sprint reporting -> supplied immutable evidence only
Workflow Scheduler runtime -> stable public contracts only
```
Production modules must not reverse these directions. Scanner or retrieval code must not import planning, approval, projection, reporting, or Workflow Scheduler runtime code. Acceptance and readiness code must not import planning or Scheduler contracts. Planning must not create Scheduler tasks or execution state. Reporting must not mutate readiness, planning, approvals, Scheduler state, or canonical evidence. Compatibility code must not become a second parser or authority.

## Canonical IssuePlan scanning
`issueplan_scanner.py` is the only acceptance-block candidate discovery and YAML parsing implementation. It preserves source identity, revision, multiplicity, malformed candidates, unknown governed fields, profile compatibility, and identity findings.

`parse_issue_metadata()` is a temporary lossy compatibility facade. It calls the canonical scanner and contains no parser of its own. Removal requires a separately governed API migration after all callers consume scanner results directly.

Scanner validity, readiness, labels, and approvals never authorize execution.

## Linked-issue parsing
A linked issue resolves only when exactly one unique same-repository target is introduced by a supported closing keyword: `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, or `resolved`. Optional colon and whitespace forms are supported.

Bare references and `Addresses #...` are non-authoritative. Fenced code, inline code, blockquotes, and HTML comments are masked. Critical consumers use `parse_linked_issue_result()`; `parse_linked_issue()` remains a lossy wrapper.

## Public-interface policy
Existing package exports remain supported until a separately governed compatibility migration proves removal safe. New interfaces use direct-module imports by default.

A package-level re-export requires intentional stability, a verified operational consumer, focused tests, owner evidence, compatibility guidance, and a registry-impact decision when applicable.

Facade growth is not justified by convenience alone. Private helpers and speculative interfaces remain internal.

## Physical-split threshold
A later package split requires current evidence of at least one of: circular dependency pressure, conflicting ownership, incompatible release requirements, repeated unrelated facade changes, inability to test or distribute a domain independently, or independently versioned operational consumers. Directory size or visual cleanliness is not sufficient.

## Metadata and issue scanning
`metadata_validation.py` evaluates MD2A fixture evidence offline and report-only. It never edits issues, labels, readiness fields, workflows, or external systems.

`issue_scanner.py` is the pure scanner library. It owns pagination, requested-state validation for `open`, `closed`, and `all`, source-state consistency, duplicate detection, deterministic ordering, and complete-versus-incomplete evidence. The legacy `scan_open_issues()` function remains a thin compatibility wrapper over the canonical state-aware scanner.

`github_issue_source.py` defines the caller-supplied `GitHubIssuePageReader` protocol and the bounded connected-source adapter. It normalizes supplied page evidence, excludes pull-request records, maps connector failures into bounded scanner errors, and projects scan results into report-only payloads. `scan_connected_open_issues()` remains a compatibility wrapper; new state-aware callers use `scan_connected_issues()` with an explicit `IssueStateFilter` and caller-supplied UTC retrieval timestamp.

External execution belongs to a separately approved connected caller. That caller must supply the repository, requested state, retrieval timestamp, complete page reader, and its own credential and permission boundary.

This package does not provide network transport or a concrete live GitHub reader; GitHub authentication, token loading, credential lookup, or authorization headers; a connected scanner CLI or subprocess wrapper; issue or label mutation; automatic report posting; or Workflow Scheduler execution behavior.

## Informational reuse evidence (optional adapter)
- `reuse_readiness.py` (RC5B / #470 under the #248 contract) attaches caller-supplied RC3 `DiscoveryResult` and corrected-RC4 `ValidationReport` evidence to a `ReadinessResult` as a strictly informational layer. Informational evidence never changes `ReadinessOutcome`, `overall_status`, ordinary checks, blockers, ordinary manual-review items, or `exit_code_for()`; it is carried only in `AcceptanceReport.informational_checks`, rendered in a separate section that is omitted when empty (legacy output stays byte-for-byte identical). Provenance is compared using caller-supplied `RegistryProvenance` values only (strict, version-aware); missing, mismatched, unsupported, failing, contradicted, conflicting, or malformed evidence suppresses positive reuse guidance while leaving base readiness unchanged.
- It is the sole cross-package boundary, never reads the registry or invokes `RegistryReader`/discovery/validation orchestration, and is not exported from `__init__.py`; `readiness.py` stays independent, so base readiness imports and runs without the reusable-capability package installed. No reuse evidence authorizes implementation, writes, readiness changes, or merge, and the adapter performs no registry, issue, label, readiness, workflow, Scheduler, credential, production, or external mutation.

## Workflow and write boundary
Metadata validation and scanning remain offline and report-only. Connected retrieval consumes caller-supplied readers and preserves provenance. The package does not authorize issue, label, readiness, workflow, Scheduler, credential, production, or external-system writes.

Outcome meaning remains governed by `01_Shared_Standards/github/issue-acceptance-automation.md`. Package boundaries and facade decisions are governed by issue #464 and the applicable Agent OS governance standards.
