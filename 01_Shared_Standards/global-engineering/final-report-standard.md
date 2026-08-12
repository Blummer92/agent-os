# Final Report Standard

Final-report field ownership, precedence, presentation profiles, and visible
ordering are canonical in `agent-interaction-output-standard.md`.

- Use its Base Report Contract for status, blockers, checks, next owner, handoff
  artifacts, files changed, tests run, docs updated, and remaining risks.
- Add bugs fixed, new tests, Notion updates, and memory recommendations as
  domain evidence when the governing task produces them.
- Specialized records such as `01_Shared_Standards/github/sprint-reporting-schema.md`
  remain canonical for their own evidence and are rendered through that contract.

This document is a compatibility pointer and must not define a competing output
schema or presentation order.

## Pattern + Docs Freshness Gate

For repository implementation reports, record the following as domain evidence
rendered through the canonical Base Report Contract; this section does not create
a competing field set or presentation order:
- existing pattern checked, or `none found`;
- reusable capability registry relevance checked, or `not applicable`;
- canonical implementation path;
- tests proving the pattern or behavior;
- docs updated;
- docs intentionally unchanged, with bounded reason; and
- changelog, module-version, and registry review result.

`Docs intentionally unchanged because...` is valid only when the change does not
alter public behavior, public interfaces, workflows, owner expectations,
standards, templates, or reusable capability records.

## Version
0.3.0

## Changelog
- 0.3.0 adds the Pattern + Docs Freshness Gate as repository-implementation domain evidence while preserving Agent Interaction Output Standard ownership of report fields and presentation order.
- 0.2.0 converted this document to a compatibility pointer for the Agent Interaction Output Standard.
