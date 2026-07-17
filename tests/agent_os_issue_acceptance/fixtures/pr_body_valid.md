## Linked Issue

Closes #164

## Summary

Adds the reusable IA2 checker.

## Files Changed

- scripts/agent_os_issue_acceptance/
- tests/agent_os_issue_acceptance/

## Tests Run

- python -m pytest tests/agent_os_issue_acceptance
- ./scripts/validate-all.sh

## Docs Updated

- scripts/agent_os_issue_acceptance/README.md

## Unresolved Blockers

- none

## Handoff Recommendations

- stage workflow integration after local checker validation

## Remaining Risks

- workflow posting is not implemented in v1
