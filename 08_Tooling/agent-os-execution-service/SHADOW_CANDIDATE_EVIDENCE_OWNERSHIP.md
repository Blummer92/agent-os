# Shadow Candidate Evidence — Field-by-Field Owner Mapping (#3329)

Production mapping for `CandidateIssueEvidence`
(`scripts/agent_os_candidate_packet/executable_lane_selection.py`), composed by
`scripts/agent_os_issue_acceptance/live_candidate_evidence_reader.py`
(`LiveCandidateEvidenceReader`, the production `CanonicalCandidateEvidenceReader`)
and consumed read-only by `select_shadow_issue` in
`agent_os_execution_service/shadow_issue_selection.py`.

The reader is a thin binding/adapter boundary mirroring the merged #1464
pattern (`live_compute_control_binding.py`). It owns no lifecycle, claim,
freshness, dependency, validation, approval, authorization, or operating-mode
semantics. For every required field: canonical evidence available means
adapt/reuse; canonical evidence unavailable or ambiguous means fail closed to
`None`, which the seam reports as `shadow-selection.candidate-evidence-incomplete`.
No field is ever inferred from issue prose, labels, timestamps, scanner order,
issue number, or AI judgment.

## Required evidence mapping

| Input | Canonical owner/source | Production acquisition path | Unavailable/ambiguous behavior |
|---|---|---|---|
| issue/repository identity | existing scanner/live issue contracts (`LiveIssueReader` over injected `SingleIssueTransport`) | live single-issue read per admitted candidate; #1451 enforces `snapshot.repository`/`snapshot.issue_number` identity joins | fail closed: `candidate-evidence.issue-read-failed:<outcome>` on transport failure; `candidate-evidence.repository-identity-mismatch` on repository mismatch |
| issue revision | existing `issue_source_revision` contract (`scripts/agent_os_github_issue_provider/revision.py`) | content-addressed `github-issue-v1:<sha256>` derived inside the reused #1464 `LiveCurrentIssueSnapshotReader`; carried in `evidence_ids`; the seam joins it against the scanned revision (`candidate-revision-mismatch`) | fail closed: `candidate-evidence.composition-contract-violation` when the payload cannot yield a revision |
| repository source revision | existing repository/currentness owner — none exists in the shadow path | caller-supplied canonical SHA only (e.g. a governed checkout identity) | fail closed: `candidate-evidence.no-canonical-repository-source-revision` |
| lifecycle / operational state | `IssueOperationalState` owner via unchanged #1451 `acquire_issue_operational_state` | live snapshot + caller-supplied lifecycle stage + approval/dependency/claim/validation/freshness acquirers | fail closed: any missing acquirer input fails closed with its own named reason; conflicting composition raises into `candidate-evidence.composition-contract-violation` |
| primary PR claim | existing claim owner — no canonical live PR-linkage reader exists; #1460 forbids inventing one | caller-supplied `tuple[PrimaryIssueClaim, ...]` only | fail closed: `candidate-evidence.no-canonical-primary-claims` |
| dependency state/depth | #1185/#1197 `DependencyReadinessEvidence` authority via the canonical `RepositoryEvidenceReader` (`LiveRepositoryEvidenceReader`; the #1155 truthful always-`UNAVAILABLE` reader when the caller supplies none) | reused #1464 `dependency_state_from_evidence` projection; `dependency_depth` is caller-supplied request context, never derived | fail closed: no reader → `DependencyState.UNKNOWN` (in-value); missing `dependency_depth` → `candidate-evidence.no-canonical-dependency-depth` |
| validation state | `scripts.agent_os_remote_validation` advisory pre-PR evidence authority via the canonical `RepositoryEvidenceReader` | reused #1464 `validation_state_from_evidence` projection | fail closed: no reader → `ValidationState.NOT_RUN` (in-value); unmappable `UNAVAILABLE` evidence → `candidate-evidence.composition-contract-violation` |
| freshness/currentness | existing freshness/currentness owner(s) — no general-purpose owner exists | caller-supplied `FreshnessState` only | fail closed: `candidate-evidence.no-canonical-freshness-state` |
| approval/applicability | existing evaluator `approval_records.evaluate_approval_applicability` — its evidence graph is not reconstructible for arbitrary backlog issues | caller-supplied `ApprovalApplicabilityResult` only | fail closed: `candidate-evidence.no-canonical-approval-applicability` |
| implementation authorization | existing authority projection, derived inside #1451 via `AuthorityProjection.from_approval_applicability` | canonical evaluation/current binding; optional execution/external-write acquirers left unset (fail-closed `NOT_APPLICABLE`) | fail closed: follows the approval input |
| operating mode | `operating_mode.py` `evaluate_operating_mode_decision` (unchanged) | acquired state + caller-supplied requested mode + caller-supplied `EnvironmentCapabilityEvidence`; the `state_id` join is preserved by the evaluator and re-checked by the `CandidateIssueEvidence` model | fail closed: `candidate-evidence.no-canonical-requested-mode` when absent (an absent mode would otherwise be silently defaulted to `PLANNING`); `candidate-evidence.no-canonical-environment-capability` when no environment owner exists |
| explicit request/substitution semantics | existing request interpretation — no canonical live owner in the shadow path | caller-supplied `substitutable` only | fail closed: `candidate-evidence.no-canonical-substitutable` (never defaulted to `True`) |

## Identity discipline

Repository SHA (`source_revision`) and the content-addressed issue revision
(`github-issue-v1:<sha256>` in `evidence_ids`) remain distinct throughout the
composition. The `CandidateIssueEvidence` model enforces the two load-bearing
joins: `operational_state.issue_number == issue_number` and
`mode_decision.source_operational_state_id == operational_state.state_id`.

## Current shadow-run wiring

`scripts/agent-os-shadow-run.py` wires the production reader with the live
read seam only. Every other required canonical input currently has no
canonical live owner in that context, so the reader fail-closes on the first
missing owner (`candidate-evidence.no-canonical-repository-source-revision`)
and the experiment record carries that exact named reason. The real-backlog
acceptance canary (Shadow Admission Test 2B) remains gated on #3328's
legitimate cohort plus caller-supplied request context; it is not claimed
complete by this wiring.

## Validation

Focused fixtures:

```bash
PYTHONPATH=08_Tooling/workflow-scheduler/src:08_Tooling/agent-os-execution-service/src:08_Tooling/agent-memory-context-manager/src:. \
  python3 -m pytest tests/agent_os_issue_acceptance/test_live_candidate_evidence_reader.py \
                   tests/agent_os_issue_acceptance/test_shadow_run_cli.py -q
```

Ready-for-Review still requires the repository's current exact-head aggregate admission.
