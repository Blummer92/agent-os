"""Deterministic, non-authorizing pre-baked environment identity contract."""

from .identity import (
    PrebakedEnvironmentIdentity,
    StableDependencyInput,
    admit_prebaked_environment,
    build_prebaked_environment_identity,
)

__all__ = [
    "PrebakedEnvironmentIdentity",
    "StableDependencyInput",
    "admit_prebaked_environment",
    "build_prebaked_environment_identity",
]
