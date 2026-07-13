# AGENTS.md

## Purpose

This file is the ChatGPT entry point for Agent OS.

Agent OS is the governed knowledge base for agent standards, overlays,
templates, registry maps, examples, tests, and release notes.

## Source Of Truth

GitHub is the canonical source of truth for Agent OS.

ChatGPT is an execution interface, not the source of truth.

Notion, Google Drive, and ChatGPT memory are secondary working surfaces unless
a governance-approved source-of-truth change says otherwise.

## Start Here

Before doing Agent OS work, read only the files needed for the task:

1. `00_Governance/ownership-and-source-of-truth.md`
2. `00_Governance/write-authorization-policy.md`
3. `04_Registry/agent-inheritance-registry.md`
4. `04_Registry/responsibility-matrix.md`
5. the relevant file in `02_Agent_Overlays/`
6. any shared standards referenced by that overlay

## Agent Selection

Use agents for repeatable jobs, not every subject area.

Video production, photography, typography, color theory, graphic design, and AI
learning are content domains unless a governed change promotes one into a real
repeatable agent role.

## Access Rules

Default to read-only when authorization, target, or source of truth is unclear.

Only the GitHub Service Agent may write to GitHub.

All non-GitHub agents must create a GitHub Change Request handoff when repository
changes are needed.

Do not modify production systems, governed fields, sharing settings, source-of-
truth records, or irreversible artifacts without explicit approval.

## ChatGPT Workflow

1. Identify the task owner.
2. Read the owner overlay and referenced standards.
3. Confirm allowed and blocked write surfaces.
4. Use the smallest useful context packet.
5. Stop if authorization or source of truth is unclear.
6. Produce a handoff when another agent or GitHub write is needed.

## Required Final Report

Every implementation or review report must include:

- files changed
- tests run
- docs updated
- unresolved blockers
- handoff recommendations

## GitHub Handoffs

Use `03_Templates/prompts/github-change-request.md` for any repository change
requested by a non-GitHub agent.

The GitHub Service Agent decides the branch, commit, pull request, validation,
and final GitHub report.