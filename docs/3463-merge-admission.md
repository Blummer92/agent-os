# Merge admission via a typed MergeProposal (#3463, #2340 ADR-001)

## Status

Repository integration plus its production caller, complete within its
verified scope. The merge-executing dispatch and host enforcement proof
are outstanding (see "What this does not do").

## Production caller, trigger, authorization boundary, receipt path

- **Caller.** The `merge_admission` job in
  `.github/workflows/agent-os-governed-invocation.yml` is the production
  caller of `merge_applicability.evaluate_merge_dispatch_applicability`.
  It runs `merge_admission_actions` first, then `merge_applicability`
  with the same fixed transport file, and publishes both
  `receipt.json` (candidate) and `dispatch_receipt.json` (dispatch) as
  job artifacts (7-day retention) plus a step summary naming both.
- **Trigger.** An owner issue comment (user id 32861845, not a PR
  comment) starting with `/agent-os merge-admit `, parsed by the fixed
  `github_issue_comment_ingress` grammar into immutable selectors
  (PR number, exact head SHA, body SHA-256, merge method, actor,
  logical trigger id). No other actor, grammar, or comment text can
  reach this job.
- **Authorization boundary.** The job's permissions are read-only
  (`contents`, `issues`, `pull-requests`, `checks`, `statuses` read).
  It creates no authorization, posts no comment, and calls no merge
  API. A positive dispatch receipt is admission only.
- **Receipt-consumption path.** A future merge dispatch — separately
  authorized, not built here — must, immediately before mutation,
  re-verify that the dispatch receipt is `applicable` with
  `merge_authorized is true`, that its authorization record is still
  current and unconsumed, that `expected_head_sha` equals the live PR
  head reacquired at dispatch time, and that expiry is in the future;
  then merge natively with `expected_head_sha`, read back merged-at-head,
  and record a consumption observation so a second dispatch with the
  same authorization is refused as consumed.

## The chain, in order

1. **Fixed ingress (unchanged, #3661).** An owner `/agent-os merge-admit`
   comment on an issue triggers the read-only `merge_admission` job, which
   runs `merge_admission_actions.evaluate_merge_admission_transport`. That
   consumer reacquires the live PR and the trusted
   `agent-os-merge-authorization/v1` source, gates open/non-draft/unmerged,
   exact head, body SHA-256, mergeability, and base == main, and reconciles
   the 8 live-comparable binding fields. A fully matching record is a
   *candidate* receipt only: this module still hard-codes
   `merge_authorized=false` in every receipt, by design.
2. **Dispatch-time verification (extended).**
   `merge_applicability.evaluate_merge_dispatch_applicability` requires the
   candidate receipt, then verifies the trusted approval triple
   (`reacquire_approval_source`), its linkage to the authorization binding,
   live file scope (canonical `changed_scope_fingerprint`), live check
   states for the exact head, live reviews, and a lifecycle-mutation
   admission binding the owner's instruction to the exact head.
3. **Canonical applicability (new wiring).** After every dispatch check
   passes, the consumer assembles a typed `MergeProposal`
   (`merge-proposal/v1`, `scripts/agent_os_issue_acceptance/merge_proposal.py`)
   from the verified records and live PR evidence via
   `merge_authorization.build_merge_proposal`, and delegates to the
   canonical `evaluate_merge_authorization_applicability`. Only a canonical
   result of `applicable` produces a positive receipt: `status ==
   "applicable"`, `merge_authorized is true`,
   `canonical_applicability_evaluated is true`, with the canonical result
   (authorization id/revision, PR evidence id, changed bindings, reason
   codes, proposal id) embedded in the receipt. Any other canonical outcome
   keeps the receipt blocked, with the canonical reason codes preserved.
   Dispatch checks passing while the canonical gate fails is reported as
   exactly that — `dispatch_checks_passed is true` with
   `merge_authorized is false` — never as authorization.

## What a MergeProposal is (and is not)

A `MergeProposal` is frozen, content-bound evidence for one repository, PR
number, exact head, base branch/identity, merge method, file-scope
fingerprint, allowlist/forbidden paths, required tests, required checks,
review state, PR metadata fingerprint, closure admission ids, ready state,
and approval-triple linkage (approval id/revision, applicability identity,
approval expiry, projection id). Its `proposal_id` is
`merge-proposal:<sha256>` over every other field, so tampering with any
bound field invalidates the identity at construction.

It is NOT a task-planning proposal: it carries no issueplan, planning
graph, or cohort state, and the canonical evaluator's merge branch checks
it field-by-field against live PR evidence and the trusted approval triple
instead of recomputing task-planning approval applicability. That
recomputation would be the wrong check for a merge; the approval triple
itself was reacquired through the trusted source readers, and the
authorization record's state, expiry, and binding drift are still enforced
by the evaluator around the merge branch.

It confers no authority by itself, posts nothing, and dispatches nothing.
`build_merge_proposal` refuses to assemble a proposal unless the approval
is APPROVED, the supplied applicability is applicable and matches the
approval, and the projection matches PR evidence. A matching proposal
alone never produces `merge_authorized=true`; only the canonical evaluator,
given an AUTHORIZED record with no binding drift, can do that.

## Host-consumable receipt contract

A dispatch consumer (or host step) may treat a receipt as merge admission
only when ALL of the following hold:

- `receipt.status == "applicable"` and `receipt.merge_authorized is true`;
- `receipt.authorization_id` names a trusted owner-authored
  `agent-os-merge-authorization/v1` record still current at dispatch time;
- `receipt.expected_head_sha` equals the live PR head SHA reacquired at
  dispatch time;
- `receipt.authorization_expires_at` is in the future at dispatch time;
- the native merge call carries `expected_head_sha ==
  receipt.expected_head_sha`;
- after the merge, the post-merge readback shows merged-at-head and a
  consumption observation is recorded for the authorization (so a second
  dispatch with the same authorization is refused as consumed).

A `blocked` receipt, or any receipt with reason codes, is never
authorization. Reusing a receipt after expiry, or after its record was
consumed, superseded, revoked, or invalidated, is forbidden.

## Merge approval construction (Option A, design A1)

The D5 preflight failure is repaired: a merge approval triple can
now be constructed from a genuine owner merge decision plus live
PR evidence, without fabricating planning evidence. See
`scripts/agent_os_issue_acceptance/merge_approval.py` (adapter),
`merge_producer.py` (E2 producer), and `merge_executor.py` (A2
executor). Independent security review of the design (Phase 4)
verdicted A1 PASS WITH FINDINGS; the blocking finding (B-1) and
non-blocking findings (N-1–N-6) are carried into the code and tests
as stated below.

- **Adapter** (`build_merge_approval_triple`): validates the exact
  owner decision against live PR evidence (repository, PR number,
  head, base branch + base identity, method, authorizer, decision
  id recomputed from decision + PR scope/metadata, expiry, ready
  state), derives every binding field from decision + PR facts,
  builds the approval through the existing generic
  `record_approval_decision` state machine, and self-verifies the
  triple (serialize/reconstruct round-trip plus
  `build_merge_proposal`) before returning it. It never constructs
  a `DraftTaskProposal`, issueplan evidence, or repository-state
  evidence, and it never bypasses the triple reader: the reader
  checks linkage, states, and reconstruction, never binding
  provenance, and the merge evaluator checks triple consistency
  plus live PR evidence, never planning evidence.
- **Binding identity (A1)**: `proposal_id` uses the additive
  `merge-approval:` prefix (allowed alongside
  `draft-task-proposal:` in `approval_records.py` and
  `approved_execution_projection.py`; every previously valid id
  remains valid, planning behavior unchanged). `proposal_version`
  is `merge-approval/1`, the single cohort is classified `merge`,
  and the single node names the merge operation
  (`merge:<repository>:<pr_number>`). Approval kind is reused
  `SOURCE_MUTATION` (a merge mutates the target branch's source);
  schema is 1.0 (no semantic subject). Planning-named digest
  fields carry merge-derived hashes (decision digest in
  `handoff_digest`, scope digest in `graph_digest`, PR-evidence
  digest in `planning_result_digest`, check-evidence hash in
  `scanner_result_fingerprint`, merge current-state hash under
  the legacy `issueplan-current-state:` name): a naming debt,
  documented here and in the module, not invented planning
  evidence — no consumer verifies any of these fields against a
  planning store.
- **Producer** (`produce_merge_authorization`): posts the triple
  plus the merge authorization (built with the existing canonical
  builders) to the target PR's conversation and returns success
  only when both trusted readers read back CURRENT. On a readback
  failure it raises; posted records are not retracted ("not
  verified" is not "not posted"), and dispatch must not proceed
  on a producer failure.
- **Executor** (`execute_merge`): merges only when BOTH gates
  pass — a positive, trigger-correlated Actions
  `dispatch_receipt.json` (status applicable, merge_authorized,
  checks passed, canonical applicability evaluated, no reasons,
  consistent with trigger, authorization, and live evidence) AND
  fresh in-run canonical applicability (fresh reacquisition of
  both sources, fresh live PR evidence, `build_merge_proposal`,
  `evaluate_merge_authorization_applicability`). Either failure
  blocks with no merge call. The merge uses the exact head and
  bound method only. Post-merge readback must agree, then the
  CONSUMED revision is posted and read back. Result vocabulary is
  strict: `blocked` (gate failed, no merge attempted), `failed`
  (merge may have happened but verification/consumption failed —
  escalate, never report as success), `dry-run-applicable`
  (gates passed in dry-run, nothing merged or posted), `merged`.
  `decision_id` is correlation/audit only; single-use is the
  posted CONSUMED revision plus the merged-state gate.
- **Revocation, corrected (B-1)**: posting a revocation revision
  alongside the approved revision makes the approval reader return
  NEEDS_DECISION (`source.trusted-record-malformed`), NOT STALE.
  Dispatch still blocks (non-`current` status), but the diagnostic
  reads as corruption. Do NOT "fix" this by changing the approval
  reader to latest-revision semantics inside this slice; that
  reader change needs separate authorization. (The merge
  authorization reader genuinely takes the latest revision, so
  the CONSUMED story is as stated.)
- **Process controls, not code guarantees (N-4)**: no code compares
  a record's `authorizer_id` to the owner id; `decision_id` is a
  content hash (integrity), not a signature (authenticity);
  decision authorship rests on the decision's provenance channel;
  the operative authorship check is comment author == snapshot
  owner login (+ `User` type) at readback; the adapter is invoked
  only from the producer by convention (no import restriction
  enforces it). None of this may be described as code-enforced.
- **Status**: the three modules exist and are tested with fake
  transports/clients (see `test_merge_approval.py`). They are NOT
  yet wired to a live GitHub Service Agent route: no production
  caller supplies real credentials, trigger comments, receipt
  artifacts, or live PR reads, and no live merge canary has run.
  That wiring and any canary remain separately authorized future
  work. Do not describe these modules as live production execution.

## What this does not do (explicitly out of scope)

- **No live producer route yet.** The E2 producer module
  (`merge_producer.py`) exists and is tested, but no production
  caller wires it to a live GitHub Service Agent client: how an
  owner decision reaches the producer, with what authentication,
  is route wiring that remains separately authorized future work.
  No code in this change posts to live GitHub, and no hand-crafted
  serialized record may be treated as produced evidence.
- **No live merge dispatch.** The A2 executor module
  (`merge_executor.py`) exists and is tested, but no production
  caller wires it to a live merge call, and no MCP tool,
  credential, or protected-setting change is made here. The one
  workflow change is read-only: the existing `merge_admission`
  job additionally runs the dispatch evaluator and publishes its
  receipt; it grants no merge authority. A live merge canary
  remains separately authorized.
- **No host enforcement proof.** Repository tests prove the canonical
  gate evaluates and refuses correctly; they do not prove that any
  connector or host merge call enforces it. That proof requires a
  separately authorized live merge with contemporaneous evidence
  (command, record, fresh applicability, positive receipt, expected-head
  dispatch, readback, consumption observation).
- **Closing references.** The dispatch consumer builds PR evidence with
  no closure admissions, so a PR whose body carries a GitHub-effective
  closing reference, or whose authorization binding carries closure
  admission ids, blocks at the canonical step (fail-closed). Reacquiring
  closure admissions at dispatch time is future work, not claimed here.
- **Check app identity.** Dispatch-time check evidence reuses the
  binding's context/app_identity with live rolled-up states and the live
  head as tested SHA; the live rollup reports states per context only.
  State and head are live-verified; app identity is binding-carried.

## Files

- New: `scripts/agent_os_issue_acceptance/merge_proposal.py`,
  `tests/agent_os_issue_acceptance/test_merge_proposal.py`,
  `docs/3463-merge-admission.md` (this file).
- New (merge-approval repair, Option A / design A1):
  `scripts/agent_os_issue_acceptance/merge_approval.py`,
  `merge_producer.py`, `merge_executor.py`,
  `tests/agent_os_issue_acceptance/test_merge_approval.py`.
- Changed (merge-approval repair): `approval_records.py` and
  `approved_execution_projection.py` (additive `merge-approval:`
  proposal-id prefix alongside `draft-task-proposal:`; no existing
  id invalidated, no planning behavior changed),
  `tests/agent_os_issue_acceptance/test_architecture_boundaries.py`
  (three architecture-domain classification lines for the new
  modules, in the `approval` domain). The package facade
  (`__init__.py` `__all__`) is intentionally UNCHANGED: exporting
  the new modules requires a separately authorized facade
  decision, which has not been granted; the modules are usable
  via direct module import, as all internal callers already do.
- Changed: `scripts/agent_os_issue_acceptance/merge_authorization.py`
  (MergeProposal type import, `build_merge_proposal`, merge branch in
  `_current_binding`), `scripts/agent_os_issue_acceptance/merge_applicability.py`
  (canonical delegation, positive applicable receipt),
  `scripts/agent_os_issue_acceptance/merge_admission_actions.py`
  (docstring/contract note only; its hard-coded `false` is unchanged),
  `tests/agent_os_issue_acceptance/test_merge_applicability.py` (ceiling
  test replaced by the positive-path test plus new negative tests),
  `tests/agent_os_issue_acceptance/test_architecture_boundaries.py`
  (one architecture-domain classification line for `merge_proposal`).
- Changed (continuation): `.github/workflows/agent-os-governed-invocation.yml`
  (the `merge_admission` job now also runs `merge_applicability` with
  the same transport and publishes `dispatch_receipt.json`; read-only
  permissions unchanged), `merge_authorization_source.py`,
  `pr_branch_refresh_authorization_source.py`, and
  `pr_branch_refresh_actions.py` (Claude Code footer parity with
  `approval_source.py`: exactly one of the `/code` or legacy bare
  footers is stripped; doubled/embedded forms still fail closed).
- Unchanged: MCP server/profile, credentials, protected settings,
  approval readers, and the canonical task-planning evaluator branch.
