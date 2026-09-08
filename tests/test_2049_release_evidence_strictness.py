import importlib.util
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).parents[1] / "scripts" / "agent-os-release-run.py"
spec = importlib.util.spec_from_file_location("release_run_strictness", MODULE)
release_run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_run
spec.loader.exec_module(release_run)


@pytest.mark.parametrize(
    "field",
    [
        "repository",
        "expected_head_sha",
        "observed_head_sha",
        "current_main_sha",
        "validation_head_sha",
        "branch_state",
        "pr_state",
        "pr_lifecycle_state",
        "issue_state",
    ],
)
def test_release_evidence_rejects_non_string_canonical_text(field):
    with pytest.raises(TypeError):
        release_run.evaluate_release_run({field: 123})


@pytest.mark.parametrize("value", ["run:123", ["run:123", 456], {"run": "123"}])
def test_source_identifiers_reject_scalar_or_non_string_shapes(value):
    with pytest.raises(TypeError):
        release_run._source_identifier_strings(value)


def test_source_identifiers_preserve_valid_string_collection():
    assert release_run._source_identifier_strings(["run:123", "job:456"]) == (
        "run:123",
        "job:456",
    )
