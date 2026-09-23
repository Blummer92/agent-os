# Agent OS Notion Curriculum Preflight

This package implements the CW6A report-only preflight from issue #799. It
checks caller-supplied evidence describing a possible Notion teacher-planning
target and returns a deterministic bounded report.

## Boundary

The package is pure local. It does not:

- access Notion or the Navigation Index;
- import a Notion SDK, Google API package, Drive package, connector, or Workflow
  Scheduler adapter;
- read files, inspect the environment, load credentials, call subprocesses, or
  use the network;
- create or update databases, data sources, properties, relations, views, or
  records;
- grant write, execution, production, publication, readiness, approval, or
  classroom-use authority.

Every report records `live_access_performed=false`,
`side_effects_performed=false`, `write_authorized=false`,
`production_authorized=false`, and `publication_authorized=false`.

## Public API

```python
from scripts.agent_os_notion_curriculum_preflight import (
    evaluate_notion_curriculum_preflight,
    serialize_preflight_report,
)

report = evaluate_notion_curriculum_preflight(
    supplied_evidence,
    evaluated_at="2026-07-30T18:00:00Z",
)
serialized = serialize_preflight_report(report)
```

`evaluated_at` is supplied by the caller. The package does not read the system
clock. Evidence expires 24 hours after its supplied `verified_at` timestamp.

## Statuses

- `ready-for-local-draft-implementation`
- `blocked`
- `manual-review-required`
- `invalid`

A ready result means only that the supplied evidence is internally compatible
with a local draft implementation. It is not live-target verification and does
not authorize a connected read or write.

## Validation

```bash
PYTHONPATH=src:. python -m pytest tests/agent_os_notion_curriculum_preflight/test_core.py -q
PYTHONPATH=src:. python -m pytest \
  tests/test_instructional_workflow_handoff.py \
  tests/test_material_requirement_contract.py \
  tests/test_artifact_manifest_contract.py \
  tests/test_instructional_artifact_reuse_planner.py \
  tests/test_instructional_workflow_contract_integration.py \
  tests/agent_os_notion_curriculum_preflight/test_core.py \
  -q
python -m compileall -q scripts/agent_os_notion_curriculum_preflight
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

## Rollback

Revert or remove this package and its focused tests. No external cleanup is
required because the implementation performs no connected or external action.
