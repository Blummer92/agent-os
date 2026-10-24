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
| Reporting | `acceptance_report_transport.py`, `documentation_advisory.py`, `documentation_gap_report.py`, `sprint_dashboard.py`, `coding_command_center_handoff.py`, `compute_control_projection.py`, `issue_operational_state_acquisition.py`, `lifecycle_stage_acquisition.py`, `pr_lineage_reader.py`, `live_compute_control_binding.py` |

## Live compute-control binding (#1460)

`live_compute_control_binding.py` is the production caller for
`issue_operational_state_acquisition.py` (#1451): given already-acquired
canonical evidence, it performs the one live GitHub issue read, wires every
#1451 injected-evidence input, and invokes the unchanged
#1451 -> #1441 -> #1097 -> #1419 chain to return one serialized
`agent-os-compute-control-projection/1.0`. Canonical owner for each #1451
input:

| #1451 input | Canonical owner |
|---|---|
| `CurrentIssueSnapshot` | `LiveCurrentIssueSnapshotReader`, composing `agent_os_candidate_packet_live_input.LiveIssueReader` (one live issue read over a caller-injected `SingleIssueTransport`) with `agent_os_github_issue_provider.revision.issue_source_revision`. `source_revision` is caller-supplied; `lifecycle_stage` is caller-supplied or, in the shadow path, acquired per issue by the #3441 PR-lineage reader through the #3433 evaluator (`LifecycleStageAcquirer`). |
| Approval applicability | Caller-supplied, from the existing `approval_records.evaluate_approval_applicability`. |
| `DependencyState` / `ValidationState` | `dependency_state_from_evidence` / `validation_state_from_evidence`, translating the existing `DependencyEvidence`/`ValidationEvidence` produced by a caller-injected `agent_os_candidate_packet_live_input.LiveRepositoryEvidenceReader` (or any other conforming `RepositoryEvidenceReader`). |
| `PrimaryIssueClaim` tuple | Caller-supplied. No canonical live PR-linkage reader exists. |
| `FreshnessState` | Caller-supplied. No general-purpose currentness authority exists outside the domain-specific ones already reused above. |
| Merge / Ready-for-Review / closure / execution / external-write authority | Caller-supplied, from `merge_authorization.py`, `lifecycle_mutation_guard.py`, and the existing execution/external-write authorization owners; passed through unchanged. |

The one join this boundary owns is the single-claim lineage check: when the
acquired state has one primary claim, the caller's exact `PrimaryIssueClaim`
and observed current head must describe that same claim, so a well-formed head
SHA can never be paired with a different PR/branch lineage. It re-derives the
claim's content-addressed `claim_id` before comparing, so a tampered frozen
claim fails closed. It verifies an identity join only; claim authority stays
with the canonical claim evidence owners.

No GitHub client, evidence model, or authority is created by this module; see
its docstring for the full reasoning, including why
`08_Tooling/agent-os-execution-service`'s `HostGitHubReadTransport` cannot be
imported here (the dependency direction runs the other way).

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

It is not exported from `__init__.py` per the direct-import policy below, and `tests/agent_os_issue_acceptance/test_architecture_boundaries.py`'s domain map classifies it in the existing `reporting` domain: reporting is the downstream output domain permitted to consume supplied immutable upstream evidence, and no upstream domain may import it. Because it consumes the #914 `PostPrLanePlan` contract, importing this module also initializes `scripts.agent_os_candidate_packet`; callers therefore need that package's declared runtime dependencies present.

Notion display mapping remains a future, separately authorized concern: Agent Start Here -> target plus smallest next action plus executor route; Active Build Queue -> canonical issue/PR plus named stage plus blocker; QA & Testing -> exact-head/validation class plus evidence reference; Automation Catalog -> unchanged. No Notion mutation is authorized by this module.

## Compute-control decision projection

`compute_control_projection.py` (#1419, AOS-NCCE1) implements the pure, content-addressed `agent-os-compute-control-projection/1.0` read-only projection that states whether compute is currently justified and what the cheapest valid governed next validation step is. It is a narrow composer over existing owners only: the #1097 `CodingCommandCenterHandoff` base projection, one `IssueOperationalState`, the canonical `ValidationPlan` profile from `scripts.agent_os_remote_validation`, that package's `EvidenceApplicabilityProjection`, plus bounded references to an already-projected validation-head decision, an already-observed active execution, and #1359/#520 measured compute metadata.

The finite disposition vocabulary is frozen by #1419: `run-now`, `do-not-spend-compute-yet`, `focused-validation-first`, `final-cloud-validation-required`, `reuse-existing-evidence`, `duplicate-or-obsolete-run-risk`, and `unavailable`. Precedence is fail-closed and fixed — currentness before prerequisites, prerequisites before duplicate risk, duplicate risk before reuse, and reuse before any instruction to spend compute. Missing, stale, or conflicting identity, authorization, or validation evidence never becomes compute admission.

The canonical validation profile names the next step directly: `static` -> `run-now`, `focused` -> `focused-validation-first`, `aggregate` -> `final-cloud-validation-required`, and `manual-review` -> `do-not-spend-compute-yet`. Focused guidance never implies the required final authoritative validation is satisfied. `reuse-existing-evidence` requires both canonical owners to agree for the exact current head: applicability must be `fresh-and-applicable` and the head decision must be `passed` with `satisfies_current_head`; either alone is insufficient. Duplicate and obsolete-head risk is surfaced as a warning plus a non-authorizing disposition and never cancels, dispatches, or supersedes anything.

The module creates no executor router, validation selector or classifier, authorization model, task ledger, active-run ownership, Scheduler behavior, generic evidence-reuse policy, Notion client, or cost estimator, and it synthesizes no percentage progress or predicted cost. `authority_created`, `side_effects_performed`, and `notion_write_performed` are hard-coded `false` and cannot be set by a caller. It re-runs each supplied record's own invariant so tampered frozen objects fail closed, and a handoff and operational state describing different identities are rejected at construction rather than projected.

`VALIDATION_HEAD_DISPOSITIONS` mirrors the canonical vocabulary owned by `agent_os_execution_service.validation_supersession` without importing it: that module lives in a separately installed distribution absent from the root developer environment, and it imports this package, so a direct import would both break root validation and invert the dependency direction. Only its already-projected decision is consumed, by reference; a focused test asserts the mirrored vocabulary still matches the canonical enum. Like #1097 this module is not exported from `__init__.py` per the direct-import policy below, and the architecture domain map classifies it in the existing `reporting` domain.

Callers compose this projection directly: build the #1097 handoff from already-owned canonical evidence, pass it with the same `IssueOperationalState` into `ComputeControlEvidence`, then call `build_compute_control_projection()` and `serialize_compute_control_projection()`. `live_compute_control_binding.py` (#1460) is the production caller and the only place the single-claim lineage join is applied; #1731 removed the separate `compute_control_producer.py` composition seam, which forwarded to this module and owned nothing else.

## Linked-issue parsing
A linked issue resolves only when exactly one unique same-repository target is introduced by a supported closing keyword: `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, or `resolved`. Optional colon and whitespace forms are supported.

Bare references and `Addresses #...` are non-authoritative. Fenced code, inline code, blockquotes, and HTML comments are masked. Critical consumers use `parse_linked_issue_result()`; `parse_linked_issue()` remains a lossy wrapper.

## Cumulative required-docs evidence (#3724)
`build_merged_doc_evidence.py` is the read-only REST producer run by the Issue Acceptance workflow; it writes a JSON list of records (or `[]` on any failure) that the CLI passes to the `required docs` check via `--merged-docs-evidence`. It nominates merged PRs from same-repository timeline cross-references, then keeps one only when the canonical `report_only_issue_number(parse_linked_issue_result(...))` association equals the evaluated issue, its merge commit is an ancestor of the evaluated base (compare API), and at least one of its files matching a current declaration has the identical blob at the merge commit and the base. `merged_docs.py` re-validates each record offline (exact keys, types, issue, freshness against the current declarations); `checks/required_docs.py` matches the remaining files with the same `_is_covered` contract as current-PR files and reports invalid-record reason codes only with a failing result. Neither module creates readiness, merge, or closure authority.

## Criterion-preservation handoff packet (#3677)
`criterion_preservation.py` is a pure, deterministic packet surface for implementation handoffs. `parse_acceptance_criteria()` reads the checkbox criteria of an issue body's acceptance-criteria section in order, preserving each criterion's exact text; a criterion's identity is its 1-based position plus a digest of that exact text. The section heading is recognized at level 2 or 3 (`##` / `### Acceptance criteria`), with or without the `and definition of done` suffix; the section ends at the next heading of the same or a higher level, so sibling issue-form fields never become criteria; and more than one recognized heading makes the section ambiguous — it is treated as missing, and the satisfaction projection reports manual-review with the note `criteria-section-ambiguous`. `build_criterion_packet()` emits the handoff packet output — every parsed criterion with its identity — and `verify_criterion_packet()` compares a packet against the canonical issue body: a missing index is a dropped criterion, the same index with different text is a reworded criterion, and each is reported as a manual-review item for that criterion. Only a byte-exact full match verifies as `preserved`. The module performs no I/O and creates no authority.

The PR template (`.github/PULL_REQUEST_TEMPLATE.md`) applies the same contract at authoring time: linkage defaults to a non-closing reference (`Part of #N`, closing opt-in only with an exact-issue closure admission), and its criterion-preservation section requires a per-criterion mapping or an explicit manual-review statement naming the unmapped criteria.

## Criterion-level satisfaction projection (#3678)
`criterion_satisfaction.py` is a pure, deterministic, report-only projection. `project_criterion_satisfaction()` maps the criteria parsed from one canonical issue body (identities from `criterion_preservation.py`) to caller-supplied evidence records and PR lineage, and gives every criterion exactly one disposition: `satisfied`, `unsatisfied`, `stale`, `missing`, `contradicted`, or `manual-review`, each with traceable evidence pointers or an explicit missing-evidence reason. Evidence accumulates across sequential linked PRs (earlier merged PRs and the one open primary PR); evidence bound to a superseded PR head or to a prior issue-body version is `stale`, disagreeing current evidence is `contradicted`, and an unparsable criterion is `manual-review`. Only a per-criterion verdict record bound to the exact issue-body version and the authoritative PR head can satisfy a criterion — merge state, CI success, and review success are `pr-signal` records and never satisfy. An issue reports complete satisfaction only when every criterion is `satisfied`. `attach_satisfaction_evidence()` registers the projection through the report's informational channel (`AcceptanceReport.informational_checks`); it never changes the overall result, blockers, or exit behavior, and it creates no authority: satisfaction output is evidence for independent QA judgment, never an admission.

Its approval-domain consumers (`lifecycle_reconciliation.py`, `closure_admission_actions.py`) receive the record as a plain mapping and validate it with the one shared, standard-library-only core `satisfaction_snapshot.py` (#3690 CR-1); each consumer keeps its own identity check and uses the shared serializer with distinct output shapes (only reconciliation includes `closure_ready`).

## Public-interface policy
Existing package exports remain supported until a separately governed compatibility migration proves removal safe. New interfaces use direct-module imports by default.

A package-level re-export requires intentional stability, a verified operational consumer, focused tests, owner evidence, compatibility guidance, and a registry-impact decision when applicable.

Facade growth is not justified by convenience alone. Private helpers and speculative interfaces remain internal.

## Physical-split threshold
A later package split requires current evidence of at least one of: circular dependency pressure, conflicting ownership, incompatible release requirements, repeated unrelated facade changes, inability to test or distribute a domain independently, or independently versioned operational consumers. Directory size or visual cleanliness is not sufficient.
## Metadata and issue scanning
`metadata_validation.py` evaluates MD2A fixture evidence offline and report-only. It never edits issues, labels, readiness fields, workflows, or external systems.

`issue_scanner.py` is the pure scanner library. It owns pagination, requested-state validation for `open`, `closed`, and `all`, source-state consistency, duplicate detection, deterministic ordering, and complete-versus-incomplete evidence. Callers use the canonical `scan_issues()` with an explicit `requested_state`.

`github_issue_source.py` defines the caller-supplied `GitHubIssuePageReader` protocol and the bounded connected-source adapter. It normalizes supplied page evidence, excludes pull-request records, maps connector failures into bounded scanner errors, and projects scan results into report-only payloads. State-aware callers use `scan_connected_issues()` with an explicit `IssueStateFilter` and caller-supplied UTC retrieval timestamp.

External execution belongs to a separately approved connected caller. That caller must supply the repository, requested state, retrieval timestamp, complete page reader, and its own credential and permission boundary.

This package does not provide network transport or a concrete live GitHub reader; GitHub authentication, token loading, credential lookup, or authorization headers; a connected scanner CLI or subprocess wrapper; issue or label mutation; automatic report posting; or Workflow Scheduler execution behavior.
## Informational reuse evidence (optional adapter)
- `reuse_readiness.py` (RC5B / #470 under the #248 contract) attaches caller-supplied RC3 `DiscoveryResult` and corrected-RC4 `ValidationReport` evidence to a `ReadinessResult` as a strictly informational layer. Informational evidence never changes `ReadinessOutcome`, `overall_status`, ordinary checks, blockers, ordinary manual-review items, or `exit_code_for()`; it is carried only in `AcceptanceReport.informational_checks`, rendered in a separate section that is omitted when empty (legacy output stays byte-for-byte identical). Provenance is compared using caller-supplied `RegistryProvenance` values only (strict, version-aware); missing, mismatched, unsupported, failing, contradicted, conflicting, or malformed evidence suppresses positive reuse guidance while leaving base readiness unchanged.
- It is the sole cross-package boundary, never reads the registry or invokes `RegistryReader`/discovery/validation orchestration, and is not exported from `__init__.py`; `readiness.py` stays independent, so base readiness imports and runs without the reusable-capability package installed. No reuse evidence authorizes implementation, writes, readiness changes, or merge, and the adapter performs no registry, issue, label, readiness, workflow, Scheduler, credential, production, or external mutation.
## Report-only issue-quality and metadata-validation checks (#3282)

`checks/issue_quality.py` (the issue-quality taxonomy checkers) and
`metadata_validation.py` (MD2B) are registered in `policy.py` as strictly
informational evidence. They run on every acceptance evaluation and their
results appear in `AcceptanceReport.informational_checks`, rendered in the
report's informational section and included in `--format json` output. They
never enter `report.checks`, `overall_status`, `blockers`,
`manual_review_items`, `remaining_risks`, or the workflow exit code:
`overall_status` is computed by `strongest_status()` over `report.checks`
only, and `exit_code_for()` returns 1 only for `Status.FAIL`. This mirrors the
`reuse_readiness.py` precedent for the same channel. The rendered section keeps
the #248-contract heading "Reusable-capability evidence (informational):"
(pinned by `test_report.py`); the #3282 checks are distinguished by name
prefix (`issue-quality: ...`, `metadata:<field>`).

### Tier-to-issue-family mapping

`issue_quality.check()` needs an `IssueFamily`, but the acceptance inputs carry
no tier-to-family mapping (metadata tiers `tier:0/1/2-*` are not families).
`policy.py` derives the family from the "Issue tier" body section (the issue
template keeps tier as body evidence, not a label):

| Issue tier value | Issue family |
|---|---|
| `tier:0-small-maintenance` | `cleanup` |
| `tier:1-standard-implementation` | `implementation` |
| `tier:2-governed-cross-system` | `governance` |

Tier 1 and Tier 2 map by direct name correspondence with the template's
definitions ("standard implementation", "governed or cross-system work");
Tier 0 ("small safe maintenance") maps to the lightest family contract
(`cleanup`: goal + scope required). When the Issue tier section holds no
canonical tier value, no family is guessed: only the family-independent
checkers (`check_parent_reference`, `check_related_references`,
`check_blocker_quality`) run, plus one manual-review note recording the skip.

### Metadata field-extraction contract

`metadata_validation.validate_metadata_evidence()` evaluates one
(field, input_evidence) pair. The live-issue contract extracts pairs from
issue-form body sections only (labels are not available to
`evaluate_acceptance`):

| Body section | Metadata field |
|---|---|
| Issue tier | `issue_tier` |
| Readiness candidate | `readiness_candidate` |
| Documentation impact | `documentation_impact` |
| Primary owner | `primary_owner` |
| Source of truth | `source_route` |
| External write boundary | `external_write_boundary` |

Only sections holding a real (non-empty, non-placeholder) value produce a
check; absent or placeholder-only sections (e.g. `_No response_`) produce no
check at all, so unfilled optional fields never emit manual-review noise.
Legacy `risk:`/`surface:`/`system:`/`phase:` tokens in the body are evaluated
as `legacy_metadata` evidence only when present.

### Fixtures

`tests/agent_os_issue_acceptance/fixtures/issue_quality/` holds one fixture per
issue family: `roadmap.md`, `strong_implementation.md`, `validation.md`,
`governance.md`, `cleanup.md`. Registration behavior is covered by
`tests/agent_os_issue_acceptance/test_report_only_registration.py`.
## Workflow and write boundary
Metadata validation and scanning remain offline and report-only. Connected retrieval consumes caller-supplied readers and preserves provenance. The package does not authorize issue, label, readiness, workflow, Scheduler, credential, production, or external-system writes.
Outcome meaning remains governed by `01_Shared_Standards/github/issue-acceptance-automation.md`. Package boundaries and facade decisions are governed by issue #464 and the applicable Agent OS governance standards.

## Authorization drift review (#1157)

`authorization_drift_review.py` implements `agent-os-authorization-drift-review/1.0` as a pure, deterministic, content-addressed classifier over caller-supplied immutable base-to-current evidence. It returns exactly one of `no-relevant-drift`, `revalidation-required`, `contract-conflict`, `authorization-expired`, `evidence-incomplete`, or `manual-decision-required` using the frozen fail-closed precedence from #854; reason codes are finite, sorted, deduplicated, and bounded.

The reviewer binds repository/issue/original-authorization identity, exact original base branch and SHA, supplied current-main SHA, authorization applicability/state, range/provenance evidence, scope and contract fingerprint, dependency identities/public-interface evidence, governance contract revisions, validation requirements/profile/policy, and optional current `IssueOperationalState` identity. It performs no Git/GitHub retrieval, filesystem access, subprocesses, network calls, clock lookup, Scheduler/provider/persistence work, model judgment, or external mutation.

Existing `IssueOperationalState`, approval applicability, merge authorization, lifecycle mutation admission, candidate-packet freshness/invalidation, provenance verification, and #543 stale-authority/retired-scope risk ownership remain canonical. The reviewer does not recreate or override those meanings and is consumed by direct-module import rather than a package-facade expansion.

`AuthorizationRefreshHandoff` is evidence for the existing authorization owner only. It may be built from an eligible review result (and completed revalidation evidence when required), preserves the original scope/allowlist/forbidden paths/tests, and always carries `authorization_granted=false` and `side_effects_performed=false`. No consumer may treat that handoff, a passing test, branch existence, or a `no-relevant-drift` result as authorization.

### Merge authorization persistence (#2869)

Terminal Fast Lane reuses the canonical content-bound merge authorization owner.
An authorized `MergeAuthorizationRecord` may be serialized as an exact
repository-owner-authored `agent-os-merge-authorization/v1` PR-conversation
record. `merge_authorization_source.py` reacquires a complete trusted
conversation, rejects bot/untrusted/malformed/conflicting evidence, selects the
latest revision per authorization identity, and exposes only current
`authorized` records. The caller must still run
`evaluate_merge_authorization_applicability(...)` against freshly reacquired
PR/head/base/scope/check/review evidence immediately before merge. Persistence
does not create authority, and the release runner remains an ordering-only
consumer.

## Issue-comment mutation readback

`comment_mutation_readback.py` (#2785) classifies a connected issue-comment mutation only after caller-supplied canonical readback. Exact target/body identity yields `persisted`; a complete readback with no matching comment yields `not-persisted`; incomplete, duplicate, target-mismatched, or unknown-provider evidence remains `uncertain`. Retry eligibility is evidence only and never performs or authorizes a GitHub write.

## Governed GitHub mutation seams (#3281)

Three pure contracts — each merged as an incident fix but with no host consumer — form two governed mutation seams, exposed to the ChatGPT execution surface as MCP admission tools (`admit_agent_os_issue_comment_mutation_tool`, `project_agent_os_lane_post_pr_issue_reconciliation_tool`; composition in `08_Tooling/agent-os-execution-service/src/agent_os_execution_service/governed_mutation_seams_facade.py`).

Seam 1, the issue-comment write boundary:
- pre-write guard: `defect_evidence_mutation_guard.py` (#2741) admits persisting new defect/process evidence only on a target whose open state was reacquired immediately before the write. A closed target is refused fail-closed with a routing directive — `reacquire-target-state` (stale evidence), `route-to-open-owner` (open owner named), or `create-new-bug` — so evidence is never admitted onto a closed issue as its active owner; closed issues stay historical lineage only.
- post-write readback: `comment_mutation_readback.py` (#2785). A subordinate comment write counts as persisted only after canonical readback proves the exact intended body; a provider success claim alone never proves persistence, and an uncertain response never authorizes an automatic retry, so uncertain-then-reconcile can never create a duplicate comment.

Seam 2, the Safe Implementation Lane post-PR step: `lane_post_pr_issue_reconciliation.py` (#2791) projects the implementation issue's expected post-PR disposition (stale Ready removal, authorized close) after Draft PR readback, and proves the terminal disposition from the canonical post-mutation readback. Draft PR creation is never reported fully reconciled while the linked issue keeps a stale Ready label or an open disposition, and the plan reuses the existing lifecycle-mutation vocabulary — it cannot grant merge or Ready authority (`ready_authorized: Literal[False]`). A closed issue counts as reconciled only under the shared closure-readback rule (#3690): closed with `state_reason` `completed` and no stale Ready label; a missing or other reason, a surviving Ready label, or a readback repository that differs from the plan's never reports full reconciliation.

Fail-closed reasons: every seam tool is pure admission/readback composition with `side_effects_performed: False` and no GitHub write authority; uncertain or stale evidence resolves to non-terminal, non-retrying dispositions rather than optimistic success; and missing closure authority surfaces visibly as `reconcile-ready-awaiting-closure-authority` instead of silently leaving the issue looking actionable.

## Governed issue-closure dispatch (#3489)

`closure_admission_actions.py` supplies the previously missing production edge
between an admitted `close-issue` lifecycle mutation and the GitHub mutation
itself. Admission, authorization, and readback proof are unchanged and reused:
owner decisions are bound by `lifecycle_mutation_authorization.py`, admission
is evaluated by `lifecycle_mutation_guard.py`; post-PR lane disposition
remains owned by `lane_post_pr_issue_reconciliation.py`, while the batch
consumer records the canonical post-dispatch issue readback directly. The new consumer adds the closure
analogue of the Ready host gate: `evaluate_issue_closure` builds one
content-bound, non-performing receipt (independent acceptance checked first,
evaluator distinct from the authorizer), `verify_closure_admission_receipt`
recomputes the admission against a fresh snapshot immediately before dispatch
(any drift fails closed), and `run_closure_batch` walks exactly the finite
owner-authorized issue set through host-injected reader/writer protocols —
per-issue blockers never stop unrelated items, an uncertain write is
reconciled by canonical readback and never retried blindly, and an
already-closed issue is never re-closed. The fixed host dispatch contract
names the native GitHub MCP `issue_write` tool (`update`, `state=closed`,
`state_reason=completed`) as the only writer; this module performs no GitHub
I/O and its receipt fixes `closure_performed: False` — closure is proven only
by post-dispatch canonical readback.

Trust-boundary repairs (#3690):

- The receipt id is an unkeyed content hash, so it authenticates nothing. The
  verification gate takes the satisfaction record the caller reacquired
  independently of the receipt (`satisfaction=`) and requires the receipt's
  block to equal it: a cited block without the trusted record, a trusted
  record whose block was stripped, or a swapped block all fail closed. With
  satisfaction absent on both sides the gate is unchanged (mandatory
  satisfaction remains #3676). The gate also owns the
  `current_issue_body_digest` check, which must match the trusted record.
- QA evidence bound to a validated head fails closed
  (`closure.acceptance-head-unverifiable`) against a snapshot with no
  comparable head; unbound QA evidence for issue-only closure is unchanged.
- `ClosureIssueReadback.issue_body_digest` lets the canonical reader report
  the current body digest; `run_closure_batch` refuses a satisfaction record
  bound to any other body (`closure.satisfaction-stale`). Without reader body
  evidence, currentness is neither proven nor fabricated. The pre-dispatch
  snapshot read carries no digest, so the reader's `observed_revision` must
  change whenever the issue body changes; the exact snapshot binding then
  refuses a body edited between evaluation and dispatch.
- `classify_closure_readback` is the single closure-readback rule, shared by
  the batch and the lane post-PR readback proof below.

## Canonical lifecycle-stage acquisition (#3433)

`lifecycle_stage_acquisition.py` is a deterministic, pure-local evaluator that
derives one issue's `LifecycleStage` from caller-supplied canonical evidence,
or fails closed with a named reason. It performs no GitHub reads or writes,
builds no client, and creates no scheduler, router, approval store, or
persistence.

Evidence contract:

- Issue identity, structured state, content-addressed `github-issue-v1:<sha256>`
  revision, repository SHA, and observation timestamp are caller-supplied and
  re-echoed on the result as currentness bindings (`acquisition_bindings_current`
  detects a changed issue revision or repository SHA).
- PR-lineage evidence is a bounded tuple of already-read PR facts. Each claim's
  linkage is re-verified with the existing GitHub-authoritative
  `parse_pr.parse_linked_issue_result` parser; a caller assertion alone is never
  trusted. Lineage completeness is a caller attestation
  (`PrLineageEnumeration`): an incomplete enumeration fails closed instead of
  proving that no PR exists.

Stage rules: closed issue -> `closed`; one verified open draft PR -> `draft-pr`;
one verified open ready PR -> `review`; one verified merged PR -> `merged`
(issue closure stays a separate fact). Zero verified claims, incomplete
enumeration, competing claims, unverifiable linkage, wrong-repository PRs, and
closed-unmerged PRs fail closed with `lifecycle-acquisition.*` reason codes.
`planning` and `implementation` are never emitted: the absence of a PR proves
neither, and no governed implementation-activity signal exists for arbitrary
backlog issues yet.

Production seam: `lifecycle_stage_from_acquisition` adapts an acquired result
to the `LifecycleStage | None` input of `LiveCandidateEvidence` /
`LiveCurrentIssueSnapshotReader`, preserving the existing
`candidate-evidence.no-canonical-lifecycle-stage` fail-closed behavior when no
stage is acquirable. `primary_claims` and `approval_applicability` remain
separately governed boundaries. The live source of that evidence is the #3441
reader below.

## Read-only PR-lineage evidence acquisition (#3441)

`pr_lineage_reader.py` is the production-reachable, read-only *source* of the
facts the #3433 evaluator consumes. It owns no GitHub client, selector,
scheduler, store, lifecycle evaluator, linkage parser, or authority: it works
over three injected read ports (a pull-request page reader, an exact
pull-request reader, and a default-branch SHA reader) plus the caller's existing
`SingleIssueTransport`, and hands the unchanged `acquire_lifecycle_stage`
exactly its input types.

Flow for one open issue:

1. read the exact issue (structured state + content-addressed
   `github-issue-v1` revision, via the existing `LiveIssueReader`) and the
   current default-branch SHA;
2. enumerate the **all-state** pull-request population once per run and prove
   it complete *inside the reader*: every page succeeded, each `next_page` is
   the contiguous successor, the last page carries positive terminal proof (from
   the provider's canonical `validated_next_page`, endpoint `pulls`), the
   explicit page bound (`DEFAULT_MAX_PAGES = 40`) was not exhausted, every record
   is well formed and belongs to this repository, and no PR was listed twice (a
   repeat, even an identical one, proves a PR was opened mid-listing and never
   observed: `pr-lineage.population-shifted-during-listing`). The shadow CLI's
   page reader also refuses a page with no `next` whose `last` relation names
   another page as terminal proof. Anything else is an *incomplete* enumeration,
   which the evaluator answers with `unavailable` -- an exhausted bound is never
   negative evidence;
3. classify every pull request against the issue with the existing
   `parse_pr.parse_linked_issue_result`: a resolved closing directive to this
   issue is a **claim**; a non-authoritative or ambiguous reference (`Part of`,
   `Refs`, qualified or multi-target references, title-only mentions) is an
   **ambiguous claim** that is *passed to the evaluator* (which answers
   `manual-review`) rather than dropped. That includes an issue named by a PR
   whose claim resolves to a different issue, and any same-repository issue
   GitHub would close on merge (`detect_github_effective_closing_references`,
   which masks nothing) that is not the claim. A declared `Non-closing:`
   reference is recorded as evidence but is not a claim; everything else is
   unrelated. One PR has one role per issue (claim, then ambiguous, then
   declared non-closing);
4. re-read each claim or ambiguous pull request by number and require it to
   agree with the listing (state, draft, merged, head SHA, base repository,
   title/body digest); disagreement is drift and makes the enumeration
   incomplete;
5. require the default branch not to have moved while the listing was read or
   since (`pr-lineage.default-branch-moved`);
6. call the unchanged evaluator. A closed issue is `closed` from GitHub's own
   state and the lineage is not consulted.

Consumer: `LiveCandidateEvidence` accepts a `lifecycle_stage_acquirer`
(mutually exclusive with the static `lifecycle_stage`).
`LiveCandidateEvidenceReader` consults it at the lifecycle input's canonical
position, and when it composes, after its own fresh issue snapshot, it re-checks
the result with `acquisition_bindings_current`; a changed issue revision or
repository SHA fails closed as `candidate-evidence.lifecycle-stage-stale`. The
shadow CLI never reaches that composition (its `primary_claims` input is
`None`, so the reader fails closed first), and its record says
`consumer_boundary_revalidation: not-reached`. The production caller is
`scripts/agent-os-shadow-run.py`, whose `LivePullRequestPageReader` /
`LivePullRequestDetailReader` are GET-only and whose experiment record carries a
`lifecycle_stage_acquisition` section (population proof and per-candidate
outcome). `primary_claims` and `approval_applicability` stay `None` there: a
lifecycle stage alone never selects an issue.

Known limits: the evaluator emits only `closed` / `draft-pr` / `review` /
`merged`, so most open backlog issues remain `unavailable` (no verified claim);
this repository's frequent non-closing linkage (`Part of #N`) is an ambiguous
claim and therefore `manual-review`; one population snapshot serves a whole run,
so a pull request opened after it and before the run ends is not seen (the
default-branch check and the exact re-read bound, but do not close, that
window). Fixture and offline tests prove the contract; live behavior is
observed separately through the shadow CLI.

## Merge evidence repairs (#3463, non-closing)

- `PullRequestMergeEvidence` bounds PR title/body text at GitHub's body limit (65,536 characters, 4 UTF-8 bytes each) instead of the generic 4,096-byte text bound; it stays bounded and NUL-free. Other text fields keep the generic bound.
- `pull-request.multiple-implemented-issues` is part of the merge-authorization reason-code vocabulary and a blocking reason, so dual implemented-issue claims produce a typed refusal.
- Approval-comment footer normalization strips exactly one trailing Claude Code footer, either `https://claude.ai/code` (actual) or the legacy `https://claude.ai`; anything else still fails closed. The same parity holds for merge-authorization, refresh-authorization, and refresh-trigger footers, so a record accepted by one source is not rejected by another for its footer alone.
- Production caller: the read-only `merge_admission` job in `agent-os-governed-invocation.yml` runs `merge_admission_actions` and then `merge_applicability` with the same fixed transport and publishes both receipts. That job performs no merge; a positive dispatch receipt is admission only.
