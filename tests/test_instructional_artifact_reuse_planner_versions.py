from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.material_requirement import (
    V2_CONTRACT_ID,
    validate_material_requirement,
)
from instructional_workflow_contracts.reuse_planner import (
    plan_instructional_artifact_reuse,
)

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plan(requirement: object):
    return plan_instructional_artifact_reuse(
        requirement,
        [],
        changed_dependency_keys=[],
        impact_map={},
    )


def test_reuse_planner_accepts_valid_v2_without_version_conversion() -> None:
    requirement = _fixture("valid_material_requirement_v2.json")
    validated = validate_material_requirement(requirement)

    assert validated.status is ValidationStatus.VALID
    assert validated.record is not None
    assert validated.record.contract_version == V2_CONTRACT_ID

    result = _plan(validated)

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["requirement_id"] == validated.record.record_id
    assert payload["decision"] == "create-new-required"
    assert set(payload["authority"].values()) == {False}
    assert validated.record.contract_version == V2_CONTRACT_ID

    repeated = _plan(validated)
    assert repeated.status is ValidationStatus.VALID
    assert repeated.record is not None
    assert repeated.record.record_id == result.record.record_id
    assert repeated.record.fingerprint == result.record.fingerprint


def test_reuse_planner_rejects_prevalidated_unsupported_contract_version() -> None:
    validated = validate_material_requirement(_fixture("valid_material_requirement_v2.json"))
    assert validated.status is ValidationStatus.VALID
    assert validated.record is not None

    unsupported = replace(
        validated.record,
        contract_version="curriculum-material-requirement-v999",
    )
    result = _plan(unsupported)

    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert result.reason_codes == ("artifact-planner-incompatible-upstream",)
