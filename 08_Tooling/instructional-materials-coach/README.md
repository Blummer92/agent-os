# Instructional Materials Coach

Builds a Google Slides deck and Google Docs worksheet for one lesson by duplicating an approved template pair and replacing placeholder tokens with lesson content. It also provides a pure/offline Source -> Lesson Bundle planning seam that coordinates existing governed material requirements before any connected production occurs.

## Connected artifact delivery
A successful connected build treats the verified native Google Drive artifacts as the canonical editable finals: the slide deliverable is the exact native Google Slides file and the worksheet deliverable is the exact native Google Docs file in the approved Drive destination. `ArtifactReceipt` reports `delivery_kind=final`, `canonical_editable=true`, and `persistence_verified=true` only after the existing final Drive readback proves the exact file identity, expected native MIME type, approved parent folder, and matching idempotency/role evidence. Pair-level `succeeded` requires both native artifacts to meet that final contract.

A created/recovered file, an `updated` state without verified native metadata, a missing/empty destination, a failed or ambiguous readback, a partial Slides/Docs result, or any PDF/preview is not sufficient for canonical-final completion. PDFs are derived review/export artifacts only and never supersede the native Drive source merely because they are easier to download. PDF draft/preview generation is governed separately from this connected native-final contract.

## Student-material PDF drafts/previews
`student_material_pdf.py` renders a bounded student-material PDF preview from caller-supplied content already bound to one exact governed native artifact identity and revision. The caller must supply the expected current revision; stale or mismatched revision evidence fails closed before rendering.

A successful receipt is explicitly `preview`, `canonical=False`, and `render_verified=True`. It carries the exact native file ID, native revision ID, and approved source destination identity. The renderer verifies that a non-trivial PDF with a PDF header and EOF marker was actually written before reporting the preview available. Render or verification failure returns `blocked`; prose or a wireframe is never substituted as a completed PDF.

The PDF is a derived review/print/download artifact only. The native Google Docs/Slides file remains the canonical editable final. This offline renderer has no Google client, credential, Drive persistence, ACL, readiness, approval, publication, or source-authority mutation. Persisting a derived PDF to Drive remains a separately authorized external-write operation with its own exact destination/readback requirement.

## Reusable visual placement contract
`visual_placement.py` defines the repository-side fail-closed contract for binding one exact governed reusable asset to one exact Docs/Slides placement marker. Controlled markers use `{{visual:<role_id>}}`; coarse visual intent such as `slide`, `page`, `section`, or `student-facing` is never interpreted as a concrete position. Exactly one marker match is required. Missing, duplicate, malformed, or drifted markers stop placement.

`apps-script/VisualPlacementTransport.gs` is an **offline reference transport** for the separately governed dedicated Apps Script runtime. It demonstrates the approved `BlobSource` route: read the exact selected private Drive file, insert its blob into the exact admitted Docs/Slides target, remove only the matched marker, and return bounded placement evidence. It does not search/reselect assets or alter Drive sharing.

Repository implementation does not activate this runtime. Creating/deploying an Apps Script API executable, enabling the Apps Script API, selecting/configuring the shared standard Google Cloud project, OAuth/credential work, and live Drive/Docs/Slides writes require separate authorization. Candidate minimum functional scopes must be reverified before activation and are currently `drive.readonly`, `documents` when Docs are enabled, and `presentations` when Slides are enabled. Existing #1753 fail-closed connected-build behavior remains in force until a positive placement path is separately integrated, activated, and verified.

## Offline slide layout QA
`slide_layout_qa.py` provides a pure structural QA seam for student-facing slide render plans. It detects only mechanically provable defects: empty opaque placeholders layered above required instructional regions, unsafe required-text contrast when both colors are known, unintended overlap between required title/directions/model/task/teacher-cue regions, oversized supporting previews, and under-dominant focal models. Unknown colors or other judgments that cannot be established from the supplied structural plan route to `manual-review` rather than receiving a false pass. The seam performs no rendering, OCR/CV, provider call, classroom publication, or Drive mutation; broader phone/projector rendered review remains owned by #1835.

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
- Final Drive readback verifies file ID/type/parent/idempotency evidence and records the web link and shared-drive `driveId` when present. Only that verified native Drive file is reported as the canonical editable final. Sharing is observed only; this tool never changes ACLs.
- Drive metadata/list/copy calls explicitly support My Drive/shared-drive objects while retaining the narrow `drive.file` OAuth scope.
- Student-material PDF previews are local derived artifacts, never canonical finals, and perform zero Drive persistence.
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

On success it explicitly identifies the verified native Google Slides and Google Docs links as the canonical editable finals.

For a local derived PDF preview, a caller supplies the exact governed native source identity/revision plus the already-authorized student-material payload to `student_material_pdf.py`. The resulting receipt is usable only when it is render-verified and remains explicitly non-canonical; this path performs no Drive persistence or sharing mutation.

## Teacher-reference PDFs
`teacher_reference.py` projects bounded Unit Alignment / Teacher Modeling evidence and governed visual assignments. `teacher_reference_pdf.py` renders those projections to PDF with ReportLab.

The PDF renderer deliberately has no retrieval client. Callers may supply already-authorized image bytes through `asset_content`; keys must be exact identities already carried by the projection. If no bytes are supplied for an approved identity, the PDF keeps the identity visible instead of widening authority or silently fetching content. Explicit gaps remain explicit. This makes the render seam usable by repository tests and future authorized artifact workflows without coupling it to Drive, the Visual Asset Library, or an image-generation provider.

The teacher-reference renderer remains a separate teacher-facing seam and is not reused for student worksheet preview semantics.

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

Focused native-final delivery coverage:

    PYTHONPATH=src:08_Tooling/instructional-materials-coach/src python -m pytest 08_Tooling/instructional-materials-coach/tests/test_live_build.py 08_Tooling/instructional-materials-coach/tests/test_cli.py -q

Focused student-material PDF-preview coverage:

    PYTHONPATH=src:08_Tooling/instructional-materials-coach/src python -m pytest 08_Tooling/instructional-materials-coach/tests/test_student_material_pdf.py -q

Focused reusable-visual placement coverage:

    PYTHONPATH=src:08_Tooling/instructional-materials-coach/src python -m pytest 08_Tooling/instructional-materials-coach/tests/test_visual_placement.py -q

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
- The new reusable-visual placement seam is repository-only; it is not wired into the connected CLI until a separately governed runtime/deployment path is activated and verified.
- The student-material PDF seam renders from an exact caller-supplied authorized payload; it does not yet export Google Docs/Slides bytes through a live Google API. Live Docs/Slides-to-PDF export or Drive persistence remains separately governed.
- Worksheet generation supports flat paragraph placeholders only; no table or answer-key templating yet.
- Placeholder replacement uses literal `{{token_name}}` substring matching, not regex matching.
