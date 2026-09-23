"""Content-addressed initial RequiredEnvironmentSpec binding for #1972.

The evidence lives in the existing Option-C pre-publication evidence namespace and
binds one already-persisted candidate-provenance identity to one exact existing
RequiredEnvironmentSpec. Construction is deterministic from repository-owned
artifacts for the two #1185/#1197 ecosystems already supported by Agent OS.
It creates no runtime-readiness or execution authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyEcosystem,
    DependencyInstallMode,
    LocalProjectRequirement,
    RequiredEnvironmentSpec,
    reconstruct_required_environment_spec,
    required_environment_spec_payload,
)
from workflow_scheduler.execution.concrete_runtime_adapters import _local_project_sha256
from workflow_scheduler.execution.dependency_preparation import (
    validate_npm_lock_source_forms,
    validate_python_requirements_source_forms,
)

from .candidate_approval_provenance import STORE_NAMESPACE

SCHEMA_NAME = "agent-os-candidate-environment-provenance"
SCHEMA_VERSION = "1.0"
MAX_RECORDS = 4096
MAX_BYTES = 262_144
PYTHON_MANIFEST = "requirements-dev.txt"
PYTHON_LOCAL_PROJECTS = (
    "src",
    "08_Tooling/agent-memory-context-manager",
    "08_Tooling/reusable-capability-registry",
    "08_Tooling/workflow-scheduler",
    "08_Tooling/visual-asset-intake",
)
PPUX_PACKAGE_ROOT = "08_Tooling/instructional-materials-coach/picture-perfect-coach"
PPUX_PROFILE_COMMAND = (
    "python -m workflow_scheduler.governance.ppux_validation_runner"
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("dependency artifact is missing or unsafe")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(root: Path, relative_path: str) -> DependencyArtifactIdentity:
    return DependencyArtifactIdentity(relative_path=relative_path, sha256=_file_sha256(root / relative_path))


def _python_spec(root: Path, required_tests: tuple[str, ...]) -> RequiredEnvironmentSpec:
    manifest = _artifact(root, PYTHON_MANIFEST)
    projects: list[LocalProjectRequirement] = []
    # RequiredEnvironmentSpec requires local project requirements sorted by
    # relative path. Sorting here (rather than relying on the declaration order
    # of PYTHON_LOCAL_PROJECTS) keeps the constant readable and stops a later
    # entry from silently making every Python spec construction fail closed.
    for relative_path in sorted(PYTHON_LOCAL_PROJECTS):
        digest = _local_project_sha256(str(root / relative_path))
        if digest is None:
            raise ValueError("local project identity is unavailable")
        projects.append(LocalProjectRequirement(relative_path=relative_path, sha256=digest, editable=True))
    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=manifest,
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=required_tests,
        local_project_requirements=tuple(projects),
    )
    text = (root / PYTHON_MANIFEST).read_text(encoding="utf-8")
    if validate_python_requirements_source_forms(text, spec):
        raise ValueError("python dependency manifest is not represented by the canonical spec")
    return spec


def _node_spec(root: Path, required_tests: tuple[str, ...]) -> RequiredEnvironmentSpec:
    package_json_path = f"{PPUX_PACKAGE_ROOT}/package.json"
    lock_path = f"{PPUX_PACKAGE_ROOT}/package-lock.json"
    package_payload = json.loads((root / package_json_path).read_text(encoding="utf-8"))
    if type(package_payload) is not dict:
        raise ValueError("package.json must be an object")
    engines = package_payload.get("engines")
    runtime = engines.get("node") if type(engines) is dict else None
    if type(runtime) is not str or not runtime:
        raise ValueError("package.json must declare the canonical Node engine range")
    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.NODE_NPM,
        package_root=PPUX_PACKAGE_ROOT,
        runtime_requirement=runtime,
        dependency_manifest_identity=_artifact(root, package_json_path),
        lock_or_constraints_identity=_artifact(root, lock_path),
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="registry.npmjs.org",
        required_validation_command_ids=required_tests,
    )
    lock_payload = json.loads((root / lock_path).read_text(encoding="utf-8"))
    if validate_npm_lock_source_forms(lock_payload, spec):
        raise ValueError("npm lock sources are not represented by the canonical spec")
    return spec


def derive_initial_required_environment_spec(
    repository_root: Path | str, *, required_tests: tuple[str, ...]
) -> RequiredEnvironmentSpec:
    """Derive the existing #1185 model from the finite current validation lanes."""
    root = Path(repository_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("repository_root must be an existing absolute directory")
    if type(required_tests) is not tuple or not required_tests or any(type(item) is not str or not item for item in required_tests):
        raise TypeError("required_tests must be a non-empty exact tuple")
    if required_tests != tuple(sorted(set(required_tests))):
        raise ValueError("required_tests must be sorted and unique")
    if required_tests == (PPUX_PROFILE_COMMAND,):
        return _node_spec(root, required_tests)
    return _python_spec(root, required_tests)


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateEnvironmentProvenanceEvidence:
    candidate_provenance_id: str
    candidate_sha: str
    required_environment_spec: RequiredEnvironmentSpec
    evidence_id: str = ""
    execution_authorized: Literal[False] = field(default=False, init=False)
    runtime_ready: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.candidate_provenance_id) is not str or not self.candidate_provenance_id.startswith("pre-publication-evidence:"):
            raise ValueError("candidate_provenance_id is malformed")
        if type(self.candidate_sha) is not str or len(self.candidate_sha) != 40 or any(ch not in "0123456789abcdef" for ch in self.candidate_sha):
            raise ValueError("candidate_sha must be a lowercase 40-hex SHA")
        if type(self.required_environment_spec) is not RequiredEnvironmentSpec:
            raise TypeError("required_environment_spec must be exact RequiredEnvironmentSpec")
        expected = candidate_environment_provenance_id(self)
        if self.evidence_id and self.evidence_id != expected:
            raise ValueError("evidence_id does not match content")
        object.__setattr__(self, "evidence_id", expected)


def _payload(value: CandidateEnvironmentProvenanceEvidence, *, include_id: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "candidate_provenance_id": value.candidate_provenance_id,
        "candidate_sha": value.candidate_sha,
        "required_environment_spec": required_environment_spec_payload(value.required_environment_spec),
        "execution_authorized": False,
        "runtime_ready": False,
        "side_effects_performed": False,
    }
    if include_id:
        payload["evidence_id"] = value.evidence_id
    return payload


def candidate_environment_provenance_id(value: CandidateEnvironmentProvenanceEvidence) -> str:
    digest = hashlib.sha256(b"agent-os-candidate-environment-provenance:v1\0" + _canonical_bytes(_payload(value, include_id=False))).hexdigest()
    return f"pre-publication-evidence:{digest}"


def build_candidate_environment_provenance(
    *, candidate_provenance_id: str, candidate_sha: str, repository_root: Path | str, required_tests: tuple[str, ...]
) -> CandidateEnvironmentProvenanceEvidence:
    return CandidateEnvironmentProvenanceEvidence(
        candidate_provenance_id=candidate_provenance_id,
        candidate_sha=candidate_sha,
        required_environment_spec=derive_initial_required_environment_spec(repository_root, required_tests=required_tests),
    )


def serialize_candidate_environment_provenance(value: CandidateEnvironmentProvenanceEvidence) -> bytes:
    if type(value) is not CandidateEnvironmentProvenanceEvidence:
        raise TypeError("value must be exact CandidateEnvironmentProvenanceEvidence")
    encoded = _canonical_bytes(_payload(value, include_id=True))
    if len(encoded) > MAX_BYTES:
        raise ValueError("candidate environment provenance exceeds byte bound")
    return encoded


def reconstruct_candidate_environment_provenance(payload: object) -> CandidateEnvironmentProvenanceEvidence:
    if type(payload) is not dict:
        raise TypeError("payload must be an exact object")
    expected = {"schema_name","schema_version","candidate_provenance_id","candidate_sha","required_environment_spec","evidence_id","execution_authorized","runtime_ready","side_effects_performed"}
    if set(payload) != expected or payload["schema_name"] != SCHEMA_NAME or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("candidate environment provenance schema drift")
    if any(payload[name] is not False for name in ("execution_authorized","runtime_ready","side_effects_performed")):
        raise ValueError("candidate environment provenance cannot carry authority")
    value = CandidateEnvironmentProvenanceEvidence(
        candidate_provenance_id=payload["candidate_provenance_id"],
        candidate_sha=payload["candidate_sha"],
        required_environment_spec=reconstruct_required_environment_spec(payload["required_environment_spec"]),
        evidence_id=payload["evidence_id"],
    )
    if serialize_candidate_environment_provenance(value) != _canonical_bytes(payload):
        raise ValueError("candidate environment provenance is not canonical")
    return value


def append_candidate_environment_provenance(store_root: Path | str, value: CandidateEnvironmentProvenanceEvidence) -> str:
    root = Path(store_root)
    directory = root / STORE_NAMESPACE
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("evidence namespace may not be a symlink")
    if len(tuple(directory.glob("*.json"))) >= MAX_RECORDS:
        raise ValueError("evidence namespace exceeds bounded record count")
    path = directory / f"{value.evidence_id.split(':',1)[1]}.json"
    encoded = serialize_candidate_environment_provenance(value)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError("content-addressed evidence conflict")
        return value.evidence_id
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return value.evidence_id


def load_candidate_environment_provenance(store_root: Path | str, evidence_id: str) -> CandidateEnvironmentProvenanceEvidence:
    if type(evidence_id) is not str or not evidence_id.startswith("pre-publication-evidence:"):
        raise ValueError("evidence_id is malformed")
    path = Path(store_root) / STORE_NAMESPACE / f"{evidence_id.split(':',1)[1]}.json"
    return reconstruct_candidate_environment_provenance(json.loads(path.read_text(encoding="utf-8")))


__all__ = [
    "CandidateEnvironmentProvenanceEvidence",
    "append_candidate_environment_provenance",
    "build_candidate_environment_provenance",
    "derive_initial_required_environment_spec",
    "load_candidate_environment_provenance",
]
