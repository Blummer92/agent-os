# Curriculum Language System v1 Roadmap

## Purpose

Define one governed sequence for unit vocabulary, lesson vocabulary, teacher language, student language, material language, and assessment language.

This roadmap coordinates repository standards and validation. It does not store live unit or lesson vocabulary, authorize classroom-artifact creation, or grant external-system write authority.

## Current State

Curriculum Language System v1 and its three post-v1 extensions are complete. The only active CLS work is roadmap synchronization through #639.

- GitHub owns CLS standards, overlays, tests, automation-readable rules, and this roadmap.
- Notion may hold actual unit vocabulary, lesson vocabulary, teacher planning, and source evidence after target and owner approval.
- Approved student-facing Slides, Docs, worksheets, and portfolios belong in Google Drive.
- No new vocabulary agent or parallel curriculum overlay hierarchy exists.

## Architecture

1. **Unit Vocabulary Map** classifies words across the unit lifecycle.
2. **Notion source audit** identifies where real unit and lesson vocabulary lives.
3. **Lesson Vocabulary Planner** selects words for current teaching and assessment.
4. **Language integration** connects vocabulary decisions to teacher talk, student language, slides, worksheets, and assessment prompts.
5. **Notion handoff** recommends data changes only when read-only evidence proves a gap.
6. **Validation** checks standards, inheritance, evidence boundaries, and prohibited hierarchy.
7. **Pipeline boundaries** preserve ownership, blockers, and non-authorization across Unit Alignment, Teacher Modeling, and Instructional Materials.

## Original V1 Sequence

| Order | Issue | Deliverable | Final state |
|---|---|---|---|
| 1 | #127 — CLS1 | This roadmap | completed |
| 2 | #128 — CLS2 | Unit Vocabulary Map standard | completed |
| 3 | #129 — CLS3 | Read-only Notion vocabulary source audit | completed |
| 4 | #130 — CLS4 | Lesson Vocabulary Planner response standard | completed |
| 5 | #131 — CLS5 | Student, teacher, material, and assessment language integration | completed |
| 6 | #132 — CLS6 | Governed Notion-field recommendation | completed / no implementation change |
| 7 | #133 — CLS7 | Structural validation and automation readiness | completed |

CLS2 precedes CLS4. CLS3 reads source evidence before CLS4 or any later Notion work proposes fields, values, or vocabulary.

## Post-V1 Extensions

| Order | Issue | Deliverable | Final state |
|---|---|---|---|
| 8 | #455 — historical CLS7 | Provisional unit-language discovery separated from canonical onboarding | completed |
| 9 | #456 — CLS8 | Play-by-play Teacher Modeling and bounded Materials extract | completed |
| 10 | #457 — CLS9 | Cross-agent ownership and route-back fixtures | completed |

#133 and #455 were both historically titled `CLS7`. Closed issues remain immutable historical evidence, so this roadmap disambiguates them by issue number and descriptive title rather than renaming or renumbering either issue.

## CLS6 Disposition

#132 completed the required planning recommendation. No Notion schema, property, relation, database, data, migration, backfill, permission, sharing, or production change was authorized or performed.

Any future Notion implementation requires a new bounded Level 2 issue after confirming the exact target, accountable owner, field model, pilot units, migration plan, validation, rollback, permissions, and production-write authorization.

## Canonical Risk Routing

- #368 owns deterministic focused-validation selection and any later bounded remote dispatch. It may map `tests/test_curriculum_pipeline_boundaries.py`; no CLS-specific selector should be created.
- #543 owns stale closed-issue authority, duplicate historical identifiers, and historical status-label interpretation. Closed labels do not reactivate completed CLS work.
- The CLS9 semantic checker and fixture data are test-local, synthetic, and non-authoritative. They must not become runtime routing code or a production packet schema.
- Live source-resolution enforcement is not implemented by #455. Any future runtime work requires a new focused issue that identifies one existing canonical resolver to extend.

## Ownership And Destinations

- **GitHub Service Agent:** approved repository implementation and pull-request execution.
- **Integration Manager:** cross-system routing and any future Notion handoff.
- **Instructional-design agents:** content review within registered roles.
- **Notion:** teacher planning and approved working knowledge.
- **Google Drive:** approved student-facing materials.

## Stop Conditions

Stop and return `needs-decision` when evidence is unavailable or contradictory; a new Notion field or write is required without a confirmed target and owner; language, material-safety, assessment, readiness, or authorization decisions would be conflated; a new agent, parallel hierarchy, duplicate standard, runtime router, or source resolver is proposed without a focused issue; student-facing artifacts would be stored in GitHub without explicit approval; or any external, production, sharing, permission, or source-of-truth write enters scope.

## Future Work

New work must use the next unused identifier, one objective, an exact allowlist, independent validation, and separate authorization. Write-capable or student-facing work also requires an approved destination and rollback plan.

## Version

0.2.0
