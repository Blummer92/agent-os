# Coding Cockpit current operational view

The Coding Cockpit is a display-only projection over existing canonical Agent OS evidence. It does not own issue state, validation, routing, authorization, lifecycle, or execution semantics.

`coding_cockpit_view.py` composes the existing `CodingCommandCenterHandoff` with the exact `IssueOperationalState` that the handoff references. Identity disagreement fails closed.

The concise operator view exposes:

- current repository/issue plus primary PR, branch, and exact head when canonical evidence supplies them;
- operational outcome and lifecycle stage;
- existing executor route / execution surface;
- validation state, evidence reference, and freshness;
- the canonical primary blocker and whether manual review is required;
- the existing smallest safe next action and handoff target;
- canonical state/source references.

Missing values remain explicit `unavailable`. Stale, conflicting, invalid, and needs-decision operational states surface manual review rather than optimistic guidance. The view never turns `ready`, `passed`, a route, or a next action into write, merge, closure, readiness, protected-setting, production, credential, or external-system authority.

This module intentionally does not perform Notion writes or introduce a Notion connector, synchronization service, scheduler, queue, background worker, or second state model.