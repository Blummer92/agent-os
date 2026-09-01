# Side-Mission Continuity Conformance

## Purpose

Prevent a bounded side conversation from silently replacing the exact active Agent OS issue or pull-request lineage.

This is a ChatGPT execution-interface conformance contract. It composes existing same-lineage continuation, Safe Implementation Lane authorization, #1524 terminal reconciliation, #1608 tool-discovery continuation, #1647 bug-evidence capture, and #1648 broader cross-chat mission continuity. It does not create a task manager, queue, hidden mission database, second issue tracker, background worker, Scheduler, or authorization model.

## Canonical invariant

```text
active primary issue/PR lineage
+ bounded side mission
+ no explicit reprioritization
-> preserve primary lineage
-> finish or terminally classify side mission
-> reacquire live GitHub state for primary lineage
-> resume primary lineage
```

A side conversation is not, by itself, a mission switch.

## Primary and side mission roles

The currently authorized exact issue/PR lineage remains the **primary mission** while a temporary question, bug investigation, evidence-capture action, or duplicate-routing action is handled as a **side mission**.

A side mission is bounded by the reason it interrupted the primary mission. Reaching its bounded terminal result does not complete the primary mission and does not replace its authorization, branch, PR, issue identity, or lifecycle state.

Do not create persistent repository runtime state merely to remember this distinction. Use the active conversation/project context and existing canonical lineage evidence, then verify GitHub before resumption.

## Required return transition

After the side mission reaches a bounded terminal point, do exactly one of the following:

1. reacquire the exact suspended issue and canonical PR, when one exists, from live GitHub state and resume the same primary lineage;
2. return to that primary lineage with an explicit blocker when the side mission proved it blocked;
3. honor an explicit user reprioritization that cancels or replaces the primary mission; or
4. fail closed with ambiguity when more than one suspended primary lineage is genuinely plausible.

Do not silently select unrelated work. Do not require the repository owner to restate an unambiguously recoverable primary issue solely because a bounded side conversation occurred.

## Live-state reacquisition

Before resumption, conversation memory is noncanonical. Reacquire recoverable live GitHub evidence for:

- exact issue number and open/closed state;
- canonical PR identity when one exists;
- branch and current head when recoverable;
- current lifecycle/checkpoint state needed for the next admitted operation; and
- blockers discovered by the side mission.

If the primary issue or PR became terminal during the side conversation, reconcile that live state before deciding whether any broader mission may continue. Issue completion never implies broader mission completion unless the broader mission is also terminal under its governing contract.

## Explicit reprioritization

A clear instruction such as `switch to`, `stop`, `work on this instead`, or equivalent canonical request evidence replaces or cancels the prior primary mission as directed. Do not automatically return after an intentional mission switch.

A quick conceptual question, bug report, evidence-capture request, or duplicate check does not count as reprioritization by itself.

## Multiple side missions

Several bounded side missions may occur in sequence. Preserve the original primary lineage through the side chain and resume it once after the chain reaches its bounded terminal point. Do not emit duplicate return handoffs or promote an intermediate side mission into the primary mission without explicit reprioritization.

## Blocking side missions

When a side bug or investigation proves a blocker for the primary issue, carry that blocker back to the exact primary lineage. The correct result is the primary issue with an explicit blocker and clearing condition, not silent abandonment or substitution of unrelated work.

## Authorization boundary

Continuity preserves only authority already applicable to each lineage. A side conversation never grants repository implementation, merge, issue closure, review-thread resolution, workflow/protected-setting mutation, credentials/IAM, production, external write, governed-field mutation, irreversible action, or another excluded surface.

Side-bug evidence capture under #1647 does not consume or widen implementation authorization for the suspended primary issue. Resuming the primary issue restores only its still-current authorization envelope after live-state verification.

## Ownership relationships

- #1649 owns exact active issue/PR continuity through bounded side conversations.
- #1648 owns broader mission continuity across handoffs and new chats.
- #1647 owns automatic confirmed-bug evidence capture/routing.
- #1608 owns continuation after successful tool/schema/capability discovery.
- #1524 owns truthful terminal reconciliation.
- Safe Implementation Lane remains authoritative for repository implementation continuation and authorization ceilings.

These contracts compose; this file does not duplicate their state machines or authority models.

## External enforcement boundary

Repository policy and fixtures can define and test this invariant, but they cannot force the native ChatGPT product loop to preserve conversational execution state. If repository conformance passes while the live interface still loses the suspended primary lineage, classify the remaining defect as execution-interface integration work rather than adding repository runtime persistence or an autonomous task engine.

## Version

0.1.0
