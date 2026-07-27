# Unit Vocabulary Map Standard

## Purpose

Classify unit vocabulary before lesson planning so agents reuse prior learning,
separate instruction from exposure, and never assess language prematurely.
This standard defines structure and decision rules, not vocabulary values.

## Source and Evidence Rules

1. Read the approved unit source in Notion or another authorized source before
   populating a word.
2. Label each populated word as `explicit`, `partial`, or `inferred` evidence.
3. Never promote inferred or missing vocabulary to approved source data.
4. When evidence is unavailable or conflicting, return `needs-decision` and name
   the missing source, property, or owner.
5. Do not write to Notion, Drive, or a classroom artifact through this standard.

## Source Identity-State Contract

This contract governs CLS2 unit-language discovery only. It separates source
identity from vocabulary evidence and never authorizes canonical onboarding.

| Evidence state | CLS2 discovery outcome | Stop and write boundary |
|---|---|---|
| Current canonical match | Proceed as `canonical-confirmed` under the current canonical source. | No automatic write. |
| No canonical record plus one unique authorized working source | Proceed as `working-source-confirmed`; the result is visibly provisional and CLS2-only. | No automatic onboarding, registry mutation, or external write. |
| Canonical lookup unavailable | Return `needs-decision`; make no provisional vocabulary decision. | Stop until lookup evidence is available. |
| Canonical lookup unverifiable | Return `needs-decision`; make no provisional vocabulary decision. | Stop until lookup evidence is verifiable. |
| Multiple plausible sources | Block for source-owner resolution. | No write. |
| Canonical/working-source conflict | Block and route to the canonical owner. | No write. |
| Stale canonical pointer | Block until the canonical owner refreshes it. | No write. |
| One governed alias resolves uniquely | Apply the resolved canonical or working-source rule. | No automatic write. |
| Alias collision | Block for identity resolution. | No write. |
| Unresolved alias | Block for identity resolution. | No write. |

A missing canonical registry record is not the same state as a canonical lookup
that is unavailable or unverifiable. Never infer one from the other.

## Provisional Working-Source Evidence

Every `working-source-confirmed` result must preserve:

- source identity;
- exact page, property, heading, table, or section;
- the relevant source section;
- freshness evidence;
- provisional status and the reason the source is uniquely usable;
- `execution_authorized: false`;
- an explicit statement that the result authorizes no readiness, assessment,
  publication, canonical onboarding, registry mutation, or external write.

`working-source-confirmed` may support provisional CLS2 discovery only. It is not
approved canonical evidence for CLS4 lesson-language planning. This contract does
not implement a live resolver, connector-backed identity resolution, or runtime
source-resolution behavior.

## Required Categories

| Category | Use |
|---|---|
| Review Vocabulary | Previously taught language that needs retrieval or reinforcement. |
| Teach Vocabulary | Language explicitly taught and practiced in this unit. |
| Introduce, Don’t Assess Yet | Language students may encounter but are not yet expected to master. |
| Transfer Vocabulary | Prior language applied in a new context or medium. |
| Future Vocabulary | Language reserved for a later unit or sequence. |

A word has exactly one primary category for the current unit. Record another
unit connection in `Prior Unit Connection`; do not duplicate the row.

## Required Table

| Word | Category | Unit | Prior Unit Connection | Student-Friendly Meaning | Teacher Language Use | Student Language Use | Slide/Worksheet Safe? | Assess This Unit? | Notes |
|---|---|---|---|---|---|---|---|---|---|

## Field Rules

- `Word`: source-backed term; never silently invented.
- `Category`: one required category from this standard.
- `Unit`: current approved unit identifier or title.
- `Prior Unit Connection`: prior source or `None documented`.
- `Student-Friendly Meaning`: concise meaning supported by the source or marked
  `Needs source confirmation`.
- `Teacher Language Use`: accurate teacher-talk guidance.
- `Student Language Use`: language students are expected to understand or use.
- `Slide/Worksheet Safe?`: `Yes`, `No`, or `Needs review`.
- `Assess This Unit?`: `Yes` only after explicit instruction or practice;
  otherwise `No` or `Not yet`.
- `Notes`: evidence class, source location, ambiguity, and owner handoff.

## Decision Order

1. Classify source identity using the Source Identity-State Contract.
2. Confirm the unit and permitted source for the resulting identity state.
3. Reuse an existing map when the source and unit are unchanged.
4. Check prior-unit connections before assigning `Teach Vocabulary`.
5. Assign one primary category.
6. Separate teacher language from student language.
7. Decide material safety independently from assessment eligibility.
8. Block assessment when instruction or practice evidence is missing.
9. Record unresolved evidence and route it to the source owner.

## Overlay Responsibilities

- Unit Alignment Agent verifies unit connection, category, evidence status, and
  source identity state.
- Teacher Modeling Coach converts approved entries into teacher and student
  language without changing the source vocabulary decision.
- Instructional Materials Coach uses only entries marked material-safe and does
  not store student-facing artifacts in GitHub.

## Prohibited Expansion

Do not create a curriculum overlay folder, vocabulary-specific agent, Lesson
Vocabulary Planner, Notion schema, canonical registry record, live resolver, or
classroom artifact under this standard.

## Version

0.2.0
