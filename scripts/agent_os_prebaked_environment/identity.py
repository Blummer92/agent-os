from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from scripts.agent_os_execution_capabilities.dependencies import RequiredEnvironmentSpec

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")


def _exact_text(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise TypeError(f"{name} must be non-empty NUL-free exact text")
    return value


def _sha256(value: object, name: str) -> str:
    text = _exact_text(value, name)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identifier(value: object, name: str) -> str:
    text = _exact_text(value, name)
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{name} contains unsupported characters")
    return text


def _content_id(prefix: str, payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    digest = hashlib.sha256(prefix.encode() + b"\x00" + canonical).hexdigest()
    return f"{prefix}:{digest}"


@dataclass(frozen=True, slots=True, kw_only=True)
class StableDependencyInput:
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        path = _exact_text(self.relative_path, "relative_path")
        if path.startswith("/") or ".." in path.split("/") or "\\" in path:
            raise ValueError("relative_path must be repository-relative POSIX text")
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))


@dataclass(frozen=True, slots=True, kw_only=True)
class PrebakedEnvironmentIdentity:
    repository_identity: str
    required_environment_id: str
    runtime_version: str
    package_manager_version: str
    approved_source_identity: str
    build_definition_sha256: str
    stable_dependency_inputs: tuple[StableDependencyInput, ...]
    environment_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "repository_identity",
            "required_environment_id",
            "runtime_version",
            "package_manager_version",
            "approved_source_identity",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self, "build_definition_sha256", _sha256(self.build_definition_sha256, "build_definition_sha256")
        )
        inputs = tuple(self.stable_dependency_inputs)
        if any(type(item) is not StableDependencyInput for item in inputs):
            raise TypeError("stable_dependency_inputs must contain exact StableDependencyInput values")
        if tuple(sorted(inputs, key=lambda item: item.relative_path)) != inputs:
            raise ValueError("stable_dependency_inputs must be sorted by relative_path")
        if len({item.relative_path for item in inputs}) != len(inputs):
            raise ValueError("stable_dependency_inputs paths must be unique")
        expected = _content_id("prebaked-environment", _identity_payload(self))
        if self.environment_id and self.environment_id != expected:
            raise ValueError("environment_id does not match identity content")
        object.__setattr__(self, "environment_id", expected)


def _identity_payload(identity: PrebakedEnvironmentIdentity) -> dict[str, object]:
    return {
        "repository_identity": identity.repository_identity,
        "required_environment_id": identity.required_environment_id,
        "runtime_version": identity.runtime_version,
        "package_manager_version": identity.package_manager_version,
        "approved_source_identity": identity.approved_source_identity,
        "build_definition_sha256": identity.build_definition_sha256,
        "stable_dependency_inputs": [
            {"relative_path": item.relative_path, "sha256": item.sha256}
            for item in identity.stable_dependency_inputs
        ],
    }


def build_prebaked_environment_identity(
    *,
    spec: RequiredEnvironmentSpec,
    repository_identity: str,
    runtime_version: str,
    package_manager_version: str,
    build_definition_sha256: str,
    stable_dependency_inputs: tuple[StableDependencyInput, ...],
) -> PrebakedEnvironmentIdentity:
    """Bind immutable image inputs to the existing canonical environment spec."""
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    return PrebakedEnvironmentIdentity(
        repository_identity=repository_identity,
        required_environment_id=spec.required_environment_id,
        runtime_version=runtime_version,
        package_manager_version=package_manager_version,
        approved_source_identity=spec.approved_source_identity,
        build_definition_sha256=build_definition_sha256,
        stable_dependency_inputs=stable_dependency_inputs,
    )


def admit_prebaked_environment(
    *,
    spec: RequiredEnvironmentSpec,
    selected: PrebakedEnvironmentIdentity,
    expected_repository_identity: str,
) -> bool:
    """Fail closed unless the selected immutable image matches current truth."""
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    if type(selected) is not PrebakedEnvironmentIdentity:
        raise TypeError("selected must be exact PrebakedEnvironmentIdentity")
    return (
        selected.repository_identity == expected_repository_identity
        and selected.required_environment_id == spec.required_environment_id
        and selected.approved_source_identity == spec.approved_source_identity
    )
