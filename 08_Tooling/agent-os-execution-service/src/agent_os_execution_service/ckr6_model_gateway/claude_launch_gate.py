"""Option A, scoped honestly: gate the EXISTING Claude Code worker-launch seam.

``build_claude_coding_worker_invocation`` only builds argv; it launches nothing.
This composes CKR6 admission in front of whatever launcher a host injects.
Scope is ``session-start-only``: a launched ``claude`` process makes its own
provider requests that this gate does NOT see. Full per-request mediation needs
that process to run under ``spawn_isolated_worker`` against a gateway-owned
provider endpoint, which no supported Claude CLI proxy path provides today.
The generic POSIX launcher is deliberately NOT modified.
"""
from __future__ import annotations

from typing import Any, Callable

from ..coding_worker_claude_adapter import ClaudeCodingWorkerInvocation
from .contract import InvocationOutcome, InvocationRequest, canonical_json, sha256_text
from .gateway import ModelGateway


def launch_binding_sha256(invocation: ClaudeCodingWorkerInvocation) -> str:
    native = invocation.native_invocation
    return sha256_text(canonical_json({
        "invocation_id": native.invocation_id, "executable": native.executable_path,
        "argv": list(native.argv), "cwd": native.working_directory}))


def gated_claude_launch(gateway: ModelGateway, request: InvocationRequest, invocation: ClaudeCodingWorkerInvocation,
                        launcher: Callable[[tuple[str, ...], str], Any], *, cancel: Any = None) -> InvocationOutcome:
    """Call ``launcher(argv, cwd)`` at most once, and only after a verified CKR6 admission
    bound to this exact argv. The native invocation id is the idempotency key."""
    native = invocation.native_invocation
    return gateway.gate_launch(
        request.with_(invocation_id=native.invocation_id, prompt=""),
        binding_sha256=launch_binding_sha256(invocation),
        launcher=lambda: launcher(native.argv, native.working_directory), cancel=cancel)
