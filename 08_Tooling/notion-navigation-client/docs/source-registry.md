# Source Registry

Durable guidance for recurring Notion reviews. This registry helps agents choose the highest-authority surface when reviewing Digital Media work. It is a navigation reference only; verify live Notion before readiness, status, ownership, curriculum, or governed-field decisions.

## Source fields

For each source, track: name, type, governed decisions, authority level, direct link, owner when known, boundaries, and related surfaces.

## Seeded Digital Media source registry

| Source | Type | Governs | Authority level | Owner | Direct link |
|---|---|---|---|---|---|
| Digital Media Source Control Dashboard | Page / operational dashboard | Source authority, generation gates, current approved materials, duplicate/conflict watchlists, source-packet readiness. | Source of truth for source authority and production gating. | Source Control | https://app.notion.com/p/3717ac78313181428d5fdcf2efdda180 |
| Unit Readiness Workspace | Page / owner workspace | Final unit generation approval, unit readiness, generation readiness, slide readiness, worksheet readiness, blockers. | Source of truth for unit readiness and final unit generation approval. | Unit Alignment | https://app.notion.com/p/3717ac783131816b840cf2bf4e049555 |
| Modeling Coach Workspace | Page / owner workspace | Teacher modeling actions, modeling readiness, modeling source evidence, natural-language modeling updates. | Source of truth for modeling readiness. | Teacher Modeling Coach | https://app.notion.com/p/3717ac78313181fca7abfdaf557d8583 |
| Evidence Coach Workspace | Page / owner workspace | Student evidence readiness, assessments, rubrics, reflection pages, student work templates, evidence gaps. | Source of truth for student evidence readiness. | Student Evidence Coach | https://app.notion.com/p/3717ac78313181c481fcc34d102076a4 |
| Generation Packet Workspace | Page / owner workspace | Packet-level slide, worksheet, and assessment readiness; daily production sequencing. | Source of truth for packet readiness decisions. | Daily Generation Packet | https://app.notion.com/p/3717ac78313181a8b04feda295f88341 |
| Digital Media Curriculum Command Center | Page / human-facing command center | Blocked-work summaries, routing, caution surfaces, governance follow-up visibility. | Derived dashboard. | Unknown | https://app.notion.com/p/3867ac78313181e5a4cadadc4c0b3420 |
| Digital Media Curriculum Command Center - Human Action View | Page / human action view | First-screen human review flow for decision, blocker, owner route, caution, governance review. | Derived dashboard. | Unknown | https://app.notion.com/p/3867ac78313181f88428f642c14ebaef |
| Digital Media Source Review Dashboard | Page / routing dashboard | Source-review triage and routing workflow. | Supporting source. | Unknown | https://app.notion.com/p/3747ac783131817e9a01f32f343c1852 |
| Digital Media Source Review Records | Database | Source-review routing, owner/next-action tracking, blocked or returned handoffs, ready-for-handoff state. | Supporting source. | Unknown | https://app.notion.com/p/5bba31a956d2476cb0e3b6b8337d128f |
| Canonical Digital Media Unit Registry | Database | Canonical unit identity, alias mapping, canonical status, course placement, unit source-of-truth pointer. | Source of truth for canonical unit naming and registry identity. | Unknown | https://app.notion.com/p/f7f22d33e1ef4932b294cbe39b24a39a |

## Boundaries

- Source Control decisions may be summarized elsewhere, but other dashboards should not overwrite source-authority decisions.
- Unit, modeling, evidence, and packet owner workspaces own their readiness decisions; summary dashboards should display or route from those decisions without redefining them.
- The Curriculum Command Center and Human Action View are summary/routing surfaces, not owners of source authority, generation approval, modeling readiness, evidence readiness, packet readiness, handoff status, or change history.
- Source Review Dashboard and Source Review Records route source-review work; they should preserve existing records, production boundaries, and governance ownership without changing source authority or curriculum decisions.
- Canonical unit naming, aliases, and status come from the Canonical Digital Media Unit Registry when conflicts appear.
- Blocked, production-pause, do-not-generate, or missing-evidence records must not move to student-facing production.

## Priority rule

When surfaces disagree, prefer the highest-authority source and record the conflict briefly.

1. Canonical Digital Media Unit Registry for canonical unit naming and identity.
2. Digital Media Source Control Dashboard for source authority and production gating.
3. Unit Readiness Workspace for final unit generation approval and unit readiness.
4. Modeling Coach Workspace for modeling readiness.
5. Evidence Coach Workspace for evidence readiness.
6. Generation Packet Workspace for packet readiness and next production move.
7. Digital Media Source Review Records and Dashboard for routing and handoff state.
8. Digital Media Curriculum Command Center and Human Action View as summary-only routing surfaces.

## Do not record

- Temporary one-off findings.
- Copied database records.
- Speculative ownership claims presented as fact.
