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
- optional lifecycle-mutation admission results.

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

## Deterministic regressions

The focused suite covers:

- completed dependency still projected as blocking;
- active implementation PR with stale blocked issue projection;
- obsolete exact-head evidence after a new commit;
- Ready-for-Review without merge authority;
- merged implementation with stale roadmap/dependency projection;
- merged PR with open issue requiring closure authority/admission;
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