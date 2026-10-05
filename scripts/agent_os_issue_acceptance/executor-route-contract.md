# Executor Route Decision Contract

## Purpose

Select the lowest-compute safe execution surface from normalized Agent OS
issue, operating-mode, authorization, capability, runtime, and resume
evidence. The canonical implementation is `select_executor_route` in
`08_Tooling/agent-os-execution-service/src/agent_os_execution_service/executor_routing.py`
(#918). This contract describes its vocabulary — and only that vocabulary.

## Routes

- `chatgpt-connector-native`: no runtime capabilities are required; bounded
  connector-native work is sufficient.
- `chatgpt-governed-runner`: required capabilities exist and the governed
  runner is available with every required capability.
- `external-coding-agent-fallback`: required runtime work exists, the governed
  runner cannot satisfy it, and the external surface is available, explicitly
  permitted, and capable of every required capability.
- `human-decision-required`: authority, ownership, source of truth, target,
  scope, or required capability evidence is ambiguous; evidence is stale or
  contradictory; the mutation is irreversible or uncertain; or no approved
  route is capable.

## Contract

The selector is pure and deterministic. It consumes supplied normalized
evidence and returns one route with stable, finite reason codes.

Route selection is capability routing only. It does not select work, widen
authority, authorize implementation, merge, issue closure, protected
settings, workflows, credentials, production, external writes,
governed-field mutation, or irreversible actions. (ADR-8.)

Ambiguous, stale, contradictory, or excluded-surface evidence fails closed
to `human-decision-required`. A prior executor route is preserved during
resume only when that route remains capable under the current evidence
(`prior-route-preserved`); otherwise selection proceeds fresh and records
`prior-route-not-available`.

## Handoff

Non-connector decisions use a compact packet containing target, mode, goal,
route, bounded scope, validation, stop condition, final-report fields, and
one primary reason. The default packet is 8–12 lines and may not exceed
20 lines.

## Side Effects

None. The contract performs no network, GitHub, filesystem, subprocess,
environment, credential, Scheduler, lifecycle, or external-system operation.

## Version

2.0

## Changelog

- 2.0: Decision 1 consolidation — canonical vocabulary is #918
  (`select_executor_route`); the #907 `evaluate_executor_route`
  vocabulary is retired. Prior-route preservation migrated in as
  `prior_route_or_none` with `prior-route-preserved` /
  `prior-route-not-available` reason codes.
- 1.0: initial deterministic executor-route contract for #907.
