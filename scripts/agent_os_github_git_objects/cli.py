"""Closed-schema CLI for planning and separately confirmed Git-object publication."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .atomic_commit import execute_atomic_commit_from_blobs, prepare_atomic_commit_from_blobs
from .models import (
    AtomicCommitConfirmation,
    AtomicCommitRequest,
    AtomicCommitResult,
    GitTreeEntry,
)
from .transport import PyGithubGitObjectTransport

_REQUEST_KEYS = frozenset(
    {
        "repository",
        "branch",
        "expected_head_sha",
        "allowed_paths",
        "entries",
        "message",
        "invocation_id",
        "prior_fingerprints",
    }
)
_ENTRY_KEYS = frozenset({"path", "mode", "type", "sha"})
_CONFIRMATION_KEYS = frozenset(
    {
        "invocation_id",
        "operation_fingerprint",
        "repository",
        "branch",
        "expected_head_sha",
        "confirmed",
    }
)


def request_from_payload(payload: object) -> AtomicCommitRequest:
    mapping = _closed_mapping(payload, _REQUEST_KEYS, "manifest")
    entries_payload = mapping["entries"]
    if not isinstance(entries_payload, list):
        raise ValueError("manifest.entries must be a list")
    entries = tuple(
        GitTreeEntry(**_closed_mapping(item, _ENTRY_KEYS, "manifest entry"))
        for item in entries_payload
    )
    allowed_paths = mapping["allowed_paths"]
    prior_fingerprints = mapping["prior_fingerprints"]
    if not isinstance(allowed_paths, list) or not all(isinstance(item, str) for item in allowed_paths):
        raise ValueError("manifest.allowed_paths must be a list of strings")
    if not isinstance(prior_fingerprints, list) or not all(
        isinstance(item, str) for item in prior_fingerprints
    ):
        raise ValueError("manifest.prior_fingerprints must be a list of strings")
    return AtomicCommitRequest(
        repository=mapping["repository"],
        branch=mapping["branch"],
        expected_head_sha=mapping["expected_head_sha"],
        allowed_paths=tuple(allowed_paths),
        entries=entries,
        message=mapping["message"],
        invocation_id=mapping["invocation_id"],
        prior_fingerprints=tuple(prior_fingerprints),
    )


def confirmation_from_payload(payload: object) -> AtomicCommitConfirmation:
    mapping = _closed_mapping(payload, _CONFIRMATION_KEYS, "confirmation")
    return AtomicCommitConfirmation(**mapping)


def result_to_dict(result: AtomicCommitResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["reason"] = result.reason.value
    payload["mutation_state"] = result.mutation_state.value
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os-github-git-objects")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--manifest", required=True)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--manifest", required=True)
    execute.add_argument("--confirmation-file", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        request = request_from_payload(_read_json(Path(args.manifest)))
        transport = _transport_from_environment()
        plan, result = prepare_atomic_commit_from_blobs(request, transport)
        if args.command == "plan" or plan is None:
            print(json.dumps(result_to_dict(result), sort_keys=True, separators=(",", ":")))
            return 0 if plan is not None else 2
        confirmation = confirmation_from_payload(_read_json(Path(args.confirmation_file)))
        executed = execute_atomic_commit_from_blobs(plan, confirmation, transport)
        print(json.dumps(result_to_dict(executed), sort_keys=True, separators=(",", ":")))
        return 0 if executed.status.value == "ref-updated" else 3
    except Exception as error:
        diagnostic = _sanitize_diagnostic(str(error))
        print(f"error:{type(error).__name__}:{diagnostic[:512]}", file=sys.stderr)
        return 2


def _sanitize_diagnostic(value: str) -> str:
    value = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b", "[redacted]", value)
    value = re.sub(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b", "[redacted]", value)
    value = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", value)
    value = re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        value,
    )
    return value.replace("\x00", "")


def _transport_from_environment() -> PyGithubGitObjectTransport:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required for live transport")
    from github import Auth, Github

    return PyGithubGitObjectTransport(Github(auth=Auth.Token(token)))


def _read_json(path: Path) -> object:
    if not path.is_file():
        raise ValueError(f"JSON file does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _closed_mapping(value: object, expected: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    keys = set(value)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing:
        raise ValueError(f"{name} is missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"{name} has unsupported fields: {', '.join(extra)}")
    return dict(value)


if __name__ == "__main__":
    raise SystemExit(main())
