# Instructional Materials Coach

Builds a Google Slides deck and Google Docs worksheet for one lesson by duplicating an approved template pair and replacing placeholder tokens with lesson content. It also provides a pure/offline Source -> Lesson Bundle planning seam that coordinates existing governed material requirements before any connected production occurs.

## Offline lesson bundles
`lesson_bundle.py` plans a bounded set of requested classroom-material members from caller-supplied current-curriculum evidence and validated `MaterialRequirement` records. It is coordination only: it performs no source retrieval, generation, credential access, Drive/Notion call, provider execution, persistence, publication, or sharing change.

A bundle does not create a second canonical lesson schema. Shared identity comes from the existing resolved current-curriculum state plus the common course/unit/lesson and curriculum-handoff references already carried by each `MaterialRequirement`. Each requirement keeps its own content-bound fingerprint; different artifact types are not required to have identical MaterialRequirement fingerprints.

The planner selects required members plus optional members that are actually available, so a minimal request does not expand into a fixed oversized package. It fails closed on cross-artifact course/unit/lesson, handoff provenance, learning-evidence, Teacher Modeling, or conflicting vocabulary-reference drift. An artifact may omit vocabulary that is irrelevant to it; if the same vocabulary stable ID appears in multiple members, its governed reference identity must agree.

`plan_bundle_member_revision()` delegates one explicitly targeted member to the existing `plan_instructional_artifact_reuse()` contract with caller-supplied changed dependency keys and impact map. Other bundle members are reported unchanged; bundle membership does not authorize broad regeneration.

All bundle authority evidence remains false. A successful plan grants no execution, external-write, production, publication, approval, readiness, or side-effect authority. Connected Slides/Docs production remains a separate governed path.

## Safety
- Never edits template/master files directly; it duplicates first, then writes only to the copy.
- Requires an explicit `--target-folder`; it never guesses a Drive destination.
- Refuses writes unless `ALLOW_WRITE=true`, in addition to Agent OS write-authorization rules.
- Connected builds require a supplied governed MaterialRequirement before Google credentials are requested.
- The application-owned live-build callable accepts already-built Drive/Slides/Docs clients; it never launches interactive OAuth, reads credential environment variables, invokes a shell/Scheduler, or writes to Notion.
- Before copying, both templates and the exact destination are checked for expected type, untrashed state, and Drive `canCopy` / `canAddChildren` capability evidence.
- Copies carry bounded private idempotency properties. An ambiguous copy is reconciled in the exact destination before any later create; multiple/conflicting matches stop for manual reconciliation.
- Slides and Docs are tracked independently. Partial success is reported truthfully; the tool does not claim pair-level transactionality and does not automatically delete/trash partial artifacts.
- Slides/Docs updates bind `writeControl.requiredRevisionId` to the copied artifact revision observed immediately before mutation.
- Final Drive readback verifies file ID/type/parent/idempotency evidence and records the web link and shared-drive `driveId` when present. Sharing is observed only; this tool never changes ACLs.
- Drive metadata/list/copy calls explicitly support My Drive/shared-drive objects while retaining the narrow `drive.file` OAuth scope.
- Unresolved required visual roles block final production. Visual planning grants no production, publication, approval, readiness, image-generation, or external-write authority.
- Teacher-reference PDF rendering is offline and caller-supplied: `render_teacher_reference_pdf()` accepts an already-built bounded reference plus optional image bytes keyed by exact governed `asset_id`, `stable_ref`, or `external_file_id`. It performs no network retrieval, no second asset-selection decision, and no Drive/Notion write. Missing bytes preserve the approved identity text or explicit gap rather than fabricating a visual.
- See `docs/safety.md` and `02_Agent_Overlays/instructional-materials-coach.md`.

## Installation
Development may use editable installs:

    pip install -e ./src
    pip install -e ./08_Tooling/instructional-materials-coach

Correctness is validated with ordinary non-editable wheels. `instructional-materials-coach` 0.2.0 declares `instructional-workflow-contracts>=0.1.0,<0.2.0`, built from the existing `src/instructional_workflow_contracts/` source without copying or vendoring.

## Setup
1. Create Google OAuth desktop credentials and download the client secret JSON.
2. Copy `.env.example` to `.env`; set `GOOGLE_OAUTH_CLIENT_SECRET_PATH` and `GOOGLE_OAUTH_TOKEN_PATH`.
3. Use approved Slides and Docs templates containing the `{{token}}` placeholders expected by `samples/sample_lesson.yaml`.
4. Supply a validated MaterialRequirement JSON record. For `visuals-required`, supply previously governed ArtifactManifest and visual-compatibility evidence as local JSON; the CLI does not retrieve Visual Asset Library records.

## Usage
A no-visual build still requires the governed MaterialRequirement:

    ALLOW_WRITE=true python -m instructional_materials_coach.cli build \
      --content samples/sample_lesson.yaml \
      --slides-template <slides_template_id> \
      --doc-template <doc_template_id> \
      --target-folder <target_drive_folder_id> \
      --material-requirement <material_requirement.json>

For `visuals-required`, add already-governed evidence as applicable:

    --artifact-manifests <artifact_manifests.json> \
    --visual-candidates <visual_candidates.json> \
    --visual-source-revision <source_revision> \
    --changed-dependency-keys <changed_dependency_keys.json> \
    --impact-map <impact_map.json>

The runtime reuses the public MaterialRequirement validator, visual-needs planner, canonical reuse planner, visual-candidate filter, and cohesive visual planner. The CLI remains the manual credential wrapper and delegates the external operation to `build_live_materials()` after governed content/visual checks pass.

On success it prints selected approved Asset IDs, when any, plus the verified generated Slides and Doc links.

## Teacher-reference PDFs
`teacher_reference.py` projects bounded Unit Alignment / Teacher Modeling evidence and governed visual assignments. `teacher_reference_pdf.py` renders those projections to PDF with ReportLab.

The PDF renderer deliberately has no retrieval client. Callers may supply already-authorized image bytes through `asset_content`; keys must be exact identities already carried by the projection. If no bytes are supplied for an approved identity, the PDF keeps the identity visible instead of widening authority or silently fetching content. Explicit gaps remain explicit. This makes the render seam usable by repository tests and future authorized artifact workflows without coupling it to Drive, the Visual Asset Library, or an image-generation provider.

## Learning Loop (Notion Lessons Learned)
This tool does not write to Notion. On a failed build it writes a local YAML lesson-candidate record to `reports/lessons/` (override with `--lessons-dir`) for human review.

To log a lesson manually:

    python -m instructional_materials_coach.cli log-lesson \
      --title "Template had a stale placeholder" \
      --what-happened "QA caught {{objective_2}} left unreplaced in a delivered deck." \
      --what-to-do-next-time "Validate all tokens are replaced before sharing the link." \
      --severity Medium \
      --learning-type "QA feedback"

See `docs/notion-field-mapping.md` for the human-applied Notion field mapping.

## Tests
    pytest tests/

Focused lesson-bundle coverage:

    PYTHONPATH=src:08_Tooling/instructional-materials-coach/src python -m pytest 08_Tooling/instructional-materials-coach/tests/test_lesson_bundle.py -q

Tests use fakes/mocks only for the C4A live-build boundary and perform no live Google or Notion I/O. The packaging proof builds the root Navigation Registry, `instructional-workflow-contracts`, and coach wheels; verifies exclusive package ownership and one-way dependency metadata; installs from wheels; strips `PYTHONPATH`; and imports the coach/contracts from outside the repository.

## Release checklist
- Build all relevant wheels with ordinary setuptools/pip tooling.
- Verify the root Navigation Registry wheel excludes `instructional_workflow_contracts`.
- Verify the contracts wheel excludes `navigation_registry` and the coach package.
- Verify coach metadata declares the bounded contracts dependency and not the reverse.
- Run non-editable outside-repository import proof plus focused coach/runtime tests.
- Run repository structure and aggregate validation against the exact PR head.
- Do not merge or publish while any required exact-head check is failing or pending.

## Limitations
- Lesson-bundle planning is offline coordination only; it does not yet execute a bundle against Drive or change the connected CLI's current Slides + worksheet production behavior.
- C4A hardens the repository production client but does not authorize credentials or a real Google call. Connected live execution remains separately governed by C4B/#1196 and C4/#119.
- There is no cross-resource transaction for the Slides/Docs pair; partial or ambiguous results require bounded reconciliation rather than automatic cleanup.
- The visual-reuse bridge consumes supplied governed evidence only; it does not retrieve the Visual Asset Library or generate images. Teacher-reference PDFs can embed caller-supplied bytes only after the projection has already authorized the exact identity.
- Worksheet generation supports flat paragraph placeholders only; no table or answer-key templating yet.
- Placeholder replacement uses literal `{{token_name}}` substring matching, not regex matching.
