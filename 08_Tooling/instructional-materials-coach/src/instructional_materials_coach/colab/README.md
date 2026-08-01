# Colab: drafting lesson content with Gemini

Colab support ships as importable Python modules, not committed notebooks, so
the same offline tests cover this path and the repository keeps zero binary
files. Paste the cells below into a fresh notebook.

## What this does and does not do

Drafts lesson content and writes a local YAML spec. Per
`00_Governance/architecture-decisions/adr-0004-model-invocation-boundary.md`
the output is **draft content only**. This path writes nothing to Drive,
Slides, Docs, Notion, or GitHub. A human reviews the draft, then renders it
with the existing `imc-build` CLI behind its `ALLOW_WRITE` gate.

## Secrets

Add `GEMINI_API_KEY` in Colab's **Secrets** panel and grant the notebook
access. Never paste a key into a cell, and never commit one. `bootstrap.py`
reads the secret store first, then the environment, and raises if neither has
it.

## Cell 1 — install and clone

```python
!pip install -q "google-genai>=1.0" "pydantic>=2.7" "PyYAML>=6.0"
!git clone --depth 1 https://github.com/Blummer92/agent-os.git
%cd agent-os
import sys; sys.path.insert(0, "08_Tooling/instructional-materials-coach/src")
```

## Cell 2 — draft a lesson

```python
from instructional_materials_coach.colab.run_lesson_build import main

path = main(
    "Draft a 45-minute intro lesson on shot composition for a digital media class.",
    out_path="reports/drafts/shot-composition.yaml",
)
```

The key is read from Colab Secrets automatically; pass `api_key=` only if you
are running outside Colab with the value already in your environment.

## Cell 3 — review, then render

Open the YAML, edit anything the model got wrong, and only then render it.
Rendering is a separate, human-initiated step:

```python
!ALLOW_WRITE=true python -m instructional_materials_coach.cli build \
  --content reports/drafts/shot-composition.yaml \
  --slides-template <APPROVED_SLIDES_TEMPLATE_ID> \
  --doc-template <APPROVED_DOC_TEMPLATE_ID> \
  --target-folder <TARGET_DRIVE_FOLDER_ID>
```

## Notes

- `resolve_repo_root()` needs a real checkout; the pedagogical standards are
  rendered from `01_Shared_Standards/instructional-design/` at run time and
  fail closed if missing.
- Model selection lives in one constant, `DEFAULT_GEMINI_MODEL` in
  `genai_client.py`. Override per call with `model=`.
- Any tool passed to the model must be read-only. Automatic function calling
  executes tools, so a writable tool would be an unreviewed write path.
