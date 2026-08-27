"""#1426 installed-wheel regression for the #1411 production publisher.

This test deliberately reuses #1300's canonical isolated host-runtime fixture.
That fixture builds the four real Agent OS production wheels, installs them into
an isolated venv with no repository-root PYTHONPATH or editable checkout, and
returns a working directory outside the repository.
"""

from __future__ import annotations

from pathlib import Path

from test_host_packaging import ROOT, _run, installed_runtime  # noqa: F401


def test_installed_wheels_import_production_handoff_publication(
    installed_runtime: tuple[Path, Path],
) -> None:
    """The merged #1411 publisher must import from installed wheels alone."""
    python, outside_repository = installed_runtime
    result = _run(
        [
            str(python),
            "-c",
            (
                "import agent_os_execution_service.production_handoff_publication "
                "as publication; print(publication.__file__)"
            ),
        ],
        cwd=outside_repository,
    )
    imported = Path(result.stdout.strip()).resolve()
    assert ROOT.resolve() not in imported.parents
    assert outside_repository.resolve() not in imported.parents
