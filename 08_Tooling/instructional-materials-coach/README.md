# Instructional Materials Coach

Builds a Google Slides deck and a Google Docs worksheet for one lesson by
duplicating an approved template pair and replacing placeholder tokens
with lesson content, instead of building both by hand.

## Safety

- Never edits a template or master file directly — always duplicates
  first (`drive_client.duplicate_template`), then writes only to the copy.
- Requires an explicit `--target-folder` Drive folder ID; refuses to
  guess a destination.
- Refuses to run any write unless `ALLOW_WRITE=true` is set, on top of
  the Instructional Materials Coach overlay's write-authorization rules.
- A connected build also requires a supplied governed MaterialRequirement
  JSON record. Visual planning runs before Google credentials are requested.
- An unresolved required visual role blocks final production. Visual planning
  is advisory and does not grant production, publication, approval, readiness,
  image-generation, or external-write authority.
- See `docs/safety.md` and
  `02_Agent_Overlays/instructional-materials-coach.md`.

## Installation

For development, the repository validation environment may use editable installs:

    pip install -e ./src
    pip install -e ./08_Tooling/instructional-materials-coach

Correctness is validated with ordinary non-editable wheels. The coach distribution
is `instructional-materials-coach` 0.2.0 and declares a normal dependency on
`instructional-workflow-contracts>=0.1.0,<0.2.0`. The contracts distribution is
built from the existing `src/instructional_workflow_contracts/` package without
copying or vendoring its source.

## Setup

1. Create a Google Cloud project and OAuth client credentials (Desktop
   app type), download the client secret JSON.
2. Copy `.env.example` to `.env` and fill in
   `GOOGLE_OAUTH_CLIENT_SECRET_PATH` and `GOOGLE_OAUTH_TOKEN_PATH`.
3. Create (or reuse) an approved Slides template and Doc template in
   Drive, each containing `{{token}}`-style placeholders matching the
   tokens your lesson content YAML produces (see
   `samples/sample_lesson.yaml`).
4. Supply a validated MaterialRequirement JSON record. If its governed visual
   direction requires visuals, also supply previously validated ArtifactManifest
   and visual compatibility evidence as local JSON; the CLI does not retrieve
   Visual Asset Library records itself.

## Usage

A no-visual build requires the governed MaterialRequirement even though no asset
candidate work is performed:

    ALLOW_WRITE=true python -m instructional_materials_coach.cli build \
      --content samples/sample_lesson.yaml \
      --slides-template <slides_template_id> \
      --doc-template <doc_template_id> \
      --target-folder <target_drive_folder_id> \
      --material-requirement <material_requirement.json>

For `visuals-required`, provide already-governed local evidence as applicable:

    --artifact-manifests <artifact_manifests.json> \
    --visual-candidates <visual_candidates.json> \
    --visual-source-revision <source_revision> \
    --changed-dependency-keys <changed_dependency_keys.json> \
    --impact-map <impact_map.json>

The runtime reuses the existing public MaterialRequirement validator, visual-needs
planner, reusable-artifact planner, visual candidate filter, and cohesive visual
planner. It preserves selected approved Asset IDs and existing deterministic image-gap
briefs; it does not infer visual evidence from lesson YAML, filenames, notes, or prompts.

Prints selected approved Asset IDs, when any, plus the generated Slides and Doc links
on success.

## Learning Loop (Notion Lessons Learned)

This tool never writes to Notion — no agent in this repo has documented
Notion write authority, and Notion defaults to read-only everywhere (see
`01_Shared_Standards/notion/`). Instead, it produces a local,
structured **lesson-candidate record** that a human reviews and applies
to the real "Lessons Learned" Notion database themselves.

**On a failed build**, a YAML record is written automatically to
`reports/lessons/` (override with `--lessons-dir`) and the path is
printed to stderr.

**To log a lesson manually** (e.g. QA feedback found after the fact,
which the tool couldn't have caught itself):

    python -m instructional_materials_coach.cli log-lesson \
      --title "Template had a stale placeholder" \
      --what-happened "QA caught {{objective_2}} left unreplaced in a delivered deck." \
      --what-to-do-next-time "Validate all tokens are replaced before sharing the link." \
      --severity Medium \
      --learning-type "QA feedback"

See `docs/notion-field-mapping.md` for the field-by-field mapping used to
apply a local record to the real Notion database.

## Tests

    pytest tests/

All tests run without live Google or Notion credentials. The coach suite includes a
non-editable packaging proof that builds the root Navigation Registry wheel, the
`instructional-workflow-contracts` wheel, and the coach wheel; verifies exclusive
package ownership and one-way dependency metadata; installs the contracts and coach
from wheels; and imports them from outside the repository without `PYTHONPATH` or
`sys.path` mutation.

## Release checklist

- Build all three relevant wheels with ordinary setuptools/pip tooling.
- Verify the root Navigation Registry wheel excludes `instructional_workflow_contracts`.
- Verify the contracts wheel excludes `navigation_registry` and the coach package.
- Verify coach metadata declares the bounded contracts dependency and not the reverse.
- Run the non-editable outside-repository import proof and focused coach/runtime tests.
- Run repository structure and aggregate validation, and bind evidence to the exact PR head.
- Do not merge or publish while a required exact-head check is failing or pending.

## Limitations

- **Not tested against a live Drive/Slides/Docs account in this session** — no Google
  credentials or template files were used. The operator must separately authorize and
  validate any live connected path.
- The visual-reuse bridge consumes supplied governed evidence only. It does not retrieve
  Visual Asset Library records, generate images, or insert image binaries into Slides.
  It preserves selected Asset IDs for a separately authorized downstream asset-use step.
- Worksheet generation supports flat paragraph placeholders only; no table or answer-key
  templating yet.
- Placeholder tokens use literal `{{token_name}}` substring matching (`replaceAllText`
  is not regex-aware) — avoid using that exact text in real lesson content.
