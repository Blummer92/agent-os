"""Bootstrap the RC6 runner while importing canonical interfaces from the frozen checkout.

This file is invoked by the manual workflow as a script rather than as ``-m`` so
it can establish the frozen import boundary before the runner package is loaded.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare_frozen_imports() -> Path:
    value = os.environ.get("RC6_FROZEN_ROOT", "").strip()
    if not value:
        raise RuntimeError("RC6_FROZEN_ROOT is required")
    frozen_root = Path(value).resolve()
    registry_src = frozen_root / "08_Tooling" / "reusable-capability-registry" / "src"
    required = [
        frozen_root / "scripts" / "agent_os_issue_acceptance",
        registry_src / "reusable_capability_registry",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(
            "frozen checkout is missing canonical implementation paths: "
            + ", ".join(missing)
        )

    # Put the frozen canonical packages ahead of the runner checkout, then load
    # their package roots before runner.py adds its development fallback path.
    sys.path.insert(0, str(frozen_root))
    sys.path.insert(0, str(registry_src))
    import reusable_capability_registry  # noqa: F401
    import scripts.agent_os_issue_acceptance  # noqa: F401

    return frozen_root


def main() -> int:
    _prepare_frozen_imports()
    from scripts.agent_os_rc6_technical_pilot.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
