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

1. Confirm the unit and approved source.
2. Reuse an existing map when the source and unit are unchanged.
3. Check prior-unit connections before assigning `Teach Vocabulary`.
4. Assign one primary category.
5. Separate teacher language from student language.
6. Decide material safety independently from assessment eligibility.
7. Block assessment when instruction or practice evidence is missing.
8. Record unresolved evidence and route it to the source owner.

## Overlay Responsibilities

- Unit Alignment Agent verifies unit connection, category, and evidence status.
- Teacher Modeling Coach converts approved entries into teacher and student
  language without changing the source vocabulary decision.
- Instructional Materials Coach uses only entries marked material-safe and does
  not store student-facing artifacts in GitHub.

## Prohibited Expansion

Do not create a curriculum overlay folder, vocabulary-specific agent, Lesson
Vocabulary Planner, Notion schema, or classroom artifact under this standard.

## Version

0.1.0