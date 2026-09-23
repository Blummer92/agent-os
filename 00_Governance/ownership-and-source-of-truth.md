# Ownership And Source Of Truth

- Identify the system of record before changing any artifact.
- Do not duplicate policy text across modules.
- Shared rules live in shared standards.
- Agent-specific rules live in overlays.
- Registry data lives in `04_Registry/`.
- Superseded documents move to archive notes.

## Inheritance-First Documentation Policy

- Shared rules live once in shared standards.
- Overlays should contain only agent-specific exceptions, scope, stop conditions, and handoff rules.
- Registry files own routing, ownership, aliases, and version tables.
- Repeated inherited rules should be replaced with references only after the source-of-truth rule is clear.
