# Context Budget Policy

## Purpose
This policy defines practical compute budgets for agent work. It limits file reads, searches, tests, and connector calls so agents can complete focused tasks without broad scans or repeated expensive actions.

## Budget Classes
| Class | Files | Searches | Tests | Connectors |
|---|---:|---:|---:|---:|
| Small | 3-7 | 1-3 | 0-1 targeted | 0 unless needed |
| Medium | 8-15 | 4-8 | 1-3 targeted | 1-2 max |
| Large | planning first | targeted first | final gate only | explicit approval |

Large tasks do not go straight to execution. Create a planning packet first, then split the work into small or medium packets.

## File Budget Policy
- Read files in priority order from the handoff packet.
- Prefer known facts and cached summaries before re-reading files.
- Stop before exceeding the file budget unless the user approves escalation.
- Avoid generated/cache folders such as `.git/`, `__pycache__/`, `node_modules/`, `.pytest_cache/`, build artifacts, and coverage output.
- Do not inspect Workflow Scheduler source for docs-only Memory Manager changes unless a specific integration claim must be checked.

## Search Budget Policy
- Prefer targeted grep/glob searches for exact filenames, symbols, or headings.
- Use broad search only after targeted search fails.
- Count repeated searches with minor wording changes against the same budget.
- Do not perform full-repo scans for one-file docs changes.
- Stop if the search target is unclear and ask for clarification instead of guessing.

## Test Budget Policy
- Do not run full test suites for docs-only changes.
- Use targeted tests for one-module source changes.
- Run the full suite only for final validation or broad behavior changes.
- Count repeated failed test runs against the same budget.
- Stop after repeated failures without new evidence.

## Connector Budget Policy
- Use connector calls only when needed to verify PR, branch, issue, or external state.
- Do not retry auth, permission, approval, or tool-policy failures without explicit user approval.
- Prefer one metadata call before fetching large diffs or comments.
- Do not subscribe, monitor, or schedule background checks unless explicitly requested.

## Budget Escalation
Escalate before exceeding the packet budget. The escalation note should state what was tried, what is missing, which budget would increase, and why the task cannot finish inside the current budget.

## Examples
### Docs-only small task
Budget: 3-7 files, 1-3 searches, no tests unless structure validation is required, 0 connector calls unless PR metadata is needed. Review the changed doc, nearby README, and acceptance checklist only.

### One-module medium task
Budget: 8-15 files, 4-8 searches, 1-3 targeted test runs, 1-2 connector calls. Read the module, relevant tests, interfaces, and docs. Avoid adjacent refactors unless required.

### Large task requiring planning
Do not execute directly. Create a planning packet that breaks the work into smaller phases. No full-repo scan or full suite until targeted exploration shows it is necessary.

## Stop Conditions
Stop when the file/search/test/connector budget is exceeded, target files are unclear, large-task scope appears, auth or approval fails, tests fail repeatedly without new evidence, full-repo search is requested too early, or unrelated cleanup is proposed.

## Non-Goals
No code implementation. No schema validator. No Python module. No Scheduler integration. No autonomous writes. No vector DB. No embeddings. No REST API. No dashboard. No daemon. No Phase 4 adapter-contract work.