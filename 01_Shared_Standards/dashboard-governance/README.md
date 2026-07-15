# Dashboard Governance Standards

## Purpose

Dashboard governance standards define how Agent OS curriculum dashboards assign
ownership, consume upstream decisions, hand off downstream work, and prevent
premature classroom-material production.

## Version

1.0.0

## Source of truth

This standard implements `Agent OS Governance v1.0`.

Canonical baseline:

- `00_Governance/agent-os-governance-v1-baseline.md`

## Core rule

Separate owner dashboards from consumer dashboards.

Owner dashboards make the canonical decision assigned to them. Consumer
dashboards may display, summarize, reference, filter, route, or consume that
decision, but they must not overwrite it.

## Canonical dashboard owners

| Canonical owner | Owns |
|---|---|
| Unit Alignment & Readiness | Unit definition, placement, learning progression, course sequencing, throughline alignment, transfer skills, and Unit Generation Approval. |
| Teacher Modeling Coach | Teacher demonstrations, think-alouds, worked examples, non-examples, critique modeling, revision modeling, bridge modeling, transfer modeling, Modeling Handoff Ready, and teacher-facing instructional language. |
| Assessment Agent / Student Evidence Coach | Student evidence, success criteria, rubrics, assessments, reflection prompts, portfolio evidence, Evidence Handoff Ready, Assessment Handoff Ready, and assessment implications. |
| Curriculum Source Control | Source authority, source confidence, source evidence, safe-use, provenance, licensing, prompt tracking, image identity, approved reusable assets, do-not-invent boundaries, and Source-Control Gate. |
| Daily Generation Packet | Packet Generation Gate, packet/day-level slide readiness, worksheet readiness, assessment readiness, current blockers, smallest next action, and daily production routing. |
| Instructional Materials Coach | Student-facing material quality, slide quality, worksheet quality, visual hierarchy, accessibility, cognitive load, layout, clarity, graphic consistency, and material usability. |
| Production Control | Production Authorized, final production authorization, blocked production reason, final go/no-go routing, and production safety enforcement. |
| Dashboard Admin & Change Log | Dashboard architecture, duplicate cleanup, governance change history, dashboard maintenance, and implementation tracking. |

Assessment Agent and Student Evidence Coach are the same owner.

Instructional Materials Coach owns material quality only, not production
authorization.

Production Control is the only owner of Production Authorized.

## Official production pipeline

1. Unit Alignment & Readiness
2. Teacher Modeling Coach
3. Assessment Agent / Student Evidence Coach
4. Curriculum Source Control
5. Daily Generation Packet
6. Instructional Materials Coach
7. Production Control
8. Generate Materials

Generation may occur only after Production Control returns Production Authorized.

## Readiness Vocabulary And Aliases

See `readiness-vocabulary-and-aliases.md` in this directory for the canonical
readiness vocabulary table and the historical alias policy.

## Standard dashboard structure

See `standard-dashboard-structure.md` in this directory for the required
section list and per-section guidance.

## Production safety standard

Production must pause if any required upstream owner summary is missing,
blocked, contradictory, unclear, or assigned to the wrong owner.

Production Control must return Production Authorized before any generation agent
creates classroom materials.

## Implementation notes

Documentation aliases and routing references may be added without schema changes.
Field, option, formula, rollup, relation, view, or automation changes require a
dependency check and explicit approval.
