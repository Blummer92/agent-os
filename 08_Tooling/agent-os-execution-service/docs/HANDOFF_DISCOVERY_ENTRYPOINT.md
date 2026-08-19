# Governed Handoff Discovery Host Entrypoint

Issue #1284 adds one fixed read-only host entrypoint:

`/usr/local/libexec/agent-os-handoff-discovery`

Public argv is exactly:

`--repository Blummer92/agent-os --issue-number <positive integer>`

The caller cannot provide the checkpoint-store root, a handoff ID, branch,
command, path, test instruction, shell text, or execution arguments.

The installed wrapper invokes the existing #1242
`discover_issue_handoff(...)` implementation against the host-composed
`AGENT_OS_CHECKPOINT_STORE_ROOT`.

Discovery is non-authorizing:

- `found` returns one already-existing immutable handoff;
- `not-found` returns no handoff;
- ambiguity, corruption, unavailable storage, or bound overflow fail closed;
- no Scheduler execution occurs;
- no GitHub write occurs;
- no new state store, router, queue, lease system, or execution authority exists.

A discovered handoff must still pass the existing #1218 reconstruction and
currentness checks before the existing #1238 governed-resume path can reach the
Scheduler.

Rollback removes only the fixed discovery wrapper and this repository binding.
