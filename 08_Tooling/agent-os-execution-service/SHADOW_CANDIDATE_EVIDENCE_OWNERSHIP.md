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
| repository source revision | GitHub API: the repository's default-branch HEAD SHA, read live by `scripts/agent-os-shadow-run.py` (`_fetch_repository_head_sha`: `GET /repos/{repo}` -> `default_branch`, then `GET /repos/{repo}/branches/{branch}` -> `commit.sha`) | the API-based equivalent of the "current checkout SHA" the snapshot-reader contract expects the caller to know; fail-closed (`RuntimeError` -> CLI transport failure) when the ref cannot be read | fail closed: `candidate-evidence.no-canonical-repository-source-revision` (unreachable only when the API ref read fails) |
| lifecycle / operational state | `IssueOperationalState` owner via unchanged #1451 `acquire_issue_operational_state` | live snapshot + lifecycle stage + approval/dependency/claim/validation/freshness acquirers | fail closed: any missing acquirer input fails closed with its own named reason; conflicting composition raises into `candidate-evidence.composition-contract-violation` |
| lifecycle stage (#3441) | unchanged #3433 `acquire_lifecycle_stage`, fed by the read-only `PrLineageAcquirer` (`scripts/agent_os_issue_acceptance/pr_lineage_reader.py`) | per candidate: exact issue read + default-branch SHA, the run's self-proven all-state PR population, `parse_pr` classification, exact re-read of each referencing PR; revalidated against the reader's fresh snapshot with `acquisition_bindings_current` when the reader composes (the shadow CLI never reaches composition while `primary_claims` is `None`; its record says `consumer_boundary_revalidation: not-reached`) | fail closed: `candidate-evidence.no-canonical-lifecycle-stage` (acquisition reason codes in `failure_detail`: `lifecycle-acquisition.*`, `pr-lineage.*`); `candidate-evidence.lifecycle-stage-stale` when the issue revision or repository SHA moved |
| primary PR claim | existing claim owner — no canonical live PR-linkage reader exists; #1460 forbids inventing one | caller-supplied `tuple[PrimaryIssueClaim, ...]` only | fail closed: `candidate-evidence.no-canonical-primary-claims` |
| dependency state/depth | #1185/#1197 `DependencyReadinessEvidence` authority via the canonical `RepositoryEvidenceReader` (`LiveRepositoryEvidenceReader`; the #1155 truthful always-`UNAVAILABLE` reader when the caller supplies none) | reused #1464 `dependency_state_from_evidence` projection; `dependency_depth` is explicit request context (`--dependency-depth`, non-negative int; absent stays absent) | fail closed: no reader → `DependencyState.UNKNOWN` (in-value); missing `dependency_depth` → `candidate-evidence.no-canonical-dependency-depth` |
| validation state | `scripts.agent_os_remote_validation` advisory pre-PR evidence authority via the canonical `RepositoryEvidenceReader` | reused #1464 `validation_state_from_evidence` projection | fail closed: no reader → `ValidationState.NOT_RUN` (in-value); unmappable `UNAVAILABLE` evidence → `candidate-evidence.composition-contract-violation` |
| freshness/currentness | the shadow-run composition itself: it performs the live issue read, so the evidence is current as of `observed_at` (the `live_route_context.py` precedent for live-verified evidence) | `FreshnessState.CURRENT` supplied by the CLI composition, not the general reader (which stays fail-closed) | fail closed: `candidate-evidence.no-canonical-freshness-state` (only when the composition cannot supply it) |
| approval/applicability | existing evaluator `approval_records.evaluate_approval_applicability` — its evidence graph is not reconstructible for arbitrary backlog issues | caller-supplied `ApprovalApplicabilityResult` only | fail closed: `candidate-evidence.no-canonical-approval-applicability` |
| implementation authorization | existing authority projection, derived inside #1451 via `AuthorityProjection.from_approval_applicability` | canonical evaluation/current binding; optional execution/external-write acquirers left unset (fail-closed `NOT_APPLICABLE`) | fail closed: follows the approval input |
| operating mode | `operating_mode.py` `evaluate_operating_mode_decision` (unchanged) | acquired state + explicit request mode (`--requested-mode`, one of the `RequestedMode` values; absent stays absent) + the CLI's honest read-only environment self-description (`local_execution_state=UNPROBED`, `push_state=UNSUPPORTED` -- this composition never executes or mutates, so these states can authorize nothing) | fail closed: `candidate-evidence.no-canonical-requested-mode` when absent (an absent mode would otherwise be silently defaulted to `PLANNING`); `candidate-evidence.no-canonical-environment-capability` when no environment owner exists |
| explicit request/substitution semantics | existing request interpretation — no canonical live owner in the shadow path | explicit request context (`--substitutable` / `--no-substitutable`; absent stays absent) | fail closed: `candidate-evidence.no-canonical-substitutable` (never defaulted to `True`) |

## Identity discipline

Repository SHA (`source_revision`) and the content-addressed issue revision
(`github-issue-v1:<sha256>` in `evidence_ids`) remain distinct throughout the
composition. The `CandidateIssueEvidence` model enforces the two load-bearing
joins: `operational_state.issue_number == issue_number` and
`mode_decision.source_operational_state_id == operational_state.state_id`.

## Current shadow-run wiring

`scripts/agent-os-shadow-run.py` wires the production reader with every input
that has an actual source in the shadow-run context:

- the live read seam (issue snapshot over the injected transport);
- the repository HEAD SHA, read live from the GitHub API;
- `FreshnessState.CURRENT` (the composition performs the live read itself);
- the honest read-only environment self-description
  (`UNPROBED` local execution, `UNSUPPORTED` push);
- explicit request context (`--requested-mode`, `--dependency-depth`,
  `--substitutable` / `--no-substitutable`; absent stays absent).

`lifecycle_stage` (#3441) is acquired per candidate from live PR lineage by the
`PrLineageAcquirer` (see `scripts/agent_os_issue_acceptance/README.md`): a stage
exists only where GitHub's own closed state or exactly one verified closing
claim establishes it, so for most open backlog issues the reader still
fail-closes on it (`candidate-evidence.no-canonical-lifecycle-stage`, with the
`lifecycle-acquisition.*` reason in the record's `lifecycle_stage_acquisition`
section). The selector stops at the first candidate with incomplete
evidence; once it has read at least one candidate, the CLI acquires the
remaining candidates' lineage (at most 25, reusing the same cached
pull-request population) into `record_only_candidates`. Each entry carries
`selection_input: false`; the list is evidence for the record only, never
reaches the selector, and is not part of the evidence-ledger inputs digest.
`primary_claims` and `approval_applicability` have no canonical live
owner for arbitrary backlog issues and remain `None`, so the reader
fail-closes on them next (`candidate-evidence.no-canonical-primary-claims`)
even when a lifecycle stage was acquired. These are #3329's bounded blockers:
surfaced with named reasons per the issue's acceptance criteria, not
manufactured. A lifecycle stage alone never selects an issue. The real-backlog acceptance canary
(Shadow Admission Test 2B) remains gated on #3328's legitimate cohort plus
caller-supplied request context; it is not claimed complete by this wiring.

## Validation

Focused fixtures:

```bash
PYTHONPATH=08_Tooling/workflow-scheduler/src:08_Tooling/agent-os-execution-service/src:08_Tooling/agent-memory-context-manager/src:. \
  python3 -m pytest tests/agent_os_issue_acceptance/test_live_candidate_evidence_reader.py \
                   tests/agent_os_issue_acceptance/test_shadow_run_cli.py -q
```

Ready-for-Review still requires the repository's current exact-head aggregate admission.


## #3441 D-A1 — Non-closing association policy (2026-10-14; default activation 2026-10-21)

The read-only shadow CLI accepts `--association-policy declared-non-closing-v1`.
Since the owner's 2026-10-21 default-activation authorization, this is the CLI
default; omitting the flag selects `declared-non-closing-v1`, and
`closing-directive-v1` remains available as an explicit option.
No existing workflow or composite action default changes.
The existing `parse_pr` parser remains the sole PR-linkage authority.

Under this policy, parser `INFORMATIONAL` qualifies as an association when its
standalone `Non-closing: #N` directive covers exactly the requested issue
in the same repository and there are zero GitHub-effective closing references.
The reader includes these PRs in the same complete-population, exact-detail
reread and currentness checks as closing claims. Bare `Part of #N`, competing
PRs, cross-repository references, multiple targets, and closing conflicts
retain fail-closed handling.

An open Draft associated PR maps to `draft-pr`, and open Ready to `review`.
A merged associated PR yields `manual-review` with reason
`lifecycle-acquisition.non-closing-pr-merged`, never `merged` or completion.
Closed-unmerged behavior is unchanged. The policy is recorded in
acquisition evidence when it is the declared-non-closing policy; the result
shape is otherwise unchanged.
`primary_claims` and `approval_applicability` remain unset by the CLI,
so an acquired lifecycle stage cannot independently select or execute.

Rollback: revert the default-activation change. Workflow activation,
Ready, merge, and issue closure require separate owner decisions.
