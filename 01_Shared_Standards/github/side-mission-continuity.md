# Primary and Side Mission Continuity

## Purpose

Prevent a bounded side conversation from silently replacing the exact active Agent OS issue.

## Contract

When issue X is the active primary mission and a separate bug/question Y is handled as a bounded side mission, X remains suspended as the primary mission unless the repository owner explicitly reprioritizes.

At the side mission's bounded terminal point:

1. reacquire live GitHub state for X and its canonical PR when one exists;
2. resume X in the same lineage if it remains open/eligible;
3. if Y blocks X, return to X with that blocker recorded;
4. if X became terminal while suspended, reconcile that live state and continue a broader mission only when prior owner intent authorizes it;
5. if more than one suspended primary mission is plausible, fail closed to ambiguity.

Explicit phrases such as `switch to`, `stop`, or `work on this instead` replace the suspended primary mission. A quick conceptual question, evidence-capture action, or duplicate-bug disposition does not.

## Composition

This contract is narrower than cross-chat mission continuity. It composes with the canonical owners for tool-discovery continuation, bug-evidence capture, and terminal reconciliation rather than redefining them.

## Boundaries

Side-mission continuity grants no new implementation, merge, closure, workflow, protected-setting, credential, production, or external-write authority. It creates no persistent task manager, hidden queue, autonomous worker, or second issue tracker.

## Regression fixture

`Work on #1543` -> log a separate workflow bug -> finish that bounded evidence capture -> reread and resume #1543 automatically unless the owner explicitly changed priorities.

## Version

0.1.0
