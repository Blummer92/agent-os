"""Execution-interface adapters that consume existing governed Agent OS seams.

This package holds the thin integration adapters that let a host execution
interface (Claude Code hooks today) resolve the governed Agent OS route before
generic GitHub publish tooling performs local ``git``/``gh`` prerequisite
checks. It owns no routing, authorization, transport, Scheduler, lease,
descriptor, or execution authority of its own.
"""
