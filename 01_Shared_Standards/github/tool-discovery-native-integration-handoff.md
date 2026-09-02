# Tool Discovery Native Integration Handoff

## Purpose

This handoff freezes the remaining #1608 integration requirement after repository conformance landed. It is not a second continuation policy.

## Required native behavior

When an authorized finite Agent OS mission is unfinished and tool/schema discovery succeeds, discovery is an intermediate state. The execution interface must either invoke the next admitted operation in the same interaction or emit an explicit terminal blocker naming the unavailable capability owner and clearing condition.

The interface must not end the turn solely because tool descriptions or schemas were loaded.

## Canonical repository contracts consumed

- `01_Shared_Standards/github/tool-discovery-continuation.md`
- `02_Agent_Overlays/chatgpt-orchestrator.md`
- `07_Agent_Tests/chatgpt-orchestrator.tests.md`
- `tests/test_tool_discovery_continuation_policy.py`

## Live acceptance reproductions

1. #1573: `Complete the handoff` -> GitHub capability discovery succeeds -> next GitHub operation occurs without a new owner prompt.
2. PR #1582: exact failed run is known and workflow/job/log capability is available -> first diagnostic read occurs without a new owner prompt.
3. Unauthorized next operation -> explicit authorization blocker; no mutation.
4. Insufficient discovered capability -> consume #1237 reroute semantics or return the bounded capability blocker.

## Authority boundary

This handoff grants no implementation, merge, closure, workflow, protected-setting, credential, production, or external-write authority. It creates no mission database, background worker, retry framework, Scheduler, or second router.
