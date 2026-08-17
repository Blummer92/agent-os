"""Shared repository-root import binding for Execution Service tests.

The package's runtime-composition modules intentionally reuse canonical
repository-local ``scripts.*`` contracts. Aggregate validation runs this suite
from the package directory with only ``src`` on ``PYTHONPATH``; bind the checked
out repository root here before test-module collection rather than making each
new integration test repeat the same path bootstrap.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
