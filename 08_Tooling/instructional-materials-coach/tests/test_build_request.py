"""#3453: the shared build composition has one deterministic result."""
import pytest

from instructional_materials_coach.build_request import compose_governed_build_request, live_build_input_factory


def _inputs():
    return dict(
        slides_template_id="slides", doc_template_id="docs",
        target_folder_id="folder", content_title="Unit",
        idempotency_key="key", slides_requests=(), docs_requests=(),
        visual_placements=(), resume_dir="resume",
        placement_transport=None, placement_receipts_dir="placements",
        qa_evidence_dir="qa",
    )


def test_cli_and_scheduler_factory_share_exact_composition():
    direct = compose_governed_build_request(**_inputs())
    scheduled = live_build_input_factory(object(), {}, governed_inputs_resolver=lambda request, subject: _inputs())
    assert direct == scheduled
    assert direct.build_input.qa_expectations.idempotency_key == "key"
    assert direct.builder_options["qa_evidence_dir"] == "qa"


def test_missing_identity_fails_closed():
    data = _inputs()
    data["slides_template_id"] = ""
    with pytest.raises(ValueError, match="governed-build-request-identity-missing"):
        compose_governed_build_request(**data)
