# Classroom Workspace Google Drive adapter

Issue #2614 binds the pure DRIVE1/2/3 classroom workspace contracts to a provider-thin external Drive protocol. The repository module imports no Google SDK and performs no live connector call by itself.

## Existing Google Drive capability mapping

A future separately authorized ChatGPT/connector execution maps the protocol to the existing Google Drive capability:

- exact metadata read: `get_file_metadata(fileId=<exact Drive ID>)`;
- create one folder: `create_folder(name=<display name>, parent_folder=<exact parent Drive ID>)`;
- future rename/move only under a separate scope and authorization: `update_file(fileId=..., name=..., addParents=..., removeParents=...)`.

No new Google Drive MCP is required.

## Identity and currentness

Drive IDs are authoritative. Names are presentation metadata only. Provider metadata is normalized into the existing DRIVE2 `FolderMetadataReader` shape; the adapter does not create a second resolver contract.

Before a create, the exact parent folder is reread. A completed create requires an exact returned folder ID plus readback proving folder MIME type and exact parent. Ambiguous transport outcomes reconcile by the DRIVE3 operation identity before another create attempt. Display names alone never establish idempotency.

## Authorization

Repository implementation and tests are Tier 1 / `external_write: false`. Tests use injected fakes and zero credentials/network.

Any live Drive create is a separate Workspace write. Before it occurs, `workspace-write-authorization.md` requires the exact target, exact operation, current state, owner/approval, capability/credential boundary, and rollback/reconciliation evidence. Merge of this adapter does not authorize a live create, move, rename, delete, sharing change, or classroom publication.
