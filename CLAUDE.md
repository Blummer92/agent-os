# Agent OS — CLAUDE.md

**Version:** 0.1.1-draft  
**Last Updated:** 2026-07-07  
**Repository:** `blummer92/agent-os`  
**Branch:** `claude/claude-md-docs-dnzy18`

---

## Overview

**Agent OS** is a modular, standards-first knowledge base for engineering agents. It defines governance rules, shared standards, agent-specific overlays, registry maps, reusable templates, and examples—all organized to provide clear source-of-truth documentation for AI assistants working on coding and automation tasks.

This repository is a **draft canonical source** for engineering-agent standards. It does not yet govern live agent behavior but serves as a reference library for review, adoption, and future integration into live systems.

---

## Repository Structure

Agent OS is organized into eight main directories, each with a specific purpose:

### `00_Governance/`
Foundation-level rules that apply to all agents before any role-specific overlay.

**Key files:**
- `ownership-and-source-of-truth.md` — Where policy lives; no duplication across modules.
- `write-authorization-policy.md` — Write defaults to read-only; explicit approval required.
- `engineering-standards-framework.md` — Core coding principles: modular design, testing, reporting.
- `memory-rules.md` — What agents should memorize vs. reference from files.
- `standards-change-control.md` — How to update standards safely.
- `agent-creation-policy.md` — Rule against redundant agents; points to `04_Registry/agent-inheritance-registry.md` for the canonical agent list.

**Convention:** Governance rules are inherited by all other modules. They are not repeated elsewhere.

### `01_Shared_Standards/`
Domain-specific standards inherited by all agents working in that domain.

**Organization by domain:**
- `global-engineering/` — Applies to every coding agent (read-only default, testing, release, bug learning)
- `python/` — Python-specific module structure, testing, packaging
- `apps-script/` — Google Apps Script deployment and sync safety
- `google-workspace/` — Google Workspace API boundaries and write safety
- `dashboard-governance/` — Dashboard schema changes and owner/consumer patterns
- `qa-test/` — Acceptance testing, regression testing, release evidence
- `notion/` — Notion record updates, learning databases, knowledge policy

**Convention:** Shared standards define inherited rules once. Agent-specific exceptions go in overlays.

### `02_Agent_Overlays/`
Agent-specific execution behavior, scope limits, stop conditions, and handoff rules.

**`_common-overlay-rules.md`** holds the blocks shared by every overlay — baseline
inherited standards, required human approval points, final report format, and
stop conditions. Individual overlays reference this file rather than repeating
it; they contain only Mission, Canonical Role, Owned Systems, Allowed/Blocked
Write Surfaces, and Required Handoff Targets.

**Overlays provided:**
- `python-development-overlay.md` — Python coding agent specifics
- `google-workspace-automation-engineer.md` — Workspace API automation rules
- `dashboard-builder-overlay.md` — Dashboard modeling and building
- `apps-script-sync-test-overlay.md` — Sync validation for Apps Script
- `qa-test-agent.md` — QA automation and testing workflows
- `modeling-dashboard-governance-agent.md` — Dashboard governance oversight
- `workspace-implementation-overlay.md` — Scoped implementation behaviors
- `integration-manager.md` — Integration routing and handoff rules
- `instructional-materials-coach.md` — Slide deck and worksheet build rules

**Convention:** When adding a new overlay, reference `_common-overlay-rules.md`
for the shared sections instead of copying them in.

**Convention:** Overlays inherit from shared standards. They contain only agent-specific scope, exceptions, stop conditions, and routing rules.

### `03_Templates/`
Reusable templates for prompts, project structures, and reports.

**Contents:**
- `prompts/` — Standard prompts for bug learning, agent updates, releases, compliance
- `python-project-template/` — Python project folder structure, README, env files, pyproject config
- `reports/` — Bug report, QA test report, final report, and release checklist templates

**Convention:** Templates are starting points. Adapt them to your context; don't treat them as rigid rules.

### `04_Registry/`
Routing tables, ownership, module versions, and aliases.

**Key files:**
- `ownership-matrix.md` — Which agent owns each responsibility.
- `responsibility-matrix.md` — What each agent is responsible for.
- `module-version-map.md` — Current versions of all modules and standards.
- `alias-and-deprecation-map.md` — Deprecated names and their replacements.
- `agent-inheritance-registry.md` — Maps canonical agent names to overlays.

**Convention:** Registry data is the source of truth for routing, ownership, and version tracking. Do not duplicate this data elsewhere.

### `05_Examples/`
Illustrative examples of compliant usage.

**Examples show:**
- Compliant agent responses to governance rules.
- Registry compliance test patterns.
- Compliant Python tool implementations.

**Convention:** Examples are illustrative only and do not override standards. Use them as reference implementations.

### `06_Archive/`
Retired, superseded, or historical documents.

**Contents:**
- `superseded-documents.md` — Links to documents that have been replaced.
- `retired-aliases.md` — Old names no longer in use.

**Convention:** Archive is read-only reference. Do not restore archived documents without governance approval.

### `07_Agent_Tests/`
Test prompts and automated structural checks that prove the knowledge
base is working — both that agents follow their overlays and that the
files themselves stay internally consistent.

**Contents:**
- `common-test-checklist.md` — Shared pass/fail checklist for every agent
  compliance test (mirrors `_common-overlay-rules.md`).
- `<overlay-name>.tests.md` — One file per overlay in `02_Agent_Overlays/`,
  each with 4 copy-paste prompts (in-scope request, blocked-write-surface
  request, ambiguous-target request, final-report request).
- `validate-repo-structure.sh` — Runnable script checking line limits, no
  reintroduced duplication, and registry/overlay/test consistency. Run
  with `bash 07_Agent_Tests/validate-repo-structure.sh`.

**Convention:** Every new overlay needs a matching `.tests.md` file, or
`validate-repo-structure.sh` fails its coverage check.

### `08_Tooling/`
Runnable reference implementations that back a specific agent overlay —
the one place in this repo with actual executable code, not just
standards documentation.

**Contents:**
- `instructional-materials-coach/` — Python package backing the
  Instructional Materials Coach overlay. Duplicates an approved Slides/Doc
  template into a confirmed target Drive folder and replaces placeholder
  tokens with lesson content, instead of building decks and worksheets by
  hand. Follows `03_Templates/python-project-template/` conventions
  (`src/`, `tests/`, `docs/`, `samples/` layout). Unit tests run with no
  live Google credentials (pure functions plus mocked API clients); live
  Drive/Slides/Docs calls need the operator's own OAuth credentials and
  template files, set up outside this repo.

**Convention:** Code here backs one specific overlay and must not
duplicate rules already stated in that overlay or in
`01_Shared_Standards/`. Safety boundaries (what it's allowed to write)
live in the overlay, not in the code's README.

---

## Key Conventions

### 1. Source-of-Truth Hierarchy

When working with standards, follow this hierarchy:

1. **Governance rules** (`00_Governance/`) apply first and are inherited by everything.
2. **Shared standards** (`01_Shared_Standards/`) apply to all agents in a domain.
3. **Overlays** (`02_Agent_Overlays/`) add agent-specific scope, exceptions, and stop conditions.
4. **Registry** (`04_Registry/`) provides routing, ownership, and version data.
5. **Templates and Examples** (`03_Templates/`, `05_Examples/`) are starting points, not mandatory.

**Never duplicate a rule.** If a shared standard already defines behavior, reference it in the overlay rather than repeating it.

### 2. Ownership and Scope Confirmation

Before making changes or decisions:

1. **Identify the system of record.** Where does this policy actually live?
2. **Check ownership.** Who owns this module, field, or responsibility?
3. **Confirm authorization.** Do you have permission to modify this?

If ownership is unclear, stop and ask before proceeding.

### 3. Read-Only Default Policy

**All external systems and shared documents default to read-only.**

Writes require:
- Explicit target confirmation
- Authorization scope (who approved this?)
- Ownership confirmation (does this agent own this data?)

Examples of write-restricted systems:
- Notion databases (especially readiness, approval, audit fields)
- Google Sheets and Drive
- Production dashboards
- Agent memory fields

### 4. Documentation Under 100 Lines

All Markdown files must stay under 100 lines to ensure clarity and readiness for future tool integration. Split large docs into detail files (see `FOLDER_TREE_DETAILS_01.md` and `FOLDER_TREE_DETAILS_02.md` pattern).

**Exception:** This CLAUDE.md file is exempt due to its role as comprehensive codebase guidance.

### 5. Markdown Formatting Rules

- Use clear section headers (`#`, `##`, `###`).
- Keep lists concise; use bullets for clarity.
- Reference other files explicitly: `See 01_Shared_Standards/global-engineering/testing-standard.md`.
- Do not duplicate policy text; link instead.

### 6. Versioning

- Repository version: Defined in `VERSION.md`.
- Module versions: Listed in `04_Registry/module-version-map.md`.
- Changes tracked in `CHANGELOG.md`.

When updating standards:
1. Update the relevant file in `00_Governance/` or `01_Shared_Standards/`.
2. Update module versions in `04_Registry/module-version-map.md`.
3. Add entry to `CHANGELOG.md`.
4. Create a pull request with clear summary of changes.

---

## Common Tasks and Workflows

### Task: Add a New Shared Standard

1. Create the file in the appropriate `01_Shared_Standards/` subfolder.
2. Keep it under 100 lines; split into detail files if needed.
3. Reference (don't duplicate) governance rules.
4. Add an entry to `04_Registry/module-version-map.md`.
5. Update `CHANGELOG.md`.
6. Create a pull request; tag for governance review.

### Task: Update an Existing Standard

1. Edit the file in its current location (shared or overlay).
2. Check `04_Registry/ownership-matrix.md` to see who owns this domain.
3. If the change affects multiple agents, update all relevant overlays.
4. Update module version in registry.
5. Add to `CHANGELOG.md` with a summary.
6. Create a pull request explaining the "why."

### Task: Create an Agent Overlay

1. Check `04_Registry/agent-inheritance-registry.md` for your agent name.
2. Create or update `02_Agent_Overlays/<agent-name>.md`.
3. Start with inheritance: "Inherits from `01_Shared_Standards/<domain>/`".
4. Add only agent-specific scope, exceptions, stop conditions, and handoff rules.
5. Do not repeat inherited rules—reference them instead.
6. Update registry to map agent name to overlay.
7. Create a pull request for review.

### Task: Report on Standards Usage

When reporting on agent work:
1. List which shared standards and overlays were applied.
2. Note any governance rule deviations (if authorized).
3. Reference specific files by path.
4. If changes need to be made to standards, flag them separately for governance review.

### Task: Handle Ambiguous Authorization

**If authorization is unclear, stop and ask.** Do not assume; do not work around it.

Example escalations:
- "This Sheets modification needs write permission to a governance field. Who owns this?"
- "Is this Python module version update in scope for this agent?"
- "This change affects the Dashboard Sync Agent overlap with Modeling Agent. Do both owners approve?"

---

## For AI Assistants: Key Behaviors

### When Starting Work

1. **Read the relevant standards and overlay first.** Do not guess at conventions.
2. **Check `04_Registry/ownership-matrix.md`.** Confirm who owns this domain.
3. **Verify authorization.** Look for explicit approval before touching write-restricted systems.
4. **Reference, don't duplicate.** If a rule is defined in shared standards, link to it in your work.

### When Making Changes

1. **Identify the system of record.** Where does this policy live? Update it there.
2. **Keep Markdown under 100 lines.** Split into detail files if needed.
3. **Update version and changelog.** Every standards change needs a version bump.
4. **Run validation.** Ensure all Markdown files conform to the 100-line rule.

### When Uncertain

1. **Check the ownership matrix first.** Who owns this?
2. **Review governance rules.** Does `00_Governance/` define this behavior?
3. **Look for examples.** Are there similar cases in `05_Examples/`?
4. **Stop and ask if unclear.** Do not assume authorization or scope.

### When Reporting Work

Include:
- Files changed (with paths and line ranges if relevant)
- Standards and overlays applied
- Registry updates made
- New template or example contributions
- Any governance rule deviations (if authorized, include approval reference)
- Recommendations for memory (reusable rules vs. files to reference)

---

## Memory and Handoff Recommendations

### What to Memorize (Durable Rules)

After governance approval, save these reusable rules to agent memory:

- Core governance principles (read-only default, ownership confirmation)
- Domain-specific standards that apply to all agents in that domain
- Agent role and scope (from your overlay)
- Common stop conditions and escalation patterns

### What to Reference (Keep in Files)

Do not memorize; always reference from files:

- Full standards text (link instead)
- Registry data (ownership, versions, routing)
- Specific file paths and line numbers
- Examples and templates
- Archive notes and deprecated aliases
- One-time review details or change justifications

---

## Validation and Quality

### Pre-Commit Checks

Before committing:
- [ ] All `.md` files are under 100 lines (except this CLAUDE.md)
- [ ] No duplicated policy text (rules reference source instead)
- [ ] Registry entries updated (versions, ownership, aliases)
- [ ] `CHANGELOG.md` reflects the change
- [ ] Links are correct and file paths are accurate
- [ ] Overlays inherit from shared standards, not repeat them

### Validation Scripts

- `07_Agent_Tests/validate-repo-structure.sh` — **Run this before every
  commit.** Automated, enforced by nothing but your own discipline, but
  it actually executes and returns a pass/fail exit code:
  ```bash
  bash 07_Agent_Tests/validate-repo-structure.sh
  ```
  Checks: line limits, no reintroduced overlay duplication, no filename
  collisions between governance and registry, and full overlay/test
  coverage in both directions.
- `VALIDATION_REPORT.md` — Line count and format validation results (manual snapshot)
- `FILE_MANIFEST.md` — Complete file listing with descriptions
- `GITHUB_PACKAGE_VALIDATION.md` — GitHub upload validation checklist

### Agent Compliance Testing

`07_Agent_Tests/*.tests.md` holds copy-paste prompts per overlay to verify
an agent actually follows its standards (not just that the files are
well-formed). See `07_Agent_Tests/README.md` for how to run and score them.

---

## Git Workflow

### Branch Strategy

- **Main branch:** `main` — Stable, governance-approved state
- **Feature branches:** `claude/<description>` — Per-task development
- **Current branch for development:** `claude/claude-md-docs-dnzy18`

### Commit Convention

Use clear, descriptive commit messages:

```
[Governance | Standards | Registry | Overlay] Brief summary

- Specific file changes
- Rationale or context
- References to governance rule if relevant
```

Example:
```
[Standards] Add Python packaging standard

- Created 01_Shared_Standards/python/packaging-standard.md
- References 01_Shared_Standards/python/module-boundaries.md
- Updates registry module-version-map.md to 0.1.1
```

### Push and Pull Requests

1. Push to your feature branch.
2. Create a pull request with a clear title and description.
3. Include which overlays/standards are affected.
4. Tag for appropriate review (governance, domain owner, etc.).
5. Link to related issues or discussions if applicable.

---

## Troubleshooting

### Issue: Unsure Which File to Edit

**Solution:** Check `04_Registry/ownership-matrix.md` first. Look for:
- Is this a governance rule? Edit in `00_Governance/`.
- Is this a shared domain standard? Edit in `01_Shared_Standards/<domain>/`.
- Is this agent-specific? Edit in `02_Agent_Overlays/<agent-name>.md`.
- Is this data (routing, versions, ownership)? Edit in `04_Registry/`.

### Issue: Duplicate Policy Text Found

**Solution:** Remove the duplicate and replace with a reference:
- Change: "Default external systems to read-only. Writes require explicit target..."
- To: "See `01_Shared_Standards/global-engineering/read-only-default-policy.md` for write authorization rules."

### Issue: File Exceeds 100 Lines

**Solution:** Split into a main file and detail files:
- Main: `topic.md` (~90 lines, overview + links to details)
- Details: `topic-details-01.md`, `topic-details-02.md` (specific sections)
- Example: `FOLDER_TREE.md` (main) + `FOLDER_TREE_DETAILS_01.md`, `FOLDER_TREE_DETAILS_02.md` (details)

### Issue: Authorization Unclear

**Solution:** Stop. Do not guess. Examples of good escalation:
- "This Notion field is marked read-only in governance. Can I write to it?"
- "Does the Dashboard Builder Agent own this schema change, or does the Modeling Agent?"
- "Should I update agent memory or reference the file for this standard?"

---

## References and Next Steps

### Key Documents to Review First

- `00_Governance/ownership-and-source-of-truth.md` — Foundational principle
- `00_Governance/write-authorization-policy.md` — Default behavior
- `01_Shared_Standards/global-engineering/README.md` — Universal standards
- `04_Registry/ownership-matrix.md` — Responsibility routing

### For Specific Domains

- **Python:** `01_Shared_Standards/python/README.md`
- **Google Workspace:** `01_Shared_Standards/google-workspace/README.md`
- **Dashboards:** `01_Shared_Standards/dashboard-governance/README.md`
- **QA/Testing:** `01_Shared_Standards/qa-test/README.md`

### For Agent Work

Check your agent's overlay first, then inherited shared standards:
- Python Developer → `02_Agent_Overlays/python-development-overlay.md`
- Workspace Automation → `02_Agent_Overlays/google-workspace-automation-engineer.md`
- Dashboard Builder → `02_Agent_Overlays/dashboard-builder-overlay.md`
- QA Engineer → `02_Agent_Overlays/qa-test-agent.md`
- Instructional Materials Coach → `02_Agent_Overlays/instructional-materials-coach.md` (runnable code: `08_Tooling/instructional-materials-coach/`)

---

## Status and Adoption

**Current Status:** Adopted as draft canonical engineering-agent standards source.

**Scope:** This is a draft source library. Live agent behavior has not been modified based on these standards yet.

**Next Steps:**
1. Governance review and approval.
2. Confirm canonical storage location (GitHub, Notion, Drive).
3. Map live agent instructions to overlays and standards.
4. Create integration plan for live systems.

See `ADOPTION_REVIEW_PACKET.md` for detailed adoption guidance.

---

**Questions or feedback?** Open an issue on GitHub or reference `00_Governance/standards-change-control.md` for the official update process.
