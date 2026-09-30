"""Bounded production-host entrypoint for PPUX prompt projection (#2673).

Registers the fixed ``ppux-picture-perfect-prompt-projection`` operation
promised by the #2525 transport contract: given an exact repository
branch/SHA and one immutable picture-perfect-prompt-projection-input-v1
identity, it invokes only ``src/promptProjectionEntrypoint.ts`` /
``projectTutorialPromptCards(...)`` under the qualified Node 22 runtime and
emits the structured picture-perfect-prompt-projection-result-v1 evidence as
a single framed JSON envelope.

Fail-closed boundaries (mirroring the contract's finite reason vocabulary):
- the branch is cloned and the remote branch head must equal the pinned SHA
  before checkout; HEAD is re-verified after checkout (same discipline as the
  dev-validation host runner);
- an unresolved input identity emits a bounded ``projection-input-unresolved``
  blocker; Tutorial 0 fixtures or manually authored prompts never substitute
  for the requested input identity (canonical input retrieval stays open in
  #2675, which is why resolution is a separate bounded seam below);
- diagnostics are emitted separately from the canonical projection JSON;
- an oversize canonical payload fails closed with
  ``projection-output-oversize`` instead of tail-truncated JSON;
- every authority field in every emitted envelope is always false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

PPUX_PROJECTION_SCHEMA_VERSION = "1.0"
PPUX_PROJECTION_OPERATION_ID = "ppux-picture-perfect-prompt-projection"
PROJECTION_RESULT_VERSION = "picture-perfect-prompt-projection-result-v1"
PROJECTION_INPUT_VERSION = "picture-perfect-prompt-projection-input-v1"
REPOSITORY = "Blummer92/agent-os"
REPO_URL = "https://github.com/Blummer92/agent-os.git"

PPUX_PACKAGE_DIR = "08_Tooling/instructional-materials-coach/picture-perfect-coach"
PROJECTION_BUILD_CONFIG = "vite.projection.config.ts"
PROJECTION_BUILD_OUTPUT = ".agent-os-projection-build/promptProjectionEntrypoint.js"

NODE = "/usr/local/libexec/agent-os-dev-validation-node"
NODE_MODULES = "/opt/agent-os/dev-validation-node-runtime/node_modules"
VITE_CLI = f"{NODE_MODULES}/vite/bin/vite.js"

MAX_PROJECTION_RESULT_BYTES = 256 * 1024
MAX_PROJECTION_CARDS = 200
MAX_DIAGNOSTIC_CHARS = 4096
NODE_TIMEOUT_SECONDS = 120

FRAME_START = "PPUX-PROJECTION-FRAME-START"
FRAME_END = "PPUX-PROJECTION-FRAME-END"

_BRANCH_RE = re.compile(r"^agent/(?!main$)[A-Za-z0-9._/-]{1,180}$", re.ASCII)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_INPUT_REF_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_REQUEST_ID_RE = re.compile(r"^ppux-projection-[A-Za-z0-9-]{1,64}$", re.ASCII)

#: Fixed, caller-independent ESM runner. The only module it imports is the
#: fixed projection entrypoint build output; the input arrives as a file path
#: argument so the input bytes themselves are never part of the runner text.
FIXED_NODE_RUNNER = """\
import fs from 'node:fs';
import { projectTutorialPromptCards, serializePromptProjectionResult } from './""" + PROJECTION_BUILD_OUTPUT + """';
const inputPath = process.argv[2];
const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
process.stdout.write(serializePromptProjectionResult(projectTutorialPromptCards(input)));
"""


@dataclass(frozen=True)
class PpuxProjectionIdentity:
    repository: str
    issue_number: int
    branch: str
    source_sha: str
    input_ref: str
    request_id: str
    operation_id: Literal["ppux-picture-perfect-prompt-projection"]


def _fail(message: str) -> ValueError:
    return ValueError(f"Invalid PPUX projection request: {message}")


def build_projection_identity(
    *,
    repository: str,
    issue_number: int,
    branch: str,
    source_sha: str,
    input_ref: str,
    request_id: str,
    operation_id: str,
) -> PpuxProjectionIdentity:
    """Validate the fixed projection request surface; raise on any deviation."""
    if repository != REPOSITORY:
        raise _fail(f"repository must be {REPOSITORY!r}")
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number <= 0:
        raise _fail("issue_number must be a positive integer")
    if not isinstance(branch, str) or not _BRANCH_RE.fullmatch(branch):
        raise _fail("branch must be an agent/* development branch")
    if branch in {"agent/", "agent/main"} or ".." in branch or "//" in branch:
        raise _fail("branch must be an agent/* development branch")
    if branch.endswith("/") or branch.endswith("."):
        raise _fail("branch must be an agent/* development branch")
    if not isinstance(source_sha, str) or not _SHA_RE.fullmatch(source_sha):
        raise _fail("source_sha must be a 40-character lowercase hex SHA")
    if not isinstance(input_ref, str) or not _INPUT_REF_RE.fullmatch(input_ref):
        raise _fail("input_ref must be a 64-character lowercase hex content identity")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise _fail("request_id must match ppux-projection-[A-Za-z0-9-]{1,64}")
    if operation_id != PPUX_PROJECTION_OPERATION_ID:
        raise _fail(f"operation_id must be {PPUX_PROJECTION_OPERATION_ID!r}")
    return PpuxProjectionIdentity(
        repository=repository,
        issue_number=issue_number,
        branch=branch,
        source_sha=source_sha,
        input_ref=input_ref,
        request_id=request_id,
        operation_id=PPUX_PROJECTION_OPERATION_ID,
    )


def resolve_projection_input(input_ref: str) -> bytes | None:
    """Resolve one content-addressed projection input.

    Bounded seam: there is currently no approved retrieval backend for
    arbitrary ``picture-perfect-prompt-projection-input-v1`` identities
    (canonical publication/retrieval is tracked in #2675), so this returns
    ``None`` and the caller fails closed with ``projection-input-unresolved``.
    When #2675 lands, its retrieval binds here; the ``input_ref`` identity
    check in :func:`execute_ppux_projection` guarantees whatever returns is
    exactly the requested bytes. This function never returns fixture or
    manually authored input: Tutorial 0 is not a substitute input.
    """
    _ = input_ref
    return None


def _run(argv: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _tail(text: str, limit: int = MAX_DIAGNOSTIC_CHARS) -> str:
    return text[-limit:] if len(text) > limit else text


def _checkout_exact_branch_sha(identity: PpuxProjectionIdentity, workdir: Path) -> str | None:
    """Clone and pin to the exact branch/SHA; return the failure reason or None."""
    clone = _run(
        ["git", "clone", "--quiet", "--no-checkout", "--single-branch",
         "--branch", identity.branch, REPO_URL, "."],
        cwd=workdir,
        timeout=180,
    )
    if clone.returncode != 0:
        return "projection-branch-clone-failed"
    head = _run(
        ["git", "rev-parse", f"refs/remotes/origin/{identity.branch}"],
        cwd=workdir,
        timeout=30,
    )
    if head.returncode != 0 or head.stdout.strip() != identity.source_sha:
        return "projection-branch-head-mismatch"
    checkout = _run(
        ["git", "--no-replace-objects", "checkout", "--detach", "--quiet", identity.source_sha],
        cwd=workdir,
        timeout=180,
    )
    if checkout.returncode != 0:
        return "projection-checkout-failed"
    verify = _run(["git", "rev-parse", "HEAD"], cwd=workdir, timeout=30)
    if verify.returncode != 0 or verify.stdout.strip() != identity.source_sha:
        return "projection-checkout-head-mismatch"
    return None


def _node_runtime_ready() -> str | None:
    """Probe the qualified Node 22 runtime and the projection vite CLI."""
    node = Path(NODE)
    vite = Path(VITE_CLI)
    if not node.is_file() or not vite.is_file():
        return "projection-runtime-unavailable"
    probe = subprocess.run(
        [str(node), "--version"], capture_output=True, text=True, timeout=30
    )
    if probe.returncode != 0 or not probe.stdout.strip().startswith("v22."):
        return "projection-runtime-unavailable"
    return None


@dataclass
class PpuxProjectionOutcome:
    status: Literal["success", "blocked", "needs-decision"]
    reason_codes: list[str]
    projection_result: dict[str, Any] | None
    diagnostics: dict[str, Any]


def execute_ppux_projection(
    identity: PpuxProjectionIdentity,
    *,
    resolve_input: Callable[[str], bytes | None] = resolve_projection_input,
    node_runner_text: str = FIXED_NODE_RUNNER,
) -> PpuxProjectionOutcome:
    """Run the fixed projection once; never raises on projection-domain failures."""
    diagnostics: dict[str, Any] = {}
    cleanup_complete = False
    try:
        workdir = Path(tempfile.mkdtemp(prefix="ppux-projection-"))
        try:
            checkout_failure = _checkout_exact_branch_sha(identity, workdir)
            if checkout_failure is not None:
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=[checkout_failure],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            input_bytes = resolve_input(identity.input_ref)
            if input_bytes is None:
                return PpuxProjectionOutcome(
                    status="blocked",
                    reason_codes=["projection-input-unresolved"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            if hashlib.sha256(input_bytes).hexdigest() != identity.input_ref:
                return PpuxProjectionOutcome(
                    status="blocked",
                    reason_codes=["projection-input-identity-mismatch"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            try:
                input_doc = json.loads(input_bytes.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return PpuxProjectionOutcome(
                    status="blocked",
                    reason_codes=["projection-input-invalid"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            if not isinstance(input_doc, dict) or input_doc.get("formatVersion") != PROJECTION_INPUT_VERSION:
                return PpuxProjectionOutcome(
                    status="blocked",
                    reason_codes=["projection-input-invalid"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            runtime_failure = _node_runtime_ready()
            if runtime_failure is not None:
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=[runtime_failure],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            package_dir = workdir / PPUX_PACKAGE_DIR
            build = _run(
                [NODE, VITE_CLI, "build", "--config", PROJECTION_BUILD_CONFIG],
                cwd=package_dir,
                timeout=NODE_TIMEOUT_SECONDS,
            )
            diagnostics["build_stdout_tail"] = _tail(build.stdout)
            diagnostics["build_stderr_tail"] = _tail(build.stderr)
            build_output = package_dir / PROJECTION_BUILD_OUTPUT
            if build.returncode != 0 or not build_output.is_file():
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=["projection-build-failed"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            input_path = workdir / "projection-input.json"
            runner_path = workdir / "run-projection.mjs"
            input_path.write_bytes(input_bytes)
            runner_path.write_text(node_runner_text, encoding="utf-8")
            invoke = _run(
                [NODE, str(runner_path), str(input_path)],
                cwd=package_dir,
                timeout=NODE_TIMEOUT_SECONDS,
            )
            diagnostics["invoke_stdout_tail"] = _tail(invoke.stdout)
            diagnostics["invoke_stderr_tail"] = _tail(invoke.stderr)
            diagnostics["invoke_returncode"] = invoke.returncode
            if invoke.returncode != 0:
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=["projection-invocation-failed"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            raw = invoke.stdout.encode("utf-8")
            if len(raw) > MAX_PROJECTION_RESULT_BYTES:
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=["projection-output-oversize"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            try:
                result_doc = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=["projection-result-invalid"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            if not isinstance(result_doc, dict) or result_doc.get("formatVersion") != PROJECTION_RESULT_VERSION:
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=["projection-result-invalid"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            if result_doc.get("status") not in {"valid", "blocked"}:
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=["projection-result-invalid"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            package = result_doc.get("package")
            if package is not None:
                cards = package.get("cards") if isinstance(package, dict) else None
                if isinstance(cards, list) and len(cards) > MAX_PROJECTION_CARDS:
                    return PpuxProjectionOutcome(
                        status="needs-decision",
                        reason_codes=["projection-output-oversize"],
                        projection_result=None,
                        diagnostics=diagnostics,
                    )
                for authority_field in ("executionAuthorized", "externalWriteAuthorized", "productionAuthorized"):
                    if isinstance(package, dict) and package.get(authority_field) is not False:
                        return PpuxProjectionOutcome(
                            status="needs-decision",
                            reason_codes=["projection-authority-violation"],
                            projection_result=None,
                            diagnostics=diagnostics,
                        )
            if not isinstance(result_doc.get("blockers"), list):
                return PpuxProjectionOutcome(
                    status="needs-decision",
                    reason_codes=["projection-result-invalid"],
                    projection_result=None,
                    diagnostics=diagnostics,
                )
            return PpuxProjectionOutcome(
                status="success",
                reason_codes=["projection-result-ready" if result_doc.get("status") == "valid" else "projection-result-blocked"],
                projection_result=result_doc,
                diagnostics=diagnostics,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            cleanup_complete = True
    except (OSError, subprocess.SubprocessError) as exc:
        diagnostics["host_error"] = _tail(f"{type(exc).__name__}: {exc}")
        return PpuxProjectionOutcome(
            status="needs-decision",
            reason_codes=["projection-host-error"],
            projection_result=None,
            diagnostics=diagnostics,
        )
    finally:
        diagnostics["cleanup_complete"] = cleanup_complete


def build_projection_envelope(
    identity: PpuxProjectionIdentity, outcome: PpuxProjectionOutcome
) -> dict[str, Any]:
    projection_json = (
        json.dumps(outcome.projection_result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if outcome.projection_result is not None
        else None
    )
    return {
        "schema_version": PPUX_PROJECTION_SCHEMA_VERSION,
        "operation_id": PPUX_PROJECTION_OPERATION_ID,
        "status": outcome.status,
        "reason_codes": outcome.reason_codes,
        "repository": identity.repository,
        "issue_number": identity.issue_number,
        "branch": identity.branch,
        "tested_sha": identity.source_sha,
        "input_ref": identity.input_ref,
        "request_id": identity.request_id,
        "projection_result": outcome.projection_result,
        "projection_result_sha256": (
            hashlib.sha256(projection_json).hexdigest() if projection_json is not None else None
        ),
        "diagnostics": outcome.diagnostics,
        "cleanup_complete": outcome.diagnostics.get("cleanup_complete", False),
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }


def emit_envelope(envelope: dict[str, Any]) -> None:
    print(FRAME_START)
    print(json.dumps(envelope, sort_keys=True))
    print(FRAME_END)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fixed PPUX prompt-projection host entrypoint")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--input-ref", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--operation-id", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        identity = build_projection_identity(
            repository=args.repository,
            issue_number=args.issue_number,
            branch=args.branch,
            source_sha=args.source_sha,
            input_ref=args.input_ref,
            request_id=args.request_id,
            operation_id=args.operation_id,
        )
    except ValueError as exc:
        emit_envelope(
            {
                "schema_version": PPUX_PROJECTION_SCHEMA_VERSION,
                "operation_id": PPUX_PROJECTION_OPERATION_ID,
                "status": "needs-decision",
                "reason_codes": ["projection-request-invalid"],
                "diagnostics": {"validation_error": str(exc), "cleanup_complete": False},
                "cleanup_complete": False,
                "workspace_side_effects_performed": False,
                "external_side_effects_performed": False,
                "production_state_mutated": False,
                "execution_authorized": False,
                "scheduler_invoked": False,
                "publication_invoked": False,
                "merge_authorized": False,
            }
        )
        return 2
    outcome = execute_ppux_projection(identity)
    emit_envelope(build_projection_envelope(identity, outcome))
    return 0 if outcome.status == "success" else 3


if __name__ == "__main__":
    sys.exit(main())
