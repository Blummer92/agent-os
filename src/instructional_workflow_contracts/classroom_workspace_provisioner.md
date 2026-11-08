# Classroom Workspace Provisioner

`classroom-workspace-provisioning-plan-v1` is the pure, deterministic planning boundary for CW-DRIVE3 / #2582.

It consumes a validated `classroom-unit-workspace-v1` record plus current `classroom-unit-workspace-resolution-v1` evidence and answers which requested semantic-role folders would need a future authorized create operation.

## Planning behavior

- Current exact-ID role folders become `no-op`.
- Intentionally missing roles may become `create-folder` plans beneath the exact currently resolved unit-root ID.
- Moved or ambiguous roles require manual review rather than replacement creation.
- Trashed, inaccessible, wrong-kind, or otherwise unsafe roles are blocked.
- An unhealthy unit root blocks every child create plan.

Operation identity derives from the workspace identity, semantic role, exact parent ID, and operation type. Display names are presentation metadata and are not identity or idempotency keys. An explicit display-name override can therefore change the plan fingerprint without changing the semantic operation identity.

## Dry-run versus execution

This module does not execute its plans. It imports no Google Drive or Notion client, uses no credentials, and performs no network access or mutation. Its authority projection is always false.

A future separately authorized Tier-2 adapter may consume a `create-folder` operation, revalidate its exact preconditions, perform the external create through the existing Google Drive capability, reconcile ambiguous outcomes before retry, and verify the resulting exact Drive folder ID by readback. That adapter is outside #2582.

The planner does not create a new Google Drive MCP, Navigation Registry writer, artifact registry, workflow engine, or background service.
