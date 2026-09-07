# Artifact-First Response Standard

Governs response ordering for classroom-material requests so backend routing
and governance reporting never displace the requested classroom artifact.
Applies to any agent that responds directly to a teacher about an assessment,
rubric, worksheet, slide concept, or other classroom-facing output. Does not
change ownership, source-of-truth, production-gate, or write-authorization
rules defined elsewhere.

## Problem

Valid routing, readiness, and governance work can still produce the wrong
teacher-facing experience if a backend handoff or authorization record is
shown before the requested classroom artifact, making the system feel
procedural and suggesting the request was not understood.

## Required Order

1. Run required source checks, ownership resolution, gate checks, and
   handoffs without making those records the primary visible output.
2. Lead the response with the requested artifact, or a clearly labeled
   preview or content specification of it.
3. Place governance status, blockers, files changed, tests run, docs
   updated, handoff recommendations, and remaining risks after the artifact.
4. Never describe a routing record, Notion handoff, readiness report, or
   authorization request as though it were the requested classroom artifact.

## Requested Format Is Part Of The Artifact

When the teacher explicitly requests an artifact format such as PDF, DOCX, or
PPTX, successful delivery requires an artifact in that requested format. A
prose description, outline, page-by-page specification, or chat-only rendering
does not satisfy the request merely because it contains the intended content.

Before claiming completion:

- produce the requested file when production is authorized;
- run the format's required render/verification path before delivery;
- return a usable artifact reference or file link through the active delivery
  surface; and
- if any of those steps cannot be completed, use Blocked-Production Behavior
  and label the result as a preview or content specification rather than a
  completed artifact.

A response must never report an explicitly requested PDF as complete when no
PDF artifact was actually produced and made available to the teacher.

## Blocked-Production Behavior

When production is blocked, show a clearly labeled preview or content
specification instead of the final artifact when doing so is safe and does
not violate source, ownership, or production-gate boundaries (see
`production-gates-and-compute.md`). State explicitly that the preview is not
yet an authorized student-facing file.

## Distinguish Three Categories

- Classroom artifact or preview -- the thing the teacher asked for.
- Backend handoff or routing record -- Notion, Drive, or GitHub routing
  evidence.
- Production authorization status -- whether generation is authorized.

Never collapse these into one undifferentiated response.

## Exceptions

- A request that specifically asks for a routing or governance report keeps
  that report as the primary output.
- An unsafe or unclear request still stops without inventing content or
  bypassing authorization; the stop condition itself is the primary output.

## Required Final Report

Unchanged: still include files changed, tests run, docs updated, blockers,
and handoff recommendations per `_common-overlay-rules.md`, positioned after
the artifact per the Required Order above.

## Version

0.1.1
