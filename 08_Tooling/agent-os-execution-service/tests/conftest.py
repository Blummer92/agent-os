"""Execution-service test bootstrap with fail-closed runtime parity checks."""
from __future__ import annotations

from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from runtime_dependency_preflight import RuntimeDependencyMismatch, validate_runtime_dependency

try:
    validate_runtime_dependency("mcp")
except RuntimeDependencyMismatch as exc:
    raise RuntimeError(
        f"{exc}. Use an isolated runtime installed from 08_Tooling/agent-os-execution-service/pyproject.toml before treating execution-service test failures as product-code evidence."
    ) from exc
