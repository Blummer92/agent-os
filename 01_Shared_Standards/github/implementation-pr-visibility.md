# Implementation PR Visibility

## Purpose

Prevent an implementation lifecycle from being reported complete while its canonical pull request is effectively invisible to the repository owner.

## Contract

When GitHub work creates, discovers, resumes, reviews, repairs, merges, or terminally reconciles a primary implementation PR, the execution interface must surface that PR before reporting the lifecycle complete.

The visible PR evidence must include, when available:

- PR number and concise purpose/title;
- lifecycle state: draft, open/ready, merged, or closed-unmerged;
- exact relevant head SHA;
- merge commit when merged.

If no PR exists where the implementation path normally requires one, say so explicitly. If multiple PRs plausibly own the implementation lineage, fail closed to lineage reconciliation rather than selecting one silently.

## Currentness

PR identity and state must be reacquired from GitHub before terminal reporting. Conversation memory is supporting context, not canonical state.

## Boundaries

Surfacing a PR is evidence presentation only. It grants no merge, issue-closure, review-resolution, protected-setting, production, credential, workflow, or external-write authority. This contract creates no second PR registry, dashboard, persistent mission store, or notification subsystem.

## Regression fixture

Issue #1627 with merged PR #1628 is the canonical reproduction: terminal implementation reporting must identify PR #1628 as the implementation artifact before saying the implementation lifecycle is complete.

## Version

0.1.0
