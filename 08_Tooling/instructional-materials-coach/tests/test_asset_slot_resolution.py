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
