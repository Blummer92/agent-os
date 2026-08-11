from visual_asset_routing.classification import (
    AssetType,
    ClassificationEvidenceSource,
    PerAssetClassification,
    evaluate_icon_system_batch,
    evaluate_icon_system_gate,
)


def classification(reference, asset_type, source=ClassificationEvidenceSource.VISUAL_INSPECTION):
    return PerAssetClassification(reference, asset_type, source)


def eligible(batch):
    return [
        decision.classification.asset_reference
        for decision in evaluate_icon_system_batch(tuple(batch))
        if decision.icon_path_eligible
    ]


def test_all_icons():
    assert eligible([classification("i1", AssetType.ICON), classification("i2", AssetType.ICON)]) == ["i1", "i2"]


def test_all_photographs():
    assert eligible([classification("p1", AssetType.PHOTOGRAPH), classification("p2", AssetType.PHOTOGRAPH)]) == []


def test_icons_and_photographs_are_independent():
    assert eligible([classification("i", AssetType.ICON), classification("p", AssetType.PHOTOGRAPH)]) == ["i"]


def test_icons_and_illustrations_are_independent():
    assert eligible([classification("i", AssetType.ICON), classification("g", AssetType.ILLUSTRATION)]) == ["i"]


def test_photographs_and_diagrams_never_enter_icon_path():
    assert eligible([classification("p", AssetType.PHOTOGRAPH), classification("d", AssetType.DIAGRAM)]) == []


def test_ambiguous_asset_blocks_only_itself():
    results = evaluate_icon_system_batch((classification("i", AssetType.ICON), classification("a", AssetType.AMBIGUOUS)))
    assert results[0].icon_path_eligible is True
    assert results[1].review_required is True


def test_icons_folder_cannot_force_photo_to_icon():
    result = evaluate_icon_system_gate(classification("photo", AssetType.PHOTOGRAPH, ClassificationEvidenceSource.FOLDER_NAME))
    assert result.icon_path_eligible is False


def test_icon_filename_cannot_force_photo_to_icon():
    result = evaluate_icon_system_gate(classification("icon-example.png", AssetType.PHOTOGRAPH, ClassificationEvidenceSource.FILENAME))
    assert result.icon_path_eligible is False


def test_teacher_batch_language_cannot_force_icon_status():
    result = evaluate_icon_system_gate(classification("photo", AssetType.PHOTOGRAPH, ClassificationEvidenceSource.TEACHER_BATCH_LANGUAGE))
    assert result.icon_path_eligible is False


def test_retry_is_deterministic_and_does_not_duplicate_decisions():
    batch = (classification("i", AssetType.ICON), classification("p", AssetType.PHOTOGRAPH))
    first = evaluate_icon_system_batch(batch)
    second = evaluate_icon_system_batch(batch)
    assert first == second
    assert len(first) == len(batch)
