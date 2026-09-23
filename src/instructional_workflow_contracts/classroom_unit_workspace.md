# Classroom Unit Workspace contract

`classroom-unit-workspace-v1` is the pure, non-authorizing contract for mapping one canonical course/unit identity to semantic Google Drive folder roles.

## Identity

Google Drive folder IDs are external identity. Human folder names are display metadata and may change without changing `workspace_id`. The workspace ID is derived only from the supplied canonical course and unit references.

Supported semantic roles are `unit-root`, `slides`, `student-materials`, `teacher-models`, `visual-assets`, `assessment`, and `teacher-reference`. Child roles may be absent and created lazily by later, separately governed work.

A binding may be `resolved`, `unverified`, `stale`, `missing`, or `ambiguous`. `resolved` requires bounded verification evidence; cached IDs may remain `unverified` or `stale` without being promoted to currentness. Ambiguous bindings do not claim an exact Drive folder ID and require bounded review.

## Boundaries

The contract performs no Drive or Notion calls. It does not create, move, rename, delete, share, or write files/folders. It grants no execution, external-write, approval, classroom-readiness, publication, or production authority.

ArtifactManifest continues to own artifact/file identity. Visual Asset Library and its existing identity contracts continue to own reusable visual identity. Navigation Registry, when used by later work, remains a non-authoritative locator/cache whose records require current live verification before external operations.

No Google Drive MCP or connector implementation is introduced here. A later read-only Workspace Resolver can consume this contract to verify exact role-folder IDs, and later separately authorized operations can use those verified IDs with the existing Google Drive capability.
