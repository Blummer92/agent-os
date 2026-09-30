# Instructional Materials Workflows
## Purpose
Use the narrowest workflow that helps the teacher immediately.
## Workflow Modes
| Mode | Use When |
|---|---|
| Triage | Request is broad, mixed, or under-specified. |
| Audit | Existing material needs review or high-impact fixes. |
| Revision | Existing material should be rewritten directly. |
| Builder | New worksheet, guided notes, handout, reading support, checklist, or exit ticket is needed. |
| Slide Builder | Main deliverable is a deck, sequence, or slide outline. |
| Source Retrieval | Needed source must be found in Drive or Notion first. |
| Polish | A real draft exists and final polish is requested. |
## Priorities
Rank tradeoffs in this order unless the user overrides them:
1. teacher usability
2. student clarity
3. pacing and cognitive load
4. production speed
5. accessibility and visual coherence
## Execution Defaults
- Default to direct revision when possible.
- Keep coaching concise unless the user asks for more depth.
- Follow the current request over saved defaults.
- Keep tasks realistic for class-time completion.
- Make next actions obvious for students.
- Simplify before adding more.
## Revision Classification
Before treating a material request as new production, classify it using `production-gates-and-compute.md` as teacher-directed routine revision, structural instructional revision, or new production/release.
A direct teacher request to revise an existing canonical classroom working file may use the Teacher-Directed Revision Lane when every bounded-lane condition passes. The explicit request authorizes the specified artifact edit and does not require `Production Authorized: Yes` merely to revise the existing file.
That authority does not permit a template/master edit, new artifact, new curriculum or assessment decision, unapproved source or asset, governed-field change, sharing/permission or destination change, publication, release, or readiness/approval decision. If any boundary is crossed, use the applicable structural-revision or new-production gate instead.
## Bounded Target Lookup
Resolving the existing worksheet target in Google Drive is bounded end to end (#2745). Exact Drive identity already available from conversation evidence is reused directly; never broad-search again when the identity is known. Title search is scope-limited (bounded title length, worksheet MIME type, `trashed = false`, capped page size and candidates), attempt-capped, and elapsed-budgeted per `src/instructional_workflow_contracts/bounded_drive_lookup.py`. Every lookup terminates in exactly one disposition: resolved (continue the authorized bounded revision automatically), ambiguous (ask only for the smallest necessary target clarification), not found, timed out, or provider error. Each non-resolved disposition surfaces a visible, precise target/access/capability blocker and preserves the requested revision as a resumable handoff; a lookup must never leave the teacher in an indefinite opaque search/Thinking state.
## Vocabulary Integration Gate
Before adding vocabulary to a slide, worksheet, handout, or assessment, inherit the CLS2 and CLS4 decisions. Use only confirmed entries and preserve teacher
language, student language, material safety, and assessment eligibility as
separate fields. Student-facing material requires `Slide/Worksheet Safe? = Yes`.
Assessment language requires explicit instruction or guided or independent
practice; exposure or appearance in material is insufficient.
## Assessment Criteria Integration Gate
For student-facing assessment materials, preserve the validated MaterialRequirement learning-objective, success-criteria, and evidence-target references as dependency identity. Render success criteria, rubrics, checklists, observation criteria, self-check criteria, or completion criteria only from current governed student-facing evidence supplied by the canonical owner; a reference alone is not student-facing copy. Keep teacher scoring notes and calibration guidance separate and do not project them into student materials. Do not invent a rubric for formative work when no governed student-facing criteria are supplied. Inherit `student-language-standard.md` for rubric language and preserve the upstream assessment meaning rather than rewriting it inside material generation.

## Exact Unit/Lesson Provenance Gate

When a teacher asks which sources provide lesson content and visuals for a named unit/lesson/day, resolve the validated `MaterialRequirement` course/unit/lesson identity before source retrieval. Lesson-content evidence and visual-asset evidence are separate source roles and must remain separately attributable.

A source bound to a different unit or lesson may not be presented as authority or as a fallback candidate merely because it is available in conversation/project context. Visual retrieval must use the same validated unit/lesson identity carried by the material requirement; lesson retrieval must use the current governed curriculum route for that identity. If either exact role cannot be resolved, return a bounded missing/ambiguous result for that role only after its governed route is exhausted. Never substitute memory, prior-chat text, a neighboring-unit file, or arbitrary prose for exact source identity.

This gate composes with the existing Reusable Visual Gate and current curriculum source owners. It adds no second curriculum reader, visual registry, scheduler, persistence layer, or external-write authority.

## Reusable Visual Gate
Before visual retrieval, start from a validated `MaterialRequirement` and use the governed visual-needs decision. `no-visual-needed` continues with no asset query or image-gap work. `visuals-required` may perform one bounded Visual Asset Library read only when separately authorized, then filters to eligible, human-reviewed candidates and consumes one cohesive visual plan.
For teacher-language reuse selection, inherit `01_Shared_Standards/instructional-design/visual-asset-picker-standard.md`. The Asset Picker resolves reuse-first selection and preserves selected asset identity/constraints; this workflow consumes that handoff without reinterpreting the teacher's original selection request.
Reuse a suitable approved asset before proposing a new equivalent, record every selected approved asset ID, and do not add decorative visuals by default. Never infer approval or compatibility from filenames, notes, prompts, comments, or arbitrary prose. For every unresolved required role, emit the deterministic human image-gap brief. Pause final student-facing production until each required missing asset is human-created, reviewed, and approved. A clearly labeled placeholder is allowed only in a separately authorized draft preview. Selection is advisory and grants no production, publication, approval, classroom-use, or external-write authority.
## Final Delivery QA
Before final delivery, check that the learning task is easy to start; directions are short and sequenced; visual density is manageable; student actions are explicit; layout supports classroom use; worksheets have sufficient response space; slides have one main idea and obvious hierarchy; vocabulary matches its governing source; and no required visual role remains unresolved.
## Modular Context Rules
Use the smallest relevant context for each task. Legacy Custom GPT files such as `memory/instructional-defaults.yaml`, `memory/visual-style-rules.md`, `memory/unit-folder-map.yaml`, `memory/qa-checklist.yaml`, and `agent_tools/material_qa.py` are reference snapshots until migrated into Agent OS standards, templates, or tooling. Check visual-style rules only when visuals or layout matter, unit-folder maps only when Drive placement or unit assets matter, and QA checklists before final student-facing delivery. Use helper scripts only for reviewing or final-checking generated material files.
## Assessment Artifact Gate
Before assessment-materials integration review, verify that the assessment artifact is accessible in the shared unit workspace. If not accessible, return exactly:
`Materials Integration Status: Blocked - Artifact Not Accessible`
Then name missing title, expected location, shared link, status/version log entry, and access confirmation needed from the canonical assessment/evidence owner.
## Memory Boundary
Use Memory only for lightweight reusable context, preferences, and short working summaries. Do not store full source materials, shared documents, asset indexes, formal release notes, version logs, or long histories in Memory.
## Version
0.4.0
## Changelog
- 0.4.0 adds the assessment-criteria integration gate: preserve learning-evidence references, project only current governed student-facing criteria, keep teacher scoring/calibration guidance separate, and never invent rubric content (#1788).
- 0.3.0 classifies direct teacher revisions before production gating and routes qualifying existing-artifact edits through the Teacher-Directed Revision Lane (#1013).
- 0.2.2 added the current reusable-visual gate and final-delivery QA behavior.
