# Common Overlay Rules

Every agent overlay in this folder inherits these blocks by reference. Overlays
must not repeat this content; they add only Mission, Canonical Role, Inherited
Standards, Owned Systems, Allowed Write Surfaces, Blocked Write Surfaces, and
Required Handoff Targets.

## Inherited Standards (baseline for all overlays)
- Global Engineering 0.4.0
- Read-Only Default 0.1.0
- Source-of-Truth Checks 0.1.0
- Agent Interaction Output Standard 0.1.0

## Required Human Approval Points
- Production writes
- Governed field changes
- New systems of record
- Breaking standards changes

## Required Final Report Format
Use the base report contract and presentation profile in
`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`.
Overlays add only domain evidence such as recommended Notion updates or memory
recommendations; they do not restate its fields, profiles, or ordering.

## Stop Conditions
- Ambiguous target
- Missing authorization
- Conflicting source of truth
- Governed field risk
