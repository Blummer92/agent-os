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
The optional `--documentation-advisory` flag attaches bounded DOC5 evidence before transport hashing by reusing the canonical `IssueMetadata` projection and existing `required docs` check; the workflow enables it while remaining read-only and job-summary-only. The adapter reports only a bounded declared-owner token, documentation-path count, existing coverage status, and expected-change presence. Ownership, relevance, sufficiency, and authorization remain human-review decisions; it never parses registries, infers path ownership, scores quality, changes acceptance/readiness/checks/blockers/exit codes/merge eligibility, or writes externally. Omitting the flag preserves legacy output byte-for-byte, and `docs-not-required` returns a fresh value-equivalent report without advisory evidence.

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
| Canonical issue operational-state projection and operating-mode decision | `issue_operational_state.py`, `operating_mode.py` |
| Approval records and approved-execution projection | `approval_records.py`, `approved_execution_projection.py` |
| Reporting | `acceptance_report_transport.py`, `documentation_advisory.py`, `documentation_gap_report.py`, `documentation_metrics.py`, `sprint_dashboard.py` |

`documentation_metrics.py` is bounded, pure-local, supplied-evidence-only, deterministic, report-only, non-scheduling, non-retaining, and non-authoritative; this map creates no API or physical split.

## Permitted dependency direction
```text
IssuePlan scanner -> acceptance/readiness and current-state evidence
acceptance primitives -> batch graph/planning -> Scheduler handoff
current-state + handoff + repository evidence -> approvals -> execution projection
current-state + approval, merge, lifecycle, claim, validation evidence -> operational state -> mode/queue projections
Sprint reporting -> supplied immutable evidence only
Workflow Scheduler runtime -> stable public contracts only
```
Production modules must not reverse these directions. Scanner or retrieval code must not import planning, approval, projection, reporting, or Workflow Scheduler runtime code. Acceptance and readiness code must not import planning or Scheduler contracts. Planning must not create Scheduler tasks or execution state. Reporting must not mutate readiness, planning, approvals, Scheduler state, or canonical evidence. Compatibility code must not become a second parser or authority.

## Canonical IssuePlan scanning
`issueplan_scanner.py` is the only acceptance-block candidate discovery and YAML parsing implementation. It preserves source identity, revision, multiplicity, malformed candidates, unknown governed fields, profile compatibility, and identity findings.

`parse_issue_metadata()` is a temporary lossy compatibility facade. It calls the canonical scanner and contains no parser of its own. Removal requires a separately governed API migration after all callers consume scanner results directly.

Scanner validity, readiness, labels, and approvals never authorize execution.

## Canonical issue operational state

`issue_operational_state.py` implements the pure, content-addressed `agent-os-issue-operational-state/1.0` projection over supplied IssuePlan, approval, merge-authorization, lifecycle-admission, claim, validation, and freshness evidence. It preserves readiness and every authority dimension separately, never re-evaluates upstream records, performs no I/O or execution, uses strict deterministic JSON and domain-separated identity, and fails closed on missing, stale, conflicting, unsupported, duplicate, or tampered evidence; downstream mode and queue evaluators may consume it but may not reconstruct authority. `operating_mode.py` is the first such consumer: the pure `agent-os-operating-mode-decision/1.0` evaluator intersects a requested mode ceiling (`planning`, `build`, `draft-pr`, `review`, `release`) with a supplied `IssueOperationalState` and caller-verified `EnvironmentCapabilityEvidence`, walking `implementation -> draft-pr -> review -> merged -> closed` one authorization/environment gate at a time and stopping at the first unmet one; an omitted or unrecognized mode -- including `complete`, `finish`, or `do everything` -- always defaults to `planning` and never implies `release`. It is not exported from `__init__.py` per the direct-import policy below, and `tests/agent_os_issue_acceptance/test_architecture_boundaries.py`'s domain map classifies it in its own exact `mode` domain, downstream of `approval` (whose canonical projection contracts it consumes) and upstream of `reporting`, which it must not import.

## Coding Command Center handoff projection

`coding_command_center_handoff.py` (#1097, AOS-NCC2) implements the pure, content-addressed `agent-os-coding-command-center-handoff/1.0` read-only projection for the existing Notion `Solo-Operator OS Coding` cockpit. It composes only caller-supplied canonical evidence: one `IssueOperationalState`, an optional `ExecutorRouteDecision`, an optional #988 `ValidationFailureClassificationResult`, an optional #914 `PostPrLanePlan`, plus a bounded validation-evidence reference and handoff target. It re-runs each supplied record's own invariant so tampered frozen objects fail closed, and it performs no GitHub, network, filesystem, subprocess, Scheduler, provider, or Notion I/O.

The projection is composition only. It creates no task ledger, progress or session state, queue planner, executor selector, validation classifier, repair engine, authorization model, Notion client, sync system, or background worker. `authority_created`, `side_effects_performed`, and `notion_write_performed` are hard-coded `false` and cannot be set by a caller. Canonical blocker ordering, #988 recommended-next-action text, and #914 smallest-next-action semantics are carried through unchanged rather than reranked, and no percentage progress is synthesized. Missing optional evidence stays explicitly `unavailable`; stale, conflicting, or invalid operational state replaces the next action with a reacquire-evidence instruction and records `handoff.fail-closed-currentness`.

`render_coding_command_center_handoff()` emits the #926 visible order — current target, smallest safe next action, route/escalation reason, validation or blocker evidence, handoff target, then compact canonical references — and repeats the three non-authority declarations. Text fields are bounded to 4 KiB, reason codes to 32 entries, and the serialized record to 64 KiB.

It is not exported from `__init__.py` per the direct-import policy below, and `tests/agent_os_issue_acceptance/test_architecture_boundaries.py`'s domain map classifies it in the existing `reporting` domain: reporting is the downstream output domain permitted to consume supplied immutable upstream evidence, and no upstream domain may import it. Because it consumes the #914 `PostPrLanePlan` contract, importing this module also initializes `scripts.agent_os_candidate_packet`; callers therefore need that package's declared runtime dependencies present.

Notion display mapping remains a future, separately authorized concern: Agent Start Here -> target plus smallest next action plus executor route; Active Build Queue -> canonical issue/PR plus named stage plus blocker; QA & Testing -> exact-head/validation class plus evidence reference; Automation Catalog -> unchanged. No Notion mutation is authorized by this module.

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
