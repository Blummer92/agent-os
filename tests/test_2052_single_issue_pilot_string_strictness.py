import sys
from pathlib import Path

import pytest

SCHEDULER_SRC = (
    Path(__file__).parents[1]
    / "08_Tooling"
    / "workflow-scheduler"
    / "src"
)
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.execution.single_issue_pilot import _bounded_details


@pytest.mark.parametrize(
    "value",
    [
        "detail-scalar",
        ("valid", 123),
        (None,),
        ({"invented": "text"},),
    ],
)
def test_single_issue_pilot_rejects_non_string_bounded_items(value):
    with pytest.raises(TypeError):
        _bounded_details(value)


def test_single_issue_pilot_preserves_valid_detail_strings():
    assert _bounded_details(("first", "second")) == ("first", "second")
