"""The production consumer must refuse unusable curriculum evidence and say why.

Nov 3 mutation C1/C2/GC1: ``compose_generation_context`` (called by the connected
build in cli.py) gates generation on the current-curriculum resolver. The resolver's
own tests killed C1 (stale owner evidence), but no consumer-level test did, and C2
(ambiguous unit) was visible only as a lost reason code. Each case changes exactly
one input and asserts the refusal carries the exact resolver reason, with an
active/ready positive control.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from instructional_materials_coach.generation_context import (
    GenerationContextError,
    compose_generation_context,
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


G = _load("_curriculum_reason_fixtures", "test_generation_context.py")


def _compose(evidence):
    return compose_generation_context(
        G._content(),
        material_requirement=G._requirement(),
        current_curriculum_evidence=evidence,
    )


def _evidence(**mutation):
    value = copy.deepcopy(G._photography_evidence())
    if "unit_status" in mutation:
        value["canonical_unit"]["status"] = mutation["unit_status"]
    if mutation.get("stale_first_gate"):
        value["owner_evidence"][0]["currentness"] = "stale"
    if mutation.get("drop_first_gate"):
        value["owner_evidence"] = value["owner_evidence"][1:]
    return value


def test_positive_control_active_unit_with_ready_gates_composes_content():
    assert _compose(_evidence()) is not None


@pytest.mark.parametrize(
    "status,reason",
    [
        ("ambiguous", "identity-canonical-unit-ambiguous"),
        ("archived", "identity-canonical-unit-archived"),
        ("split", "identity-canonical-unit-split"),
        ("merged", "identity-canonical-unit-merged"),
        ("human-review-required", "manual-review-canonical-unit-human-review"),
    ],
)
def test_non_active_canonical_unit_is_refused_with_its_exact_reason(status, reason):
    with pytest.raises(GenerationContextError, match=reason):
        _compose(_evidence(unit_status=status))


def test_stale_required_gate_is_refused_as_stale_material():
    with pytest.raises(GenerationContextError, match="source-stale-material"):
        _compose(_evidence(stale_first_gate=True))


def test_missing_required_gate_is_refused_as_missing_owner_evidence():
    with pytest.raises(GenerationContextError, match="dependency-owner-evidence-missing"):
        _compose(_evidence(drop_first_gate=True))
