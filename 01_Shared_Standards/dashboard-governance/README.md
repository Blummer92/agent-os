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

## Canonical readiness vocabulary

| Term | Owner | Boundary |
|---|---|---|
| Unit Generation Approval | Unit Alignment & Readiness | Not packet readiness or production authorization. |
| Modeling Handoff Ready | Teacher Modeling Coach | Not slide approval, worksheet approval, or production authorization. |
| Evidence Handoff Ready | Assessment Agent / Student Evidence Coach | Not worksheet approval or production authorization. |
| Assessment Handoff Ready | Assessment Agent / Student Evidence Coach | Not packet approval or production authorization. |
| Source-Control Gate | Curriculum Source Control | Not production authorization. |
| Packet Generation Gate | Daily Generation Packet | Not Unit Generation Approval or Production Authorized. |
| Packet Slide Readiness | Daily Generation Packet | Not slide production approval. |
| Packet Worksheet Readiness | Daily Generation Packet | Not worksheet production approval. |
| Packet Assessment Readiness | Daily Generation Packet | Not assessment production approval. |
| Production Authorized | Production Control | Final production authorization. |

## Historical alias policy

Historical labels remain discoverable. Treat them as aliases until a governed
migration renames fields or options after dependency checks.

| Historical term | Governance v1.0 interpretation |
|---|---|
| Ready for slides | Modeling Handoff Ready only, unless explicitly owned by Daily Generation Packet as packet/day slide readiness. |
| Ready for worksheet agent | Evidence Handoff Ready only. |
| Ready for assessment agent | Assessment Handoff Ready only. |
| Generation Gate | Must be qualified by owner. |
| Production Ready | Production Authorized only when owned by Production Control. |
| Generation Readiness | Unit Generation Approval or Packet Generation Gate depending owner. |
| Worksheet Agent Ready Check | Worksheet Source Packet Ready Check when used in Source Control. |
| Source-Control Production Readiness | Source-Control Routing Readiness, not final production authorization. |

Do not infer ownership from legacy wording.

## Standard dashboard structure

Each governance dashboard should document these sections:

1. Dashboard Mission
2. Owns
3. Consumes
4. Hands Off To
5. Governance Rules
6. Boundaries
7. Common Routing Mistakes
8. Production Relationship
9. References

### Dashboard Mission

One sentence stating the dashboard's canonical role.

### Owns

List only the decisions, fields, summaries, or readiness states for which this
dashboard is the canonical owner.

### Consumes

List upstream summaries used by this dashboard and identify the owner of each
summary.

### Hands Off To

List downstream dashboards or production agents that consume this dashboard's
summary.

### Governance Rules

State what this dashboard may decide and what it must not decide.

### Boundaries

Clarify common false approvals. For example, Modeling Handoff Ready is not slide
approval, and Packet Generation Gate is not Production Authorized.

### Common Routing Mistakes

Document frequent incorrect interpretations and the correct owner or route.

### Production Relationship

State how the dashboard relates to Production Control and whether it can or
cannot authorize generation.

### References

Link to the Governance v1.0 baseline, ownership map, relevant source dashboards,
and downstream consumers.

## Production safety standard

Production must pause if any required upstream owner summary is missing,
blocked, contradictory, unclear, or assigned to the wrong owner.

Production Control must return Production Authorized before any generation agent
creates classroom materials.

## Implementation notes

Documentation aliases and routing references may be added without schema changes.
Field, option, formula, rollup, relation, view, or automation changes require a
dependency check and explicit approval.
