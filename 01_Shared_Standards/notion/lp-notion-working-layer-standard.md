# LP Notion Working Layer Standard
This standard defines the bounded Notion working layer for lesson pacing, aggregate lesson-run evidence, mixed-class pathway briefs, and optional evidence summaries.
`04_Registry/lp-notion-working-layer-change-request.yaml` owns the exact targets, the field-by-field authority map, views, prohibited data, pilot records, and unresolved decisions; this file owns normative meaning.
LP1, LP2, LP3, LP5, LP9–LP12, LP14, and LP15 are consumed by reference. LP10 remains the sole owner of privacy, retention, suppression, disclosure, deletion, access, and destination authorization; LP11 remains the sole owner of calibration and lifecycle.
This standard authorizes no Notion write. A live schema, property, relation, view, form, template, or record change requires the separate Change Request and LP8 authorization.
The Change Request remains `proposed-not-authorized`; `live_change_authorized` and `pilot_execution_authorized` remain false, and any future pilot is `shadow_mode_only`.
No new readiness, evidence, OCR, learner-profile, or agent role is created; every writer named below is an already-registered agent or the teacher.
## sot-github-canonical
GitHub remains canonical for LP and EIA standards, normative vocabulary, versioned schemas, compatibility rules, reason codes, validation rules, fixtures, ownership, write authorization, privacy and calibration policy, and implementation history.
## sot-notion-working-layer
Notion may hold teacher planning records, provisional pacing assessments, lesson and pathway briefs, aggregate de-identified lesson-run summaries, bounded evidence summaries, review state, owner-specific gate displays, routing recommendations, and the governing GitHub contract reference.
## sot-no-competing-readiness-owner
The `Unit Alignment & Readiness Dashboard` remains the only unit-approval owner. Notion never redefines LP or EIA policy, never becomes the canonical schema source, and never becomes a raw student-work repository.
## authority-required-property-map
Every proposed property declares semantic owner, canonical source, display or planning purpose, permitted writer, retention class, privacy classification, authority class, prohibited implication, schema reference, and behaviour when missing, stale, conflicting, or `NOT_EVALUATED`.
## authority-no-gate-advancement
No property, formula, rollup, view, form, template, or automation advances Unit Generation Approval, modeling approval, Production Authorized, grading, learner placement, route assignment, or publication.
## authority-display-only-gates
A gate shown in the working layer is display-only, names its canonical owner and source record, and is never editable from a pacing record.
## authority-not-evaluated-visible
`NOT_EVALUATED` stays visible and distinct from blank, blocked, cleared, and not authorized; a blank value never inherits pacing state or a prior gate.
## architecture-unit-summary-layer
The unit dashboard carries only bounded advisory summary properties, a relation to the supporting planning record, and display-only gate mirrors.
## architecture-supporting-data-source
One supporting data source holds identity and provenance, pacing, difficulty diagnosis, instructional-function preservation, and mixed-class pathway fields for a lesson or task.
## architecture-lesson-run-log
One aggregate lesson-run pattern captures planned period, bounded checkpoint durations, operational summaries, completion and revision summaries, delay categories, supports that helped, evidence quality, implementation stage, bounded teacher notes, and teacher confidence.
## architecture-no-detailed-evidence-in-summary
Detailed lesson-run evidence and checkpoint records stay out of the unit summary dashboard.
## projection-separate-diagnosis-fields
The six LP3 demand and uncertainty dimensions remain six separate properties; no property combines, ranks, or scores them, and `Cognitive Load Risk` is never reused as a substitute.
## projection-pathway-briefs-only
Pathway properties carry route briefs, released and replacement time ranges, advanced dimensions, checkpoints, temporary grouping, re-entry, and common synthesis only.
## projection-no-learner-rows
No row, relation, or property represents an individual learner, a small subgroup identity, a diagnosis, a protected characteristic, or a permanent ability label.
## eia-summary-only-projection
When scan-derived evidence is used, the working layer receives only a bounded, privacy-approved evidence summary or stable reference carrying source type and date, dimension, disposition, confidence basis, review state, freshness, privacy state, limitations, usability, immutable non-authority fields, and schema reference.
## eia-prohibited-artifacts
The working layer never receives raw scans, page images, cropped answer regions, handwriting samples, full transcripts, answer-level or learner-level histories, model internals, embeddings, or one opaque similarity percentage.
## eia-no-direct-engine-connection
No extraction engine writes to Notion. Any later projection is a separately approved adapter that consumes normalized summaries, not engine objects.
## eia-confidence-is-not-correctness
Extraction confidence is extraction evidence only and never becomes correctness, mastery, evidence quality, pacing, pathway, grading, readiness, or approval.
## eia-visible-review-and-staleness
Review state, runtime eligibility, privacy state, disposition, confidence basis, limitations, and staleness display separately; `not-reviewed` is distinct from reviewed, accepted, rejected, and unusable, and a blank review state never defaults to accepted.
## eia-what-supported-and-unmeasured
The projection exposes what the evidence supported and what remains unmeasured instead of one overall summary score.
## display-no-colour-only-meaning
Meaning never depends on colour alone; advisory assessments and canonical gates carry distinct labels, text, icons, and screen-reader-readable property names.
## display-advisory-labelled
An advisory property visibly reads `Advisory` or `Recommendation` and never shares approval icons, badges, or dominant colours with a canonical gate.
## display-owner-named-on-gate
Every displayed gate names its canonical owner or source; visual prominence never implies that pacing outranks alignment, modeling, evidence, or production.
## display-no-combined-rollup
No combined rollup status, dominant LP status card, or view logic hides conflicting owner states; a record may show pacing feasibility and blocked readiness at once.
## display-accessibility-review
Accessibility review covers contrast, text labels, non-colour cues, and screen-reader-readable property names before any live change.
## retention-lp10-owned
Retention class, access role, deletion behaviour, suppression, small-cell handling, and destination authorization come from LP10; this standard only requires that each property declare them.
## retention-expiry-and-suppression
Every evidence summary carries review and expiry dates; stale, suspended, wrong-version, wrong-runtime, privacy-blocked, and deletion-pending summaries are suppressed rather than displayed as current.
## retention-deletion-and-supersession
Correction, supersession, deletion, cache and export behaviour, and rollback are defined before any live change; relation traversal, exports, alternate views, and joins must not reconstruct prohibited data.
## migration-historical-differentiation
Historical `Differentiation updated` values in the `Unit Alignment Tracker` remain display-only history; they are never read as pathway evidence or migrated into an LP5 field.
## migration-legacy-status-literals
Existing unscoped literals such as `Status`, `Ready to teach`, and `Ready for teacher modeling handoff` remain display-only history under the LP authority and state registry and never infer an LP gate.
## migration-notion-side-ownership-label
`Assessment Agent / Student Evidence Coach` is a Notion-side governance ownership label in `00_Governance/agent-os-governance-v1-baseline.md` with no GitHub overlay. Existing relations to it stay as they are; no LP property is written through that label, and no new agent role is created for this lane.
## pilot-shadow-mode-only
Any later pilot starts in LP11 shadow mode and changes no approval, gate, grade, or learner route.
## pilot-three-lesson-scope
The pilot covers three existing lesson patterns and specifies, per record, minimum populated fields, provisional timing range, diagnostic dimensions, route briefs where applicable, manual-review questions, post-lesson aggregate evidence, optional synthetic evidence summary, usefulness criteria, and rollback and deletion expectations.
## pilot-no-real-artifacts
No real student scan or classroom artifact is authorized for the design or for shadow-mode rehearsal.
## change-request-exact-target
The Change Request names the exact workspace, database, and data-source identifiers it would touch, and no other target.
## change-request-allowlist
The Change Request carries an exact property, relation, view, form, template, and record allowlist; anything outside it is out of scope.
## change-request-preflight-and-rollback
The Change Request defines preflight checks, verification, rollback, incident routing, and explicit non-authority guarantees before any live change.
## change-request-unresolved-decisions
Unresolved decisions are listed explicitly and each names the human owner who must resolve it; an unresolved decision blocks the live change rather than being defaulted.
## retired-view-names
`Ready for Teacher Modeling` and equivalent approval-sounding view names are retired in favour of advisory, owner-explicit names.
## retired-approval-styling
Approval-like green badges for advisory pacing, red/green-only distinctions, and icon-only status meaning are retired.
## retired-scan-properties
A `scanned work` property, an OCR transcript property, worksheet attachments for pacing analysis, and automatic ingestion from an extraction engine are retired.
## retired-score-properties
`Evidence Score`, `Mastery Score`, `Readiness Score`, and equivalent percentages, rankings, and combined rollups are retired.
