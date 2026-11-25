"""Independent synthetic test controls from the scheduler mutation campaign."""
import pytest

from workflow_scheduler.execution.executor import _validate_adapter_result
from workflow_scheduler.models import WorkflowPlan, WorkflowStatus


def test_completion_refuses_duplicate_even_with_all_task_ids():
    plan = WorkflowPlan("w", "Plan", "owner", tasks=["a", "b"], status=WorkflowStatus.RUNNING)
    with pytest.raises(ValueError, match="requires every planned task"):
        plan.mark_completed(completed_task_ids=["a", "a", "b"])
    assert plan.status is WorkflowStatus.RUNNING


def test_adapter_success_requires_boolean_instead_of_integer():
    assert _validate_adapter_result({"success": True}) is None
    assert _validate_adapter_result({"success": 1}) == "adapter result 'success' must be a bool, got int"
