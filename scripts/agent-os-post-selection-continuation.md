# Post-selection capability-transition continuation (#1237)

## Failure removed

The pre-tool half of #1237 resolves the governed route before a tool is
selected. This is the other half: a tool has *already* been selected and then
proves insufficient for the exact next bounded operation.

```text
same authorized mission -> ordinary file read insufficient/truncated
-> unsafe whole-file replacement correctly rejected
-> alternate exact-blob capability discovered -> blocker resolved
-> execution nevertheless stopped with a handoff to the user
```

Hard invariants:

```text
one tool/action unavailable or insufficient != Agent OS mission unavailable
alternative capability discovered           != user handoff required
```

## Classifications

The six states are #1237's, unchanged. No seventh state is added.

| Classification | Continues | May mutate |
| --- | --- | --- |
| `capability-alternative-available` | yes | unless state already present |
| `partial-effect-reconciliation-required` | no — read back first | no |
| `no-capable-authorized-route` | no — one blocker + clearing condition | no |
| `currentness-or-identity-unproven` | no — fail closed | no |
| `authority-or-scope-boundary` | no — `needs-decision` | no |
| `material-user-decision` | no — real product choice | no |

`capability-alternative-available` structurally cannot carry a blocker: the
dataclass rejects it. Discovery is therefore never renderable as a stop.

## Precedence

Fixed and fail-closed, strongest governance boundary first:

1. an adjacent lifecycle misrouted into this seam is refused outright;
2. a valid active foreign lease — never taken over;
3. an alternative that widens authority or changes lineage — never substituted;
4. a genuine material decision, including a route that already required one;
5. ambiguous prior effects — read back before any alternate write;
6. no approved alternative, or a repeated equivalent transition (#1200);
7. currentness or identity the caller has not reacquired;
8. otherwise the alternative is consumed and the mission continues.

## Prior effects

| Prior effect | Result |
| --- | --- |
| proven zero effect | alternative may perform the mutation |
| ambiguous | read back canonical state before any alternate write |
| desired state already present | converge; mutation suppressed, no second write |

## Same-lineage invariant

`ContinuationLineage` carries repository, issue, branch, pull request,
checkpoint, and lease. Equality is structural, so an alternative resolving to a
different branch, PR, checkpoint, or lease is rejected as an authority/scope
boundary rather than silently substituted. Every classification echoes the
original lineage and carries the `preserve-existing-lineage` and
`route-through-owning-writer` obligations.

## Ownership boundary

This module decides nothing that belongs to another issue:
- #918 owns routing; this consumes an already-selected route's outcome.
- #1039 owns surface prerequisites; its `ExecutionSurfaceAvailabilityOutcome` is
  the input, and an available surface raises rather than being reclassified.
- #1200 owns semantic no-progress; a repeated transition delegates, never retries.
- #1201 owns cross-generation evidence compatibility; a runtime-surface
  transition carries it as an obligation rather than reimplementing it.
- #1209 base drift, #1235 stale gates, #1251 red CI — refused, owner named.

It performs no I/O and holds no state. Proof flags are caller evidence; unset
means unproven, and unproven fails closed. It introduces no router, Scheduler,
lease, capability registry, checkpoint store, persistent state, retry engine, or
execution authority, and grants no execution, GitHub-write, merge,
issue-closure, or external-write authority.

## Regressions covered

- historical missing local `gh` — surface evidence only, mission continues;
- #1213 truncated whole-file view — rejected until exact blob identity is
  reacquired, then continued on the same lineage without a user handoff.

Tests: `tests/agent_os_execution_interface/test_post_selection_continuation.py`.

## Rollback

Remove `scripts/agent_os_execution_interface/post_selection_continuation.py`, its
test module, and this note. Nothing else depends on them; the pre-tool preflight,
locator, descriptor store, transport, Scheduler state, branches, and PRs are
untouched.
