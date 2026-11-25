"""Test-run-only bootstrap for the canonical in-repo Navigation Registry."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


def _ancestor(marker):
    for parent in Path(__file__).resolve().parents:
        if (parent / marker).is_file():
            return parent
    raise pytest.UsageError(f"execution-service test setup: missing {marker}")


def _prefer_paths(*paths):
    priority = []
    for path in paths:
        path = path.resolve()
        if not path.is_dir():
            raise pytest.UsageError(f"execution-service test setup: missing {path}")
        priority.append(str(path))
    existing = [entry for entry in sys.path if str(Path(entry).resolve()) not in priority]
    sys.path[:] = priority + existing


class _MissingRuntimeModule(pytest.Module):
    def collect(self):
        pytest.skip(self.config._execution_service_runtime_skip)


def pytest_configure(config):
    repository = _ancestor("src/navigation_registry/__init__.py")
    package = _ancestor("runtime_dependency_preflight.py")
    helper_path = package / "runtime_dependency_preflight.py"
    spec = spec_from_file_location("runtime_dependency_preflight", helper_path)
    if spec is None or spec.loader is None:
        raise pytest.UsageError(f"execution-service test setup: cannot load {helper_path}")
    helper = module_from_spec(spec)
    spec.loader.exec_module(helper)

    project = package / "pyproject.toml"
    missing = helper.runtime_dependency_mismatches(project_file=project)
    if missing:
        config._execution_service_runtime_skip = (
            "execution-service test environment: " + "; ".join(missing)
            + f"; install the isolated runtime declared in {project}"
        )
        return

    canonical = repository / "src/navigation_registry/__init__.py"
    loaded = sys.modules.get("navigation_registry")
    if loaded is not None and Path(getattr(loaded, "__file__", None) or "").resolve() != canonical:
        raise pytest.UsageError("execution-service tests require the canonical in-repo Navigation Registry")

    old_path = sys.path[:]
    config.add_cleanup(lambda: sys.path.__setitem__(slice(None), old_path))
    _prefer_paths(repository / "src", package)


def pytest_pycollect_makemodule(module_path, parent):
    if getattr(parent.config, "_execution_service_runtime_skip", None):
        return _MissingRuntimeModule.from_parent(parent, path=module_path)
    return None
