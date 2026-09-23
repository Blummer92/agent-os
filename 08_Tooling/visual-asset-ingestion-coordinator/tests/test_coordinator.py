from visual_asset_ingestion_coordinator import (
    CoordinatorRequest,
    CoordinatorState,
    GenerationProvenance,
    RoutingEvidence,
    WriterResult,
    coordinate_ingestion,
)


def route(**changes):
    data = dict(
        intake_reference="intake-1",
        duplicate_disposition="NO_DUPLICATE_FOUND",
        existing_identity=None,
        routing_state="CONFIRMED",
        teacher_confirmed=True,
        drive_destination_ref="drive-folder-1",
        notion_destination_ref="notion-library-1",
        destination_current=True,
        reusable_icon_confirmed=False,
    )
    data.update(changes)
    return RoutingEvidence(**data)


def provenance(**changes):
    data = dict(
        generation_handoff_id="handoff-1",
        returned_binding_id="binding-1",
        intake_id="intake-1",
        association_state="exact",
    )
    data.update(changes)
    return GenerationProvenance(**data)


def verified(identity):
    return WriterResult("VERIFIED", True, identity, external_write_performed=True)


def test_dry_run_calls_no_writers_and_preserves_provenance():
    called = []
    result = coordinate_ingestion(
        CoordinatorRequest(route(), provenance(), dry_run=True),
        drive_step=lambda _: called.append("drive"),
        library_step=lambda *_: called.append("library"),
    )
    assert result.state is CoordinatorState.DRY_RUN
    assert result.provenance == provenance()
    assert called == []
    assert result.external_write_authorized is False


def test_ordinary_upload_needs_no_fabricated_generation_provenance():
    result = coordinate_ingestion(CoordinatorRequest(route(), None, dry_run=True))
    assert result.state is CoordinatorState.DRY_RUN
    assert result.provenance is None


def test_provenance_must_match_exact_intake():
    result = coordinate_ingestion(
        CoordinatorRequest(route(), provenance(intake_id="intake-other"), dry_run=True)
    )
    assert result.state is CoordinatorState.PRECHECK_BLOCKED
    assert result.reason_codes == ("coordinator-provenance-intake-mismatch",)


def test_unconfirmed_or_stale_routing_blocks_before_writers():
    for routing in (
        route(routing_state="RECOMMENDED", teacher_confirmed=False),
        route(destination_current=False),
    ):
        called = []
        result = coordinate_ingestion(
            CoordinatorRequest(routing, None, dry_run=False),
            drive_step=lambda _: called.append("drive"),
            library_step=lambda *_: called.append("library"),
        )
        assert result.state is CoordinatorState.PRECHECK_BLOCKED
        assert called == []


def test_exact_existing_asset_does_not_write_new_binary():
    called = []
    result = coordinate_ingestion(
        CoordinatorRequest(route(duplicate_disposition="EXACT_EXISTING", existing_identity="asset-1"), None, dry_run=False),
        drive_step=lambda _: called.append("drive"),
        library_step=lambda *_: called.append("library"),
    )
    assert result.state is CoordinatorState.EXISTING_ASSET_REUSED
    assert called == []


def test_drive_success_library_failure_preserves_drive_for_repair():
    result = coordinate_ingestion(
        CoordinatorRequest(route(), provenance(), dry_run=False),
        drive_step=lambda _: verified("drive-file-1"),
        library_step=lambda *_: WriterResult("FAILED", False, repair_required=True),
    )
    assert result.state is CoordinatorState.DRIVE_VERIFIED_METADATA_PENDING
    assert result.drive_result.external_identity == "drive-file-1"
    assert result.library_result.repair_required is True


def test_ambiguous_drive_stops_before_library():
    called = []
    result = coordinate_ingestion(
        CoordinatorRequest(route(), None, dry_run=False),
        drive_step=lambda _: WriterResult("AMBIGUOUS_WRITE_RESULT", False, ambiguous=True, external_write_performed=True),
        library_step=lambda *_: called.append("library"),
    )
    assert result.state is CoordinatorState.AMBIGUOUS_EXTERNAL_OUTCOME
    assert called == []


def test_reusable_icon_requires_icon_completion():
    routing = route(reusable_icon_confirmed=True)
    pending = coordinate_ingestion(
        CoordinatorRequest(routing, None, dry_run=False),
        drive_step=lambda _: verified("drive-file-1"),
        library_step=lambda *_: verified("library-page-1"),
    )
    assert pending.state is CoordinatorState.ICON_SYSTEM_PENDING

    complete = coordinate_ingestion(
        CoordinatorRequest(routing, None, dry_run=False),
        drive_step=lambda _: verified("drive-file-1"),
        library_step=lambda *_: verified("library-page-1"),
        icon_step=lambda *_: verified("icon-page-1"),
    )
    assert complete.state is CoordinatorState.FULLY_SYNCHRONIZED
    assert complete.icon_result.external_identity == "icon-page-1"


def test_manual_review_duplicate_never_calls_writers():
    called = []
    result = coordinate_ingestion(
        CoordinatorRequest(route(duplicate_disposition="MANUAL_REVIEW_REQUIRED"), None, dry_run=False),
        drive_step=lambda _: called.append("drive"),
        library_step=lambda *_: called.append("library"),
    )
    assert result.state is CoordinatorState.PRECHECK_BLOCKED
    assert called == []
