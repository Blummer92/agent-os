"""Finite dependency-artifact qualification for AOS-DEVVAL7 (#1783).

This module owns one closed EIA package set and target. It never accepts package,
index, platform, resolver-argument, environment, path, or network overrides from
the caller. Network use is limited to the separately authorized resolver step;
verification is explicitly offline and all workspace state is ephemeral.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence

PROFILE_ID = "eia-paddleocr-cp311-wheelhouse-qualification"
PACKAGES = ("paddleocr==3.7.0", "paddlepaddle==3.2.0", "paddlex==3.7.2")
TARGET_PYTHON = "3.11"
TARGET_PLATFORM = "manylinux2014_x86_64"
TARGET_IMPLEMENTATION = "cp"
TARGET_ABI = "cp311"
MAX_ARTIFACTS = 128
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_LOG_CHARS = 4096
RESOLVE_TIMEOUT_SECONDS = 300
VERIFY_TIMEOUT_SECONDS = 300
_WHEEL = re.compile(r"^(?P<name>.+)-(?P<version>[^-]+)-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>[^-]+)\.whl$", re.ASCII)


@dataclass(frozen=True, slots=True)
class Artifact:
    name: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    python_tag: str
    abi_tag: str
    platform_tag: str
    license_expression: str | None


@dataclass(frozen=True, slots=True)
class QualificationResult:
    status: Literal["ready", "blocked"]
    reason_codes: tuple[str, ...]
    artifacts: tuple[Artifact, ...]
    hash_lock: tuple[str, ...]
    resolver_network_used: bool
    offline_verification_passed: bool
    cleanup_complete: bool
    execution_authorized: Literal[False] = False
    host_mutation_authorized: Literal[False] = False
    scheduler_invoked: Literal[False] = False
    production_authorized: Literal[False] = False
    classroom_data_authorized: Literal[False] = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "profile_id": PROFILE_ID,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "target": {"python": TARGET_PYTHON, "platform": TARGET_PLATFORM, "implementation": TARGET_IMPLEMENTATION, "abi": TARGET_ABI},
            "packages": list(PACKAGES),
            "artifacts": [artifact.__dict__ for artifact in self.artifacts],
            "hash_lock": list(self.hash_lock),
            "resolver_network_used": self.resolver_network_used,
            "offline_verification_passed": self.offline_verification_passed,
            "cleanup_complete": self.cleanup_complete,
            "execution_authorized": False,
            "host_mutation_authorized": False,
            "scheduler_invoked": False,
            "production_authorized": False,
            "classroom_data_authorized": False,
        }


def resolver_argv(destination: Path) -> tuple[str, ...]:
    return (
        sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--dest", str(destination),
        "--python-version", TARGET_PYTHON.replace(".", ""), "--platform", TARGET_PLATFORM,
        "--implementation", TARGET_IMPLEMENTATION, "--abi", TARGET_ABI, *PACKAGES,
    )


def offline_verify_argv(wheelhouse: Path, target: Path, lock_path: Path) -> tuple[str, ...]:
    return (
        sys.executable, "-m", "pip", "install", "--no-index", "--find-links", str(wheelhouse),
        "--require-hashes", "--only-binary=:all:", "--target", str(target), "-r", str(lock_path),
    )


def _run(argv: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(tuple(argv), check=False, capture_output=True, text=True, timeout=timeout, env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})


def _license_from_wheel(path: Path) -> str | None:
    with zipfile.ZipFile(path) as archive:
        metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            return None
        text = archive.read(metadata[0]).decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("License-Expression:"):
            value = line.partition(":")[2].strip()
            return value or None
    for line in text.splitlines():
        if line.startswith("License:"):
            value = line.partition(":")[2].strip()
            return value or None
    return None


def inspect_wheelhouse(wheelhouse: Path) -> tuple[Artifact, ...]:
    paths = sorted(wheelhouse.iterdir(), key=lambda path: path.name.lower())
    if not paths or len(paths) > MAX_ARTIFACTS:
        raise ValueError("artifact-count-invalid")
    artifacts: list[Artifact] = []
    total = 0
    identities: set[tuple[str, str]] = set()
    for path in paths:
        if not path.is_file() or path.suffix != ".whl":
            raise ValueError("source-distribution-or-extra-artifact")
        size = path.stat().st_size
        total += size
        if size <= 0 or size > MAX_ARTIFACT_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("artifact-size-bound-exceeded")
        match = _WHEEL.fullmatch(path.name)
        if match is None:
            raise ValueError("wheel-filename-invalid")
        name = match.group("name").replace("_", "-").lower()
        version = match.group("version")
        identity = (name, version)
        if identity in identities or any(existing[0] == name and existing != identity for existing in identities):
            raise ValueError("artifact-identity-conflict")
        identities.add(identity)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts.append(Artifact(name=name, version=version, filename=path.name, sha256=digest, size_bytes=size, python_tag=match.group("python"), abi_tag=match.group("abi"), platform_tag=match.group("platform"), license_expression=_license_from_wheel(path)))
    return tuple(artifacts)


def hash_lock(artifacts: Sequence[Artifact]) -> tuple[str, ...]:
    if not artifacts:
        raise ValueError("artifact-lock-empty")
    return tuple(f"{artifact.name}=={artifact.version} --hash=sha256:{artifact.sha256}" for artifact in sorted(artifacts, key=lambda item: (item.name, item.version)))


def qualify(*, runner: Callable[[Sequence[str], int], subprocess.CompletedProcess[str]] | None = None) -> QualificationResult:
    execute = runner or (lambda argv, timeout: _run(argv, timeout=timeout))
    root = Path(tempfile.mkdtemp(prefix="agent-os-wheelhouse-"))
    wheelhouse = root / "wheelhouse"; wheelhouse.mkdir()
    target = root / "offline-target"; lock_path = root / "requirements.lock"
    artifacts: tuple[Artifact, ...] = (); lock: tuple[str, ...] = (); reasons: list[str] = []
    offline_ok = False; cleanup = False
    try:
        try:
            resolved = execute(resolver_argv(wheelhouse), RESOLVE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return QualificationResult("blocked", ("resolver-timeout",), (), (), True, False, False)
        if resolved.returncode != 0:
            return QualificationResult("blocked", ("resolver-download-failed",), (), (), True, False, False)
        try:
            artifacts = inspect_wheelhouse(wheelhouse); lock = hash_lock(artifacts)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return QualificationResult("blocked", (str(exc),), (), (), True, False, False)
        if any(artifact.license_expression is None for artifact in artifacts):
            reasons.append("license-metadata-incomplete")
        lock_path.write_text("\n".join(lock) + "\n", encoding="utf-8")
        try:
            verified = execute(offline_verify_argv(wheelhouse, target, lock_path), VERIFY_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return QualificationResult("blocked", ("offline-verification-timeout",), artifacts, lock, True, False, False)
        offline_ok = verified.returncode == 0
        if not offline_ok:
            reasons.append("offline-verification-failed")
        if not reasons:
            reasons.append("wheelhouse-qualified")
        return QualificationResult("ready" if reasons == ["wheelhouse-qualified"] else "blocked", tuple(reasons), artifacts, lock, True, offline_ok, False)
    finally:
        try:
            shutil.rmtree(root); cleanup = True
        except OSError:
            cleanup = False


def main() -> int:
    result = qualify()
    payload = result.to_dict()
    # qualify() returns before finally can rewrite the frozen result's cleanup flag;
    # CLI evidence therefore derives cleanup from absence of the workspace prefix.
    payload["cleanup_complete"] = not any(Path(tempfile.gettempdir()).glob("agent-os-wheelhouse-*"))
    if not payload["cleanup_complete"]:
        payload["status"] = "blocked"; payload["reason_codes"] = ["workspace-cleanup-failed"]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_LOG_CHARS * 8:
        print(json.dumps({"schema_version":"1.0","profile_id":PROFILE_ID,"status":"blocked","reason_codes":["evidence-size-bound-exceeded"],"execution_authorized":False,"host_mutation_authorized":False,"scheduler_invoked":False,"production_authorized":False,"classroom_data_authorized":False}, sort_keys=True))
        return 2
    print(encoded)
    return 0 if payload["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
