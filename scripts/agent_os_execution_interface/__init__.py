"""Execution-interface adapters that consume existing governed Agent OS seams.

This package holds the thin integration adapters that let a host execution
interface (Claude Code hooks today, the ChatGPT Orchestrator Codespaces
transport) resolve the governed Agent OS route before generic GitHub publish
tooling performs local ``git``/``gh`` prerequisite checks. It owns no routing,
authorization, Scheduler, lease, descriptor, or execution authority of its
own. The Codespaces orchestrator transport (#3333) is a bounded command
conduit: it carries already-authorized lane work to the current qualified
Codespace and returns structured evidence, and it cannot grant GitHub write,
publication, merge, or any other authority.
"""
