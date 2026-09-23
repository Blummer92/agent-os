# Future Growth Strategy

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth. Guidance for scaling documentation as Agent OS grows, without adding duplication.

The governing rule is unchanged: shared rules live once in shared standards, agent-specific
rules live in overlays, and registry data lives in `04_Registry/`
(`00_Governance/ownership-and-source-of-truth.md`). Growth should reinforce that, not
work around it.

## How to add each kind of thing

- **New connector:** add an adapter spec that inherits
  `01_Shared_Standards/navigation/connector-adapter-framework.md`. Do not fork the
  framework per system.
- **New agent:** only when `04_Registry/` proves a repeatable role existing agents cannot
  own (`00_Governance/agent-creation-policy.md`). Otherwise extend an existing overlay.
- **New repository:** register navigation for it under `04_Registry/` (as the DMSC
  proposal does); do not copy its rules into this map.
- **New classroom workflow:** keep planning/readiness in Notion and student-facing
  artifacts in approved Drive folders per `AGENTS.md`; add only the governed standard to GitHub.
- **New standard:** create it in the correct `01_Shared_Standards/` domain, keep it under
  the line limit, reference governance instead of restating it, then add an inventory row
  (or regenerate the inventory).

## Index + companion pattern

This map uses an **index + companion documents** layout: a lightweight entry point that
routes to focused, individually reviewable, sub-100-line companions. This is the
recommended pattern for other large documentation areas as they grow (for example the
navigation stack already uses a README index). Reusing one pattern keeps the repository
navigable for humans and agents and keeps each file small enough to review, test, and
eventually generate.

## Guardrails as it scales

- Prefer indexes, cross-links, and extension notes over duplicate standards.
- Add a test for every recurring agent failure, ambiguous navigation path, or
  source-of-truth conflict (extend `07_Agent_Tests/`).
- Regenerate the inventory, graph, concept ownership, and metadata rather than editing
  them by hand once generation exists.
