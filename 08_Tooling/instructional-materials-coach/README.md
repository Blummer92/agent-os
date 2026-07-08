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
- See `docs/safety.md` and
  `02_Agent_Overlays/instructional-materials-coach.md`.

## Installation

    pip install -e .

## Setup

1. Create a Google Cloud project and OAuth client credentials (Desktop
   app type), download the client secret JSON.
2. Copy `.env.example` to `.env` and fill in
   `GOOGLE_OAUTH_CLIENT_SECRET_PATH` and `GOOGLE_OAUTH_TOKEN_PATH`.
3. Create (or reuse) an approved Slides template and Doc template in
   Drive, each containing `{{token}}`-style placeholders matching the
   tokens your lesson content YAML produces (see
   `samples/sample_lesson.yaml`).

## Usage

    ALLOW_WRITE=true python -m instructional_materials_coach.cli \
      --content samples/sample_lesson.yaml \
      --slides-template <slides_template_id> \
      --doc-template <doc_template_id> \
      --target-folder <target_drive_folder_id>

Prints the generated Slides and Doc links on success.

## Tests

    pytest tests/

All tests run without live Google credentials — the pure functions
(`content_spec.py`, `slides_requests.py`, `docs_requests.py`) are tested
directly, and the thin API wrappers (`drive_client.py`,
`workspace_clients.py`, `cli.py`) are tested against a mocked Google
client.

## Limitations

- **Not tested against a live Drive/Slides/Docs account in this
  session** — no Google credentials or template files were available.
  The operator must supply their own OAuth credentials and template
  files and validate the live path themselves.
- Worksheet generation supports flat paragraph placeholders only; no
  table or answer-key templating yet.
- Placeholder tokens use literal `{{token_name}}` substring matching
  (`replaceAllText` is not regex-aware) — avoid using that exact text in
  real lesson content.
