# Lifecycle Reconciliation Contract

Issue: #996  
Parent design: #856  
Schema: `agent-os-lifecycle-reconciliation` `1.0`

## Purpose

Provide one pure, deterministic comparison between supplied canonical GitHub
lifecycle evidence and bounded normalized projections that may have gone stale.
The component plans reconciliation only. It performs no GitHub read or write and
creates no authorization.

## Reuse boundary

- `IssueOperationalState` in
  `scripts/agent_os_issue_acceptance/issue_operational_state.py` owns current
  operational truth.
- `LifecycleStateSnapshot` and lifecycle-mutation admission in
  `scripts/agent_os_issue_acceptance/lifecycle_mutation_guard.py` own exact
  mutation preconditions and admission.
- Existing merge authorization in
  `scripts/agent_os_issue_acceptance/issue_operational_state.py` remains the
  merge-authority source.
- Post-PR audit remains downstream terminal reporting and next-work advice.
- The GitHub Service Agent overlay at
  `02_Agent_Overlays/github-service-agent.md` defines the sole GitHub write
  executor.

The reconciler is only the comparison/planning seam between these contracts and
stale issue-body, roadmap, PR-description, label, dependency, claim, and
exact-head projections.

## Inputs

Callers supply immutable, already-normalized evidence for:

- repository and issue identity;
- one canonical `IssueOperationalState`;
- optional exact lifecycle snapshot;
- optional current primary PR/head evidence;
- dependency terminal/incomplete evidence;
- normalized issue-body, roadmap, and PR-description projections;
- exact-head validation evidence;
- optional lifecycle-mutation admission results;
- optional criterion-level satisfaction record (#3680): an evidence
  snapshot of the record produced by the #3678 verifier
  (`criterion_satisfaction.py`), handed over by the reporting-side
  producer as a plain mapping — `{repository, issue_number,
  issue_body_digest, status, criteria}` with one disposition and
  traceable evidence pointers per original acceptance criterion. This
  approval-domain consumer imports nothing from the reporting domain;
  it strictly validates the snapshot at the input boundary (exact
  shape and types, contiguous criterion indexes, and a declared
  status that must agree with the criteria under the verifier's own
  derivation — a forged `complete` claim over unsatisfied, stale,
  missing, contradicted, or absent criteria is rejected, never
  interpreted as complete) and stores a defensive copy, so later
  mutation of the caller's mapping cannot change behavior. The
  envelope identity is enforced against the identity this consumer
  already holds authoritatively: a snapshot whose `repository` or
  `issue_number` names a different issue than the reconciliation
  input's is rejected, so satisfaction evidence produced for one
  issue cannot be attached to another undetected; the stored snapshot
  classes enforce the same validation at construction, so no
  hand-built instance can bypass the boundary rules. The identity
  binding detects cross-issue attachment only — it does not
  authenticate that the criteria or digest were produced from that
  issue's body; provenance remains the producing verifier's and QA's
  responsibility, and verifying the digest against the body itself
  would require the body at this consumer, which is a producer/host
  dependency outside this contract. When the input carries no
  satisfaction record, input and result serialization are
  byte-identical to the pre-#3680 form; the manual judgment path
  below is unchanged.

The component does not parse arbitrary issue, roadmap, PR, or comment prose.

## Outcomes

Exactly one outcome is returned:

- `consistent` — no supplied contradiction requires reconciliation;
- `reconciliation-required` — deterministic stale projection or lifecycle action
  is identified;
- `needs-decision` — canonical evidence is partial, contradictory, stale in a
  material way, or contains multiple primary claims.

## Actions

Actions remain descriptive and side-effect free:

- `observation` — factual stale evidence such as obsolete exact-head validation;
- `projection-repair` — non-authoritative issue-body, roadmap, or PR-description
  projection should be synchronized to canonical evidence;
- `governed-lifecycle-mutation` — a GitHub lifecycle mutation is the expected
  repair but still requires the existing admission/authorization boundary;
- `merge` — reserved for separately authorized merge-shaped planning and never
  inferred from green checks, Ready state, or mergeability;
- `manual-decision` — canonical evidence must be resolved before any repair.

Every mutation-shaped action carries exact expected-state guards. Missing
admission or closure authority is represented explicitly; it never becomes an
implicit mutation.

When a satisfaction record is supplied, the result additionally carries a
`satisfaction` block: the envelope issue identity (`repository` and
`issue_number`) verbatim, the record's overall status, a `closure_ready`
signal (true only when the record reports complete satisfaction — every
criterion holds current, uncontradicted evidence), and the per-criterion
dispositions and evidence pointers verbatim. The closure-ready reporting
rule is:

- In the merged-PR/open-issue case, an incomplete record (any criterion
  unsatisfied, stale, missing, contradicted, or manual-review) blocks the
  close-issue projection: reconciliation reports a `manual-decision` action
  naming every blocking criterion by identity and disposition, and projects
  no close-issue mutation — even when closure authorization and admission
  exist.
- A complete record leaves the existing projection, authorization, and
  admission flow exactly as it was. Satisfaction is an evidence signal
  under the QA judgment; it is never closure authority, never substitutes
  for the closure authorization or the exact-issue admission, and a
  complete record alone never closes or authorizes closing anything.
- Consumers must reacquire the current satisfaction record at admission
  time; a record can age after reconciliation consumes it, and stale
  dispositions report not-closure-ready by the rule above.

The closure-admission judgment packet produced by
`closure_admission_actions.py` may cite the same record: when a closure
request carries a satisfaction snapshot (validated at the request
boundary under the same strict rules, including the envelope identity
checked against the closure decision's repository and issue number),
the receipt includes the envelope identity, per-criterion dispositions,
and evidence pointers verbatim inside its hashed core, so the citation
is integrity-bound by the receipt id and the verification gate
revalidates the block and recomputes it under the same conditional
rule. The receipt hash binds the cited block against later alteration
of the receipt; it does not authenticate the evidence itself —
authenticity rests with the producing verifier and the QA judgment,
exactly as for the packet's other caller-bound fields. When
no record is carried, the receipt is byte-identical to the pre-#3680
form.

## Deterministic regressions

The focused suite covers:

- completed dependency still projected as blocking;
- active implementation PR with stale blocked issue projection;
- obsolete exact-head evidence after a new commit;
- Ready-for-Review without merge authority;
- merged implementation with stale roadmap/dependency projection;
- merged PR with open issue requiring closure authority/admission;
- merged PR with open issue and authorized closure/admission issuing governed
  close and stale-label mutations (#3409);
- merged PR with open issue and no closure authority refusing close while
  still repairing stale `status:ready` when admitted (#3409);
- closed completed issue with stale `status:ready` repairing labels only, with
  no close mutation (#3377);
- post-mutation canonical readback converging to consistent (#3409);
- closed/superseded PR still projected active;
- stale lifecycle labels;
- duplicate primary claims;
- conflicting dependency evidence;
- deterministic input/result identities and authority preservation.

## Safety

No GitHub, network, filesystem, subprocess, environment, Scheduler, provider,
credential, production, classroom-artifact, Notion, Google Drive, or other
external-system access exists in this component. `side_effects_performed` is
always false. Reconciliation evidence never grants implementation, execution,
Ready-for-Review, merge, closure, or external-write authority.