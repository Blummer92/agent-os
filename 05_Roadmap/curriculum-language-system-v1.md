# Curriculum Language System v1 Roadmap

## Purpose

Define one governed sequence for unit vocabulary, lesson vocabulary, teacher
language, student language, material language, and assessment language.

This roadmap coordinates repository standards and validation. It does not store
live unit or lesson vocabulary and does not authorize classroom-artifact creation.

## Current Findings

- Vocabulary is a cross-unit and cross-lesson system, not a standalone lesson feature.
- Existing language standards distinguish teacher-facing and student-facing language,
  but they do not yet consume one unit-to-lesson vocabulary map.
- Notion may contain complete, partial, or inferred vocabulary evidence; it must be
  read before new vocabulary fields or values are proposed.
- Generated Slides, Docs, and worksheets must use approved Google Drive destinations.

## Architecture

1. **Unit Vocabulary Map** classifies words across the unit lifecycle.
2. **Notion source audit** identifies where real unit and lesson vocabulary lives.
3. **Lesson Vocabulary Planner** selects words for today's teaching and assessment.
4. **Language integration** connects vocabulary decisions to teacher talk, student
   language, slides, worksheets, and assessment prompts.
5. **Notion handoff** proposes data-field changes only when the read-only audit proves
   a gap.
6. **Validation** checks standards, references, categories, and prohibited hierarchy.

## Issue Sequence

| Order | Issue | Deliverable | Dependency state |
|---|---|---|---|
| 1 | #127 — CLS1 | This roadmap | none |
| 2 | #128 — CLS2 | Unit Vocabulary Map standard | CLS1 context |
| 3 | #129 — CLS3 | Read-only Notion vocabulary source audit | CLS1 and CLS2 |
| 4 | #130 — CLS4 | Lesson Vocabulary Planner response standard | CLS1–CLS3 |
| 5 | #131 — CLS5 | Student/teacher/material language integration | CLS2 and CLS4 |
| 6 | #132 — CLS6 | Governed Notion-field handoff recommendation | CLS3 and CLS4 |
| 7 | #133 — CLS7 | Structural validation and automation readiness | CLS2, CLS4, CLS5 |

CLS2 must precede CLS4. CLS3 must read Notion before CLS4 or CLS6 invents fields,
values, or vocabulary.

## Ownership And Source Of Truth

- **GitHub:** standards, overlays, tests, automation-readable rules, and this roadmap.
- **Notion:** actual unit vocabulary, lesson vocabulary, teacher planning, and source
  audit evidence.
- **Google Drive:** approved student-facing Slides, Docs, worksheets, and portfolios.
- **Integration Manager:** cross-system routing and any future Notion handoff.
- **GitHub Service Agent:** approved repository implementation.
- **Instructional-design agents:** content review within existing registered roles.

No new vocabulary agent or parallel curriculum overlay hierarchy is created.

## Stop Conditions

Stop and return `needs-decision` when:

- Notion evidence is unavailable, incomplete, or contradictory;
- a new Notion field or schema write is required;
- teacher language and student-facing language cannot be separated;
- vocabulary would be assessed before it is taught or practiced;
- a new agent, new curriculum overlay tree, or duplicate shared standard is proposed;
- student-facing artifacts would be stored in GitHub without explicit approval;
- any external, production, sharing, or permission write enters scope.

## Future Expansion

After CLS7 passes, later work may add read-only planners, approved classroom-artifact
workflows, and bounded source synchronization. Each write-capable or student-facing
step requires its own issue, destination, authorization, validation, and rollback.

## Version

0.1.0
