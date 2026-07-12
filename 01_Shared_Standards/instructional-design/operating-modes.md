# Instructional Design Operating Modes

Use these modes so curriculum agents can support daily planning without weakening
production safety.

## Mode Field

Every curriculum prompt should include `mode: Draft | Gate | Production`.
If missing, default to Draft for generation requests and Gate for verification
requests.

## Draft Mode

Use for brainstorming, rough lesson planning, sample modeling, prototype slides,
early worksheets, or incomplete inputs.

Agents may:
- Make reasonable assumptions.
- Create local drafts or prototypes.
- Ask for missing inputs without blocking helpful draft output.

Agents must:
- Label output `DRAFT — not verified for production use`.
- List assumptions and missing inputs.
- Set `production_ready: false`.
- Avoid production writes, governed fields, shared curriculum repositories,
  master templates, Notion readiness fields, and final student-facing documents.

## Gate Mode

Use for readiness checks. Agents verify required gates and return PASS/BLOCKED.
They should name blockers, missing fields, next owner, and handoff artifacts.
They should not generate polished production materials.

## Production Mode

Use for final classroom-ready output, publishing, or governed writes. Existing
hard-stop gates apply. Agents must not proceed unless required gates pass.
Human approval is required for production writes, governed field changes, new
systems of record, and breaking standards changes.

## Core Rule

Agents may create drafts when required fields are incomplete, but they must label
assumptions, avoid production writes, and not mark work as ready until the
required gate passes.

## Version

0.1.0