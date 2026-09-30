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

## Requested Artifact Role Is Authoritative

Resolve the teacher's requested artifact role before candidate selection and
preserve that role through retrieval, rendering, and final response. A request
for a student worksheet or worksheet preview must not silently resolve to a
teacher-modeling package, tutorial/modeling material, generated illustration,
composite image, game/activity board, or another artifact category merely
because it shares the same unit name or appears visually related.

Words such as `look like` or `with images` describe preview or visual-support
intent; they do not independently change a worksheet request into image
generation. Candidate title similarity also does not override the resolved
artifact role.

Before presenting a retrieved or generated candidate, verify that its artifact
role matches the resolved request. If no matching candidate can be retrieved or
produced under current source and authorization rules, use Blocked-Production
Behavior and return a worksheet-specific blocker or clearly labeled worksheet
preview/content specification rather than substituting another artifact role.

This role check is downstream of the existing source-order contract in
`instructional-materials-sources.md`; it does not replace or duplicate the
Notion-first / Drive-second retrieval rule and grants no external-write
authority.

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

## Required Visual Components

When the requested classroom artifact explicitly requires, or its approved
content specification declares, images, icons, diagrams, or other visual
support, those visual slots are part of completion rather than optional polish.
Before final delivery, the producing path must verify that every required
visual slot is either populated by an approved visual path or explicitly
reported as blocked.

When governed context says reusable visuals already exist, the producing path
must run reuse-first resolution before any synthetic fallback. Check usable
authorized conversation/project files and supplied export material first when
they can preserve the governed asset identity, then use the current connected
Visual Asset Library route when available. Do not skip those sources merely
because a renderer can create a plausible substitute more quickly.

Asset metadata is not artifact fulfillment. An asset ID, eligible-asset ID,
selection decision, or successful metadata read does not prove that image bytes
or another usable source reference were recovered, materialized, embedded, or
placed. Completion evidence must distinguish discovery, selection,
materialization, and placement, and the final artifact must satisfy the last
state required by its format.

If governed evidence identifies an eligible reusable asset but the producing
surface cannot recover/materialize that exact asset, report the artifact as
incomplete/preview with an unresolved visual-assets blocker. Do not convert the
recovery failure into permission to omit the visual, draw a placeholder, invent
a lookalike, or silently generate a replacement. Synthetic fallback is eligible
only when governed discovery proves no eligible reusable asset is available and
current generation policy independently permits creation.

If a connected visual-asset source such as Visual Asset Sync is unavailable or
not authorized, do not interpret that absence as permission to silently remove
required visuals. Use an approved non-connected/generated/local fallback when
current policy permits it and the reuse-first rules above admit that fallback.
If no approved fallback is available, label the artifact as incomplete/preview,
identify the visual-assets blocker, and do not claim classroom-ready completion.

Render QA for a visually required artifact must verify both layout integrity
and presence of the required visual components. A file whose required visual
slots resolve to zero images/icons cannot receive a complete/classroom-ready
claim. A placeholder box, generated stand-in, or metadata-only asset reference
cannot satisfy that check when the required role is bound to an existing
governed reusable asset.

## Required Visual Placement And Companion-File Boundary

When worksheet content references a required visual asset — for example, a
worksheet that tells students they will receive or must analyze a specific
intentionally designed visual — that reference binds an explicit required
visual role before artifact generation. Name the role, its instructional
purpose, and its intended placement alongside the analysis prompts it
supports.

Resolve the bound asset through the current Notion Visual Asset Library
working record and the exact Drive file identity. Do not infer a different
file, substitute a nearby asset, or treat folder co-location as identity.

A required visual that exists only as a separate file in the same Drive folder
proves discovery at most. Discovery, selection, or folder co-location cannot
be reported as visual fulfillment. When the current lesson requires inline
analysis, the required visual slot is satisfied only by the asset bytes or a
usable source reference materialized and placed in the worksheet at the
instructional point where students need it. The separate companion file
remains a candidate for companion-file placement only when the current plan
explicitly requires a separate companion file; it never silently converts an
inline-analysis slot into a satisfied visual.

Never silently deliver a text-only artifact for a visually required worksheet.
When required visual placement is missing — including when the only evidence
is an unplaced companion file in the same folder — surface the gap as an
explicit blocker, label the artifact as incomplete/preview, and use
Blocked-Production Behavior. Asset discovery/selection cannot be reported as
visual fulfillment without materialization and placement.

Render QA for a visually required worksheet must verify required visual
presence, readable scale, no clipping, and usable proximity to the analysis
prompts the visual supports, in addition to layout integrity. The worksheet
layout must preserve intentional hierarchy, section grouping, adequate
response space, and visual scaffolding rather than collapsing into raw
headings, text, and response lines.

Final-delivery QA fails the classroom-ready claim when required visuals are
absent or unplaced.

This section creates no external-write authority. It does not authorize
Drive, Notion, publication, or other external writes, and it does not change
classroom artifact destinations or ownership boundaries.

## Generated Asset Delivery Continuation

A successful generated classroom visual is intermediate evidence when the active
teacher mission already includes a current, exact, explicitly approved Drive
destination and the external write remains authorized. Do not stop at image
creation merely to ask the teacher to request the already-authorized handoff
again.

After the teacher accepts the generated visual, or the active mission otherwise
contains the required explicit human acceptance, continue the same bounded
mission through the existing governed visual-asset ingestion path:

1. preserve the generated image as the exact returned asset for the active
   generation/intake lineage;
2. use only the already-grounded exact approved Drive folder ID; never infer a
   destination from a folder name, search for a replacement, or create a folder;
3. execute the separately authorized Drive write through the existing visual
   asset writer/coordinator boundary;
4. require exact Drive file and parent-folder readback before treating the upload
   as persisted;
5. continue through the already-authorized metadata/registry handoff when that
   handoff is part of the active mission; and
6. verify the written metadata against the exact Drive identity before reporting
   the handoff complete.

This continuation never creates external-write authority. If the exact Drive
destination, current destination evidence, human confirmation, or external-write
authorization is absent or stale, fail closed before upload and report the
specific blocker. A successful generation must never manufacture a new folder,
choose a nearby destination, change sharing, or treat metadata registration as
student-facing approval.


## Source Retrieval Delivery Continuation

A successful project/source retrieval is intermediate evidence when the active
teacher mission already requests a classroom artifact and that artifact has not
yet been produced. Do not stop at retrieval merely to report that relevant
Photography Foundations (or other unit) source material was found, that a
production skill was loaded, or that the evidence is sufficient. Loading a
DOCX-generation skill or summarizing retrieved composition concepts is not
worksheet delivery.

After retrieving the needed source evidence in the same mission, continue
immediately into worksheet generation:

1. treat the retrieved source context as input to production, not as the
   response's terminal deliverable;
2. consume the retrieved project materials and composition vocabulary directly,
   without requiring the teacher to restate what the project already contains;
3. produce the usable student-facing worksheet artifact, or complete
   artifact-ready student-facing content, before backend status or governance
   reporting per the Required Order above;
4. when no explicit Drive destination is supplied and no authorized production
   write is available, finish with a bounded local/chat artifact -- complete
   student-facing worksheet content or a clearly labeled content specification --
   rather than stopping after retrieval.

Do not ask an unnecessary clarifying question when the supplied project
materials are sufficient for a bounded worksheet. Ask only when source
uncertainty makes a bounded draft unsafe, and then use Blocked-Production
Behavior instead of fabricating curriculum facts.

This continuation never creates external-write authority. It does not change
classroom artifact destinations, does not authorize Drive, Notion, publication,
or other external writes, and does not weaken source-grounding requirements.
A missing Drive destination never authorizes writing the lesson artifact to
GitHub.

## Content-First Visual Planning For Worksheets

When a teacher explicitly requests student-facing content first and visual selection second, preserve that sequence. Establish the bounded worksheet content or clearly labeled content specification before selecting visuals. A missing lesson-day detail does not by itself erase the requested deliverable when a safe bounded draft can be produced; mark unsupported lesson specifics as proposed / needs confirmation rather than silently inventing them.

After the content exists, evaluate visuals against the actual student tasks and learning targets. For each worksheet section, record whether a visual is needed, optional, or unnecessary; the proposed or reusable asset; its instructional purpose; curriculum/learning-target alignment; source/evidence status; and create/reuse disposition. Decorative availability alone is not instructional justification. If source uncertainty makes a bounded draft unsafe, use the existing blocked-production/source rules instead of fabricating curriculum facts.

This sequencing does not change classroom artifact destinations or authorize Drive, Notion, publication, or other external writes.

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

0.1.7
