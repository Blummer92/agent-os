"""Run the post-merge learning checks and fail if none actually ran."""
from pathlib import Path
import sys
import unittest


def run_suite(directory: Path, *, stream=None) -> int:
    """Return 0 for a passing, nonempty run, 1 for failures, or 5 for no tests."""
    stream = sys.stderr if stream is None else stream
    suite = unittest.TestLoader().discover(str(directory), pattern="test_*.py")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    if result.testsRun == len(result.skipped):
        print("No post-merge learning tests ran.", file=stream)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(run_suite(Path(__file__).resolve().parent))
