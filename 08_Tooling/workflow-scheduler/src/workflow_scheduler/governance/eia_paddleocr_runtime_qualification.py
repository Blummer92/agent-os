"""Finite, synthetic-only EIA PaddleOCR runtime qualification for #1763.

This entrypoint inspects only the already-installed host runtime. It never
installs packages, downloads models, opens network connections, or consumes
caller-supplied paths/commands. Missing dependencies fail closed for #716.
"""
from __future__ import annotations

import importlib
import json
import platform
import sys
from dataclasses import dataclass, asdict
from typing import Literal

QUALIFICATION_ID = "eia-paddleocr-runtime-qualification"
_REQUIRED_MODULES = ("paddle", "paddleocr", "paddlex")


@dataclass(frozen=True, slots=True)
class QualificationResult:
    schema_version: str
    qualification_id: str
    status: Literal["ready", "blocked"]
    reason_codes: tuple[str, ...]
    python_version: str
    platform: str
    module_versions: tuple[tuple[str, str], ...]
    synthetic_only: Literal[True] = True
    network_used: Literal[False] = False
    installation_performed: Literal[False] = False
    model_download_performed: Literal[False] = False
    external_write_performed: Literal[False] = False
    execution_authorized: Literal[False] = False
    scheduler_invoked: Literal[False] = False
    production_authorized: Literal[False] = False
    classroom_data_authorized: Literal[False] = False


def qualify_runtime() -> QualificationResult:
    versions: list[tuple[str, str]] = []
    missing: list[str] = []
    for name in _REQUIRED_MODULES:
        try:
            module = importlib.import_module(name)
        except (ImportError, ModuleNotFoundError):
            missing.append(name)
            continue
        version = getattr(module, "__version__", None)
        versions.append((name, version if isinstance(version, str) and version else "unknown"))
    reasons = tuple(f"runtime-dependency-missing:{name}" for name in missing)
    return QualificationResult(
        schema_version="1.0",
        qualification_id=QUALIFICATION_ID,
        status="blocked" if missing else "ready",
        reason_codes=reasons if reasons else ("runtime-dependencies-present",),
        python_version=platform.python_version(),
        platform=f"{platform.system().lower()}-{platform.machine().lower()}",
        module_versions=tuple(versions),
    )


def main() -> int:
    result = qualify_runtime()
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0 if result.status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
