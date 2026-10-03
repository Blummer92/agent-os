from instructional_materials_coach.asset_slot_resolution import resolve_asset_slots


def _describe(metadata_by_file_id):
    def describe_drive_file(file_id):
        if file_id not in metadata_by_file_id:
            raise RuntimeError(f"drive lookup failed for {file_id}")
        return metadata_by_file_id[file_id]
    return describe_drive_file


def test_no_required_asset_slots_resolves_vacuously():
    result = resolve_asset_slots(asset_slots={}, describe_drive_file=_describe({}))
    assert result.status == "resolved"
    assert result.unresolvable_slots == ()


def test_asset_slot_with_live_drive_file_resolves():
    result = resolve_asset_slots(
        asset_slots={"CB-MINI-001": "drive-file-1"},
        describe_drive_file=_describe({"drive-file-1": {"id": "drive-file-1", "trashed": False}}),
    )
    assert result.status == "resolved"
    assert result.resolved_slots == ("CB-MINI-001",)
    assert result.unresolvable_slots == ()


def test_asset_slot_without_drive_binding_is_unresolvable():
    result = resolve_asset_slots(asset_slots={"CB-MINI-001": None}, describe_drive_file=_describe({}))
    assert result.status == "unresolvable"
    assert result.unresolvable_slots == ("CB-MINI-001",)


def test_asset_slot_with_empty_drive_file_id_is_unresolvable_without_lookup():
    calls = []

    def describe_drive_file(file_id):
        calls.append(file_id)
        return {"id": file_id, "trashed": False}

    result = resolve_asset_slots(asset_slots={"CB-SHOT-001": ""}, describe_drive_file=describe_drive_file)
    assert result.status == "unresolvable"
    assert result.unresolvable_slots == ("CB-SHOT-001",)
    assert calls == []


def test_asset_slot_whose_drive_lookup_fails_is_unresolvable():
    result = resolve_asset_slots(
        asset_slots={"CB-MINI-001": "missing-drive-file"},
        describe_drive_file=_describe({}),
    )
    assert result.status == "unresolvable"
    assert result.unresolvable_slots == ("CB-MINI-001",)


def test_asset_slot_bound_to_trashed_drive_file_is_unresolvable():
    result = resolve_asset_slots(
        asset_slots={"CB-MINI-001": "drive-file-1"},
        describe_drive_file=_describe({"drive-file-1": {"id": "drive-file-1", "trashed": True}}),
    )
    assert result.status == "unresolvable"
    assert result.unresolvable_slots == ("CB-MINI-001",)


def test_one_unresolvable_slot_fails_the_whole_resolution_and_names_every_slot():
    result = resolve_asset_slots(
        asset_slots={"CB-MINI-001": "drive-file-1", "CB-SHOT-001": "missing-drive-file"},
        describe_drive_file=_describe({"drive-file-1": {"id": "drive-file-1", "trashed": False}}),
    )
    assert result.status == "unresolvable"
    assert result.resolved_slots == ("CB-MINI-001",)
    assert result.unresolvable_slots == ("CB-SHOT-001",)


def test_missing_or_ambiguous_file_evidence_is_unresolvable():
    for metadata in ({}, {"id": "file-1"}, {"id": "file-1", "trashed": None},
                     {"id": "file-1", "trashed": 0}, {"trashed": False},
                     {"id": "different-file", "trashed": False}):
        result = resolve_asset_slots(
            asset_slots={"synthetic-slot": "file-1"},
            describe_drive_file=lambda _file_id: metadata,
        )
        assert result.status == "unresolvable", metadata
        assert result.unresolvable_slots == ("synthetic-slot",)


# --- #3256 content identity -------------------------------------------------

SHA_A = "a" * 64
SHA_B = "b" * 64


def _identity(value):
    return {
        "contract_version": "governed-asset-content-identity-v1",
        "source": "drive-sha256",
        "algorithm": "sha256",
        "value": value,
    }


def test_matching_content_identity_resolves():
    result = resolve_asset_slots(
        asset_slots={"slot-1": "drive-file-1"},
        describe_drive_file=_describe({"drive-file-1": {"id": "drive-file-1", "trashed": False, "sha256Checksum": SHA_A}}),
        expected_content_identities={"slot-1": _identity(SHA_A)},
    )
    assert result.status == "resolved"
    assert result.slot_outcomes == {"slot-1": "resolved"}
    assert result.content_identity_mismatches == ()


def test_modified_after_approval_fails_closed_with_explicit_mismatch():
    result = resolve_asset_slots(
        asset_slots={"slot-1": "drive-file-1"},
        describe_drive_file=_describe({"drive-file-1": {"id": "drive-file-1", "trashed": False, "sha256Checksum": SHA_B}}),
        expected_content_identities={"slot-1": _identity(SHA_A)},
    )
    assert result.status == "unresolvable"
    assert result.slot_outcomes == {"slot-1": "content-identity-mismatch"}
    assert result.content_identity_mismatches == ("slot-1",)
    assert result.unresolvable_slots == ("slot-1",)


def test_metadata_without_hash_fields_is_unverifiable_not_absence():
    result = resolve_asset_slots(
        asset_slots={"slot-1": "drive-file-1"},
        describe_drive_file=_describe({"drive-file-1": {"id": "drive-file-1", "trashed": False}}),
        expected_content_identities={"slot-1": _identity(SHA_A)},
    )
    assert result.status == "unresolvable"
    assert result.slot_outcomes == {"slot-1": "content-identity-unverifiable"}


def test_no_expected_identity_preserves_legacy_resolution():
    result = resolve_asset_slots(
        asset_slots={"slot-1": "drive-file-1"},
        describe_drive_file=_describe({"drive-file-1": {"id": "drive-file-1", "trashed": False}}),
    )
    assert result.status == "resolved"
    assert result.slot_outcomes == {"slot-1": "resolved"}


def test_not_found_and_no_access_are_distinct_outcomes():
    class NotFoundError(RuntimeError):
        drive_outcome = "not-found"

    class NoAccessError(RuntimeError):
        drive_outcome = "no-access"

    def describe(file_id):
        if file_id == "gone":
            raise NotFoundError("deleted")
        raise NoAccessError("forbidden")

    result = resolve_asset_slots(
        asset_slots={"deleted-slot": "gone", "private-slot": "secret"},
        describe_drive_file=describe,
    )
    assert result.status == "unresolvable"
    assert result.slot_outcomes == {"deleted-slot": "not-found", "private-slot": "no-access"}


def test_outcome_envelope_is_understood():
    result = resolve_asset_slots(
        asset_slots={"slot-1": "gone"},
        describe_drive_file=lambda _fid: {"outcome": "not-found", "metadata": None},
    )
    assert result.slot_outcomes == {"slot-1": "not-found"}
    assert result.unresolvable_slots == ("slot-1",)
