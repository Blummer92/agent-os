# Part A Implementation: Phase 0 Baseline (Corrected) — 2026-07-12

**Rebased to PR #12 head (9f0a409)**

## Repository State

- **Branch**: `claude/workflow-scheduler-task-99sk7d` (rebased to 9f0a409)
- **PR #12 head**: 9f0a409 "Clean up instructional design agent pipeline"
- **Instructional Design standards**: ✅ PRESENT (not missing)
- **Working tree**: Clean after rebase

## Critical Files Verification

### Instructional Design Standards (Now Present ✅)
- ✅ `01_Shared_Standards/instructional-design/unit-alignment-rules.md`
- ✅ `01_Shared_Standards/instructional-design/unit-alignment-essential-questions.md`
- ✅ `01_Shared_Standards/instructional-design/teacher-modeling-standards.md`
- ✅ `01_Shared_Standards/instructional-design/material-quality-rubric.md`
- ✅ `01_Shared_Standards/instructional-design/production-gates-and-compute.md`
- ✅ `01_Shared_Standards/instructional-design/student-language-standard.md`
- ✅ `01_Shared_Standards/instructional-design/README.md` (curriculum pipeline table)

### IMC Status (Verified Against Current Branch)
- **Overlay file**: version 0.3.0 ✅
- **Inherited standards**: Includes instructional-design standards ✅
  - learning-science-rules.md
  - material-quality-rubric.md
  - production-gates-and-compute.md
  - student-language-standard.md
- **Registry (agent-inheritance-registry.md)**: Will need verification/update
- **Status**: Version matches expected state from PR #12

## Issue Status Summary (Corrected)

### Issue 1: Unit Alignment Gate Wording Over-Requires ✅ ACTIONABLE
- **Status**: FOUND IN CURRENT BRANCH
- **Location**: `01_Shared_Standards/instructional-design/README.md`, line 13
- **Current wording**: "Six alignment checks and 12 essential questions pass"
- **Problem**: Gate wording conflates basic ready-for-modeling (six checks) with Tier 2 certification (12 questions)
- **Standards truth** (from unit-alignment-rules.md):
  - Six checks = ready-for-modeling gate (lines 45-75)
  - Tier 2: 12 essential questions = verification after six checks pass (lines 84-88)
  - Both required before Teacher Modeling advance (line 82)
- **Fix needed**: Update pipeline table to clarify two-tier structure
- **Action**: Modify README pipeline table Gate column for Unit Alignment stage

### Issue 2: Overlay Contract Enforcement ✅ VERIFIED
- **Status**: All 10 overlays compliant with 7-section contract
- **Finding**: No violations in current branch
- **Action**: No changes needed

### Issue 3: Instructional Materials Coach Inheritance ✅ VERIFIED
- **Status**: No mismatch (branch drift was in previous branch)
- **Current state matches expected**:
  - Overlay file: version 0.3.0 ✅
  - Overlay inheritance: Includes instructional-design standards ✅
  - Changelog: Shows progression 0.1.0 → 0.1.1 → 0.2.0 → 0.3.0
- **Action**: No changes needed (already correct on PR #12)

### Issue 4: Prompt Templates Duplicate Standards ✅ VERIFIED
- **Status**: Templates already use thin wrapper pattern
- **Findings**: No embedded standards definitions found
- **Action**: No changes needed (already compliant)

### Issue 5: Tests Lack Machine-Checkable Output Contract ✅ ACTIONABLE
- **Status**: Current tests use natural-language expectations
- **Example files**: `07_Agent_Tests/instructional-materials-coach.tests.md`
- **Needed**: Define output schema with required keys
- **Action**: Create schema and update test expectations

## Correct Phase Status

- ✅ **Phase 0**: Repo state verified (this document)
- ✅ **Phase 1**: Unit Alignment wording found and actionable
- ✅ **Phase 2**: Overlay contract verified; compliant
- ✅ **Phase 3**: IMC verified; already correct
- ✅ **Phase 4**: Prompt templates verified; no action needed
- ✅ **Phase 5**: Output schema needed; actionable

## Key Correction

**Previous assessment was based on branch without instructional-design changes.** Current PR #12 branch has:
- All instructional design standards files
- IMC at correct version (0.3.0)
- Clear Tier 2 structure in unit-alignment-rules.md

The issue tracker was accurate; the branch wasn't.

## Next Steps

1. Apply Part A schema changes (Phase 5 output schema)
2. Fix Issue 1 pipeline table wording
3. Verify registry matches IMC overlay
4. Commit Part A cleanup work
5. Keep separate from Workflow Scheduler implementation
