"""Shared fixtures for the instructional materials coach test suite."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def fail_on_default_lessons_dir_writes():
    """Fail any test that records a lesson into the working-directory default.

    ``cli.DEFAULT_LESSONS_DIR`` is resolved against the process working
    directory, which is correct for an operator running ``log-lesson`` but wrong
    for a test: a test that omits ``--lessons-dir`` drops timestamped YAML
    carrying machine-specific ``/tmp`` paths into whatever tree pytest was
    started from. Tests must pass a ``tmp_path``-based directory instead.

    Files that already existed are left alone, so a contributor's real lesson
    records are never mistaken for test output.
    """
    from instructional_materials_coach.cli import DEFAULT_LESSONS_DIR

    default = Path(DEFAULT_LESSONS_DIR)
    before = _files(default)

    yield

    leaked = sorted(_files(default) - before)
    if not leaked:
        return
    for path in leaked:
        path.unlink()
    pytest.fail(
        f"test wrote lesson reports into the working tree at {default}: "
        f"{', '.join(path.name for path in leaked)}. "
        "Pass --lessons-dir under tmp_path instead of relying on DEFAULT_LESSONS_DIR."
    )


def _files(directory: Path) -> set[Path]:
    if not directory.is_dir():
        return set()
    return {path for path in directory.iterdir() if path.is_file()}
