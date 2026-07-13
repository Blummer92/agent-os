# Agent OS Governance v1.0 Baseline

Date: 2026-07-13

## Status

Agent OS Governance v1.0 is the canonical governance baseline for curriculum
production routing, dashboard ownership, readiness vocabulary, and production
authorization.

GitHub is the source of truth for this baseline. Notion remains the operational
workspace where dashboard records, readiness summaries, and implementation notes
may be maintained.

This baseline does not add classroom artifacts, student-facing materials, lesson
content, slides, worksheets, assessments, or Google Drive artifacts to GitHub.

## Ownership model

Every curriculum decision has exactly one canonical owner. Other dashboards may
summarize, reference, filter, display, or route from an owner decision, but they
must not overwrite the owning dashboard's decision.

| Canonical owner | Owns |
|---|---|
| Unit Alignment & Readiness | Unit definition, unit purpose, unit placement, learning progression, course sequencing, throughline alignment, transfer skills, and Unit Generation Approval. |
| Teacher Modeling Coach | Teacher demonstrations, think-alouds, worked examples, non-examples, critique modeling, revision modeling, bridge modeling, transfer modeling, teacher-facing instructional language, and Modeling Handoff Ready. |
| Assessment Agent / Student Evidence Coach | Student evidence, success criteria, rubrics, assessments, reflection prompts, portfolio evidence, assessment implications, Evidence Handoff Ready, and Assessment Handoff Ready. |
| Curriculum Source Control | Source authority, source confidence, source evidence, safe use, provenance, licensing, prompt tracking, image identity, approved reusable assets, do-not-invent boundaries, and Source-Control Gate. |
| Daily Generation Packet | Packet Generation Gate, packet/day-level slide readiness, worksheet readiness, assessment readiness, current blockers, smallest next action, and daily production routing. |
| Instructional Materials Coach | Student-facing material quality, slide quality, worksheet quality, visual hierarchy, accessibility, cognitive load for student-facing materials, layout, clarity, graphic consistency, and material usability. |
| Production Control | Production Authorized, final production authorization, blocked production reason, final go/no-go routing, and production safety enforcement. |
| Dashboard Admin & Change Log | Dashboard architecture, duplicate cleanup, governance change history, dashboard maintenance, and implementation tracking. |

Assessment Agent and Student Evidence Coach are the same canonical owner for
student evidence and assessment readiness. They are not separate owners.

Instructional Materials Coach owns material quality only. It does not authorize
production.

Production Control is the only owner of Production Authorized.

## Official production pipeline

The official governance workflow is:

1. Unit Alignment & Readiness
2. Teacher Modeling Coach
3. Assessment Agent / Student Evidence Coach
4. Curriculum Source Control
5. Daily Generation Packet
6. Instructional Materials Coach
7. Production Control
8. Generate Materials

Generation may occur only when Production Control returns Production Authorized.

## Canonical readiness vocabulary

Approved readiness and handoff terms are:

| Term | Owner | Meaning |
|---|---|---|
| Unit Generation Approval | Unit Alignment & Readiness | Unit-level generation approval. This is not packet readiness or production authorization. |
| Modeling Handoff Ready | Teacher Modeling Coach | Teacher-facing modeling is ready for downstream owners to consume. This is not slide approval. |
| Evidence Handoff Ready | Assessment Agent / Student Evidence Coach | Evidence requirements are ready for downstream owners to consume. This is not worksheet approval. |
| Assessment Handoff Ready | Assessment Agent / Student Evidence Coach | Assessment requirements are ready for downstream owners to consume. This is not production approval. |
| Source-Control Gate | Curriculum Source Control | Source authority, provenance, safe-use, and asset constraints are clear enough for the stated routing. This is not production authorization. |
| Packet Generation Gate | Daily Generation Packet | Packet/day-level readiness and blockers are summarized. This is not Unit Generation Approval or Production Authorized. |
| Packet Slide Readiness | Daily Generation Packet | Day-level slide readiness context. This is not slide production approval. |
| Packet Worksheet Readiness | Daily Generation Packet | Day-level worksheet readiness context. This is not worksheet production approval. |
| Packet Assessment Readiness | Daily Generation Packet | Day-level assessment readiness context. This is not assessment production approval. |
| Production Authorized | Production Control | Final production authorization. This is the only term that permits generation. |

## Historical alias policy

Historical records remain discoverable and should not be rewritten casually.
Legacy terminology must be interpreted as aliases unless a governed migration
renames the underlying field or option after dependency checks.

| Historical term | Governance v1.0 interpretation |
|---|---|
| Ready for slides | Modeling Handoff Ready only, unless explicitly owned by Daily Generation Packet as packet/day slide readiness. |
| Ready for worksheet agent | Evidence Handoff Ready only. |
| Ready for assessment agent | Assessment Handoff Ready only. |
| Generation Gate | Must be qualified by owner: Unit, Modeling, Evidence, Source-Control, Packet, or Production. |
| Production Ready | Production Authorized only when owned by Production Control. |
| Generation Readiness | Unit Generation Approval or Packet Generation Gate depending on owner. |
| Worksheet Agent Ready Check | Worksheet Source Packet Ready Check when used in Source Control. |
| Source-Control Production Readiness | Source-Control Routing Readiness, not final production authorization. |

Do not infer ownership from legacy wording.

## Standard dashboard structure

Every governance dashboard should document the following sections:

1. Dashboard Mission
2. Owns
3. Consumes
4. Hands Off To
5. Governance Rules
6. Boundaries
7. Common Routing Mistakes
8. Production Relationship
9. References

The dashboard-governance standard owns the detailed structure and vocabulary.
See `01_Shared_Standards/dashboard-governance/README.md`.

## Governance rules

- One curriculum decision has exactly one canonical owner.
- Other dashboards may summarize, reference, filter, display, or route from an
  owner decision, but they must not overwrite it.
- Production Control alone authorizes production.
- Instructional Materials Coach reviews material quality but does not authorize
  production.
- Curriculum Source Control owns source authority and safe-use decisions.
- Teacher Modeling Coach owns teacher-facing modeling decisions.
- Assessment Agent and Student Evidence Coach are the same owner for evidence
  and assessment readiness.
- Daily Generation Packet owns packet/day-level readiness, not unit approval.
- Unit Alignment owns stable unit definition and Unit Generation Approval, not
  packet/day production details.
- Historical records remain discoverable.
- Schema changes require dependency review before implementation.

## Production safety rules

Production must pause when any of these are true:

- Source-Control Gate is blocked or unclear.
- Unit Generation Approval is not cleared.
- Modeling Handoff Ready is missing when modeling is required.
- Evidence Handoff Ready or Assessment Handoff Ready is missing when evidence or
  assessment is required.
- Packet Generation Gate is blocked.
- Instructional Materials Coach has unresolved student-facing material risks.
- Production Control has not returned Production Authorized.
- A dashboard tries to own a decision assigned to another owner.

## Notion operational implementation

Notion Sprint 1 implemented operational documentation for this baseline by
adding governance alias notes, Instructional Materials Coach routing links,
Production Control standardization, Daily Generation Packet standardization,
Teacher Modeling Coach standardization, and Assessment Agent / Student Evidence
Coach standardization.

Those Notion pages are operational surfaces. This GitHub baseline is the
canonical source of truth.

## Change policy

Future governance changes must:

1. Reference Agent OS Governance v1.0 as the baseline.
2. State why the baseline needs to change.
3. Identify affected dashboards and owners.
4. Separate governance decisions from implementation changes.
5. Preserve backward compatibility whenever practical.
6. Keep historical records discoverable.
7. Use aliases before schema renames.
8. Avoid database property renames without dependency checks.
9. Record applied changes in the changelog.
10. Keep Production Control as the only production authorization owner unless a
    governed baseline change explicitly changes that owner.

## Current validation status

Production Cycles was used as the first governance pilot unit.

- Certification status: Certified with Conditions.
- Certification score: 85 / 100.
- Production status: not production-ready.
- Production decision: Production Authorized: No.

Production Cycles is the benchmark governance pilot unit, not a classroom
production-ready unit.

## Version

Agent OS Governance v1.0 -- 2026-07-13
