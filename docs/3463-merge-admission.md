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
authority and cannot authorize current merge dispatch. The schema 1.1
candidate producer and evaluator branch were deleted in this change: no
active 1.1 creation or evaluation caller remains, and the canonical
evaluator returns `invalid` / `version.unsupported` for any 1.1 record.
Shared planning approval records, evaluators, and projections are untouched
and remain available for their own planning consumers; they are not merge
authority. The current dispatch path uses the canonical merge authorization
evaluator's native 1.2 branch and does not reacquire or reconstruct a
generic planning approval triple.

**Owner-provenance boundary (S2).** The merge source reader applies two
negative filters, and neither is positive proof of owner performance. A
trusted record comment posted through a GitHub App
(`performed_via_github_app` present, e.g. a connector app) is refused as
`source.app-performed-record` even when the displayed author is the owner:
live comments on this PR displayed owner authorship while performed by an
agent connector. A trusted record carrying an agent-attribution footer
(e.g. Claude Code) is refused as `source.trusted-record-malformed`: footers
are no longer stripped from merge authorization parsing, because stripping
erases in-band agent-generation evidence. Conversely, a comment posted with
the owner's PAT or OAuth token by an agent carries no app evidence and no
footer, and is indistinguishable from an owner-typed comment by any
provider field the reader can see.

**S2 resolution by owner decision (2026-10-25): the runtime human
approval card is the required human-origin attestation.** The
merge-authorization record remains an auditable representation only; it
does not independently establish human-origin authority. The dispatch
receipt enforces this: a content-passing result has status
`awaiting-human-attestation` with `merge_authorized` false and reason
`human-origin-attestation-required`, plus a `human_origin_attestation`
section naming the exact binding the card must cover (repository, PR
number, head SHA, base branch and SHA, merge method, authorization
identity and revision, scope fingerprint). No repository receipt ever
carries `merge_authorized=true` or human-origin attestation anymore.

**What the card actually exposes (audited, not assumed).** The approval
card is invisible to the agent and cannot be tapped or described by it.
A granted call's tool result carries only an approved/declined status --
no attestation id, no signature, no hash of the approved parameters.
The host-side approval history records an approval id, the invoked
command and parameters, request/decision timestamps, and a one-hour card
expiry, but that history is not queryable by a GitHub Actions executor
and carries no signature either. No standing merge grant exists (verified
against the live grant list at decision time). Consequence: the card is a
genuine enforcement gate **at the merge call itself** (the host observes
the tap before executing an `mcp.write` merge call), but it exposes **no
verifiable attestation evidence to a repository-side or Actions-side
verifier**. Any executor that is not the host-gated merge call must not
be activated until the platform supplies a signed attestation receipt
(grant id, timestamp, hash of approved parameters) verifiable by that
executor -- that is the precise capability boundary and the platform
handoff below. No token, approval object, service, or framework was
invented to paper over it; the binding parameters are existing receipt
fields, and there is deliberately no repository API that accepts an
attestation input (an agent cannot inject one).

**Executor rules (not activated by this change).** An executor may merge
only when BOTH hold: (a) a dispatch receipt with status
`awaiting-human-attestation`, `dispatch_checks_passed` true, and a
canonical result of `applicable` for the exact parameters; and (b) a
fresh per-call runtime approval card tap for exactly the receipt's
`human_origin_attestation.binding`, with no standing merge grant and a
re-prompt on any parameter change. One tap must never serve a different
parameter set or a second merge. Production merge execution remains
unwired; this change activates no executor.

**Reviewer eligibility (rule changed: exact-head review decoupled from
APPROVED state).** GitHub forbids pull request authors from approving
their own pull requests, and agent PRs are authored by the owner
account, so an APPROVED-at-head requirement made owner-only admission
impossible while adding no protection beyond the gates below. GitHub's
own Protect-main ruleset does not require it (required approving review
count is 0; it requires thread resolution and the authoritative
aggregate check). The rule is now: no CHANGES_REQUESTED review, zero
unresolved review threads, substantive independent QA on the exact head
plus aggregate CI green, and the owner's fresh runtime card tap as the
owner's approval at execution. Blocking-review and thread protections
are preserved: a blocking review appearing, or an unresolved thread
count changing, still fails dispatch and evaluation. `exact_head_reviewed`
remains in the evidence schema as a truthful audit record of whether an
APPROVED review existed at the head, but it no longer gates admission
and its drift no longer stales a binding. No new approval representation
was added; the card tap is the owner's approval, not a record.

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
  reconstruction and serialization only; the 1.1 candidate producer and
  evaluator branch are deleted. It carries the native schema 1.2 binding,
  candidate construction and canonical direct applicability.
- `merge_applicability.py`: verifies actual GitHub scope, checks, reviews,
  GraphQL review-thread completeness and the owner-authored merge record.
- `merge_admission_actions.py`: remains the non-authorizing candidate
  front door and dispatch contract.
- The redundant `merge_proposal.py` representation, its exclusive tests
  and the `_merge_proposal_binding` approval-triple branch were retired.
- Shared planning approval records, evaluators, projections and Scheduler
  approvals remain unchanged.

