# Merge-specific authorization and read-only dispatch (#3463, #2340)

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
2. **Dispatch-time verification.**
   `merge_applicability.evaluate_merge_dispatch_applicability` requires a
   currently authorized schema 1.2 merge record, re-verifies its trusted
   owner-authored source, complete PR changed files and forbidden paths,
   required check states, reviews, every review-thread page, and the existing
   lifecycle-mutation admission. Schema 1.1 records remain readable but never
   authorize current dispatch.
3. **Canonical merge applicability.** The same canonical
   `evaluate_merge_authorization_applicability` compares the native schema
   1.2 binding directly against fresh PR evidence without reconstructing
   `ApprovalRecord`, generic approval applicability, execution projections
   or a separate `MergeProposal` representation. Only `applicable` with
   `merge_authorized=true` produces positive admission. No merge is executed.

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

## Native merge-specific authorization (schema 1.2)

The merge-dispatch consumer accepts only current, trusted owner-authored
`agent-os-merge-authorization/v1` comments containing a schema **1.2**
merge-specific authorization record. A schema 1.2 binding no longer includes
planning approval IDs/revisions, applicability identities, approval expiry or
an approved execution projection ID. Its authority instead comes from the
authenticated repository-owner PR conversation, exact current authorization
revision, owner decision identity and content-bound current PR evidence.

`build_merge_authorization_candidate_from_pr` creates a **PENDING**
schema 1.2 candidate from typed PR evidence and an explicitly supplied owner
decision; it does not authenticate authorship or publish authority. Existing
`record_merge_authorization_decision` transitions still require an explicit
decision and retain expiry, revocation, replacement and consumption rules.
Dispatch must reacquire the trusted owner-authored record and independently
validate exact head/base, changed files, forbidden paths, required checks,
review status and all GitHub GraphQL review-thread pages. If GraphQL review
thread evidence is missing or incomplete, dispatch blocks; it never assumes
that unresolved review threads equal zero.

Historical schema **1.1** records reconstruct and serialize under their
unchanged schema and identity rules. They are not migrated into schema 1.2
authority and cannot authorize current merge dispatch. The previous
planning-approval-driven producer/evaluator remains solely for historical
compatibility and related legacy tests; the current dispatch path uses the
same canonical merge authorization evaluator's native 1.2 branch and does not
reacquire or reconstruct a generic planning approval triple.

The workflow remains read-only. Producing an admission receipt is **not** a
merge, and a production merge executor consuming an exact-head receipt is
not established by this repository refactor. No new owner approval
requirement is introduced.

## What this does not do (explicitly out of scope)

- **No authenticated producer posting path.** How an owner decision becomes
  a trusted approval/authorization comment on a PR conversation — which
  agent/route, with what authentication — is Phase 4 decision (e) and is
  NOT implemented here. No code in this change posts to GitHub, and no
  hand-crafted serialized record may be treated as produced evidence.
- **No merge dispatch.** No repository code calls the GitHub merge API,
  and no MCP tool, credential, or protected-setting change is made here.
  The one workflow change is read-only: the existing `merge_admission`
  job additionally runs the dispatch evaluator and publishes its
  receipt; it grants no merge authority. The dispatch owner
  (repo-owned Actions dispatch vs. product-side connector gating,
  decisions (a)/(b)) is still undecided for the merge-executing step.
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

## Files and ownership

- `merge_authorization.py`: retains historical schema 1.1 record
  reconstruction while adding the native schema 1.2 binding, candidate
  construction and canonical direct applicability.
- `merge_applicability.py`: verifies actual GitHub scope, checks, reviews,
  GraphQL review-thread completeness and the owner-authored merge record.
- `merge_admission_actions.py`: remains the non-authorizing candidate
  front door and dispatch contract.
- The redundant `merge_proposal.py` representation, its exclusive tests
  and the `_merge_proposal_binding` approval-triple branch were retired.
- Shared planning approval records, evaluators, projections and Scheduler
  approvals remain unchanged.

