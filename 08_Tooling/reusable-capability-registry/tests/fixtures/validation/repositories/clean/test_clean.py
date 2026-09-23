from src.cleanpkg.core import run


def test_run_increments():
    assert run(1) == 2
