# Common Overlay Rules

Every agent overlay in this folder inherits these blocks by reference.
Overlays must not repeat this content; they add only Mission, Canonical
Role, Owned Systems, Allowed/Blocked Write Surfaces, and Required Handoff
Targets.

## Inherited Standards (baseline for all overlays)
- Global Engineering 0.1.0
- Read-Only Default 0.1.0
- Source-of-Truth Checks 0.1.0

## Required Human Approval Points
- Production writes
- Governed field changes
- New systems of record
- Breaking standards changes

## Required Final Report Format
- Files changed
- Tests run
- Docs updated
- Notion updates recommended
- Memory recommendations

## Stop Conditions
- Ambiguous target
- Missing authorization
- Conflicting source of truth
- Governed field risk
