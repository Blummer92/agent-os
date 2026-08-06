# Executor Route Decision Contract

## Purpose

Select the lowest-compute safe execution route from normalized Agent OS issue,
operating-mode, authorization, capability, runtime, and resume evidence.

## Routes

- `chatgpt_connector`: bounded GitHub reads and writes are sufficient.
- `governed_runner`: checkout, tests, build, generation, runtime inspection,
  local Git, or checkpointed execution is required.
- `external_fallback`: the external surface is proven available, and either the
  owner explicitly selected an external coding surface, or required runtime
  work exists and the governed runner is proven unavailable or insufficient,
  or the connector and the governed runner are both proven unavailable or
  insufficient. If the owner explicitly selects the external surface while it
  is not proven available, or a required capability is unknown, selection
  fails closed to `human_decision` instead.
- `human_decision`: authority, source evidence, required fields, excluded
  surfaces, or required capability evidence is ambiguous or unsafe.

## Contract

The selector is pure and deterministic. It consumes supplied normalized evidence,
returns one route with stable reason codes, and emits a compact handoff only when
ChatGPT cannot continue connector-native.

Route selection is capability routing only. It does not authorize implementation,
merge, issue closure, protected settings, workflows, credentials, production,
external writes, governed-field mutation, or irreversible actions.

Unknown, stale, conflicting, incomplete, or excluded-surface evidence fails
closed to `human_decision`. A prior executor route is preserved during resume only
when that route remains valid under the current evidence.

## Handoff

Non-connector decisions use a compact packet containing target, mode, goal,
route, bounded scope, validation, stop condition, final-report fields, and one
primary reason. The default packet is 8–12 lines and may not exceed 20 lines.

## Side Effects

None. The contract performs no network, GitHub, filesystem, subprocess,
environment, credential, Scheduler, lifecycle, or external-system operation.

## Version

1.0

## Changelog

- 1.0: initial deterministic executor-route contract for #907.
