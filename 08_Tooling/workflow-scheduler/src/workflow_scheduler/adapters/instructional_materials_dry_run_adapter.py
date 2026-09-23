"""Pure-local adapter for the Instructional Materials Coach dry-run contract."""

from typing import Any, Dict

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.adapters.instructional_materials_contract import (
    validate_instructional_materials_contract,
)
from workflow_scheduler.models import ExecutionRequest


class InstructionalMaterialsDryRunAdapter(TaskAdapter):
    """Delegate one immutable request to the C3A validator without execution."""

    accepts_execution_request = True

    def execute(self, request: ExecutionRequest) -> Dict[str, Any]:
        return validate_instructional_materials_contract(request)
