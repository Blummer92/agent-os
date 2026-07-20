# Classroom Artifact Google Drive Setup

## Purpose

Prepare an operator for a future authorized Scheduler-to-Instructional-Materials-
Coach Drive run without storing secrets or changing any external system.

This runbook is preparation evidence only. It does not authorize OAuth setup,
Google Drive access, folder creation, permission changes, or artifact generation.

## Required Configuration Categories

Provide these values at runtime through an approved private execution surface:

- Google Cloud project name and OAuth client type, not a private client identifier;
- authorized operator account;
- approved OAuth scopes limited to the required Drive operation;
- credential and token storage location outside the repository;
- approved destination folder identifier;
- source template identifier, when a template is used;
- expected output filename and artifact type;
- approval reference for the specific live run.

Never commit client secrets, tokens, private keys, account identifiers, private
folder IDs, or local environment files.

## Approved Destination Verification

Before a live run, a human operator must verify in Google Drive that:

1. the folder is the exact approved destination for the class or project;
2. the authenticated account has only the permissions needed for the action;
3. the folder owner and sharing state match the approved handoff;
4. the destination is not a template-master or source-material folder;
5. the runtime folder ID matches the operator-verified folder URL;
6. no readiness, approval, or source-of-truth decision is inferred from the ID.

Record the verified folder name, owner, access level, verification time, and
approval reference in the private execution handoff. Do not copy private IDs into
GitHub reports.

## Copy-Safe Artifact Rules

- Treat templates and source artifacts as read-only masters.
- Create a new file in the confirmed destination; never overwrite the master.
- Use a new output name that identifies the lesson, unit, and run date.
- Do not move, rename, share, archive, or delete source files.
- Stop if the destination and template resolve to the same folder or file.
- Preserve attribution and approved asset-use notes in the run evidence.

## Dry-Run Gate

A dry run must complete before any live write. It should report the intended
account class, destination description, template description, output name,
requested scopes, planned API action, and safety checks without authenticating or
writing to Drive.

A dry-run pass is evidence only. It does not authorize the live run.

## Live-Run Authorization

Immediately before execution, confirm:

- explicit approval for this action and destination;
- unchanged destination, template, scopes, and output specification;
- credentials are available through the approved private runtime;
- production gates and material-quality checks passed;
- the operation creates a copy rather than modifying a master;
- rollback and disablement steps are available.

Stop when any value differs from the approved handoff.

## Verification, Disablement, And Rollback

After an authorized run, verify the new artifact exists only in the approved
folder, opens successfully, uses the intended source, and has no unintended
sharing changes. Record the generated link and sanitized evidence in the final
report.

To disable future runs, revoke or remove the runtime credential from the approved
private store and disable the scheduled execution path. Do not commit revoked
credentials or token details.

Rollback means deleting or moving only the newly generated artifact when the
operator has explicit permission. Never modify the template master, change folder
permissions, or remove unrelated files. Record the rollback action and result.

## Stop Conditions

Stop and request a governed decision if credentials, private IDs, account or
permission changes, folder creation, broader scopes, a second policy document,
files outside this runbook, or any live Google operation are required.

## Required Final Evidence

Report files changed, tests run, documentation updated, unresolved blockers,
handoff recommendations, remaining risks, and confirmation that no OAuth or Drive
operation occurred while producing this runbook.
