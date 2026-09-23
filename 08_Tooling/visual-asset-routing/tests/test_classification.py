from visual_asset_routing.classification import (
    AssetType,
    ClassificationEvidenceSource,
    PerAssetClassification,
    evaluate_icon_system_gate,
)


def classification(reference, asset_type, source=ClassificationEvidenceSource.VISUAL_INSPECTION):
    return PerAssetClassification(reference, asset_type, source)


def test_icon_requires_positive_per_asset_visual_evidence():
    assert evaluate_icon_system_gate(classification("asset-a", AssetType.ICON)).icon_path_eligible is True
    insufficient_sources = (
        ClassificationEvidenceSource.FOLDER_NAME,
        ClassificationEvidenceSource.FILENAME,
        ClassificationEvidenceSource.FILE_EXTENSION,
        ClassificationEvidenceSource.BATCH_CONTEXT,
        ClassificationEvidenceSource.TEACHER_BATCH_LANGUAGE,
    )
    for source in insufficient_sources:
        result = evaluate_icon_system_gate(classification("asset-a", AssetType.ICON, source))
        assert result.icon_path_eligible is False
        assert result.review_required is True


def test_non_icons_never_enter_icon_path():
    for asset_type in (AssetType.PHOTOGRAPH, AssetType.ILLUSTRATION, AssetType.DIAGRAM, AssetType.OTHER_VISUAL):
        result = evaluate_icon_system_gate(classification("asset-a", asset_type))
        assert result.icon_path_eligible is False
        assert result.review_required is False


def test_ambiguous_fails_closed():
    result = evaluate_icon_system_gate(classification("asset-a", AssetType.AMBIGUOUS))
    assert result.icon_path_eligible is False
    assert result.review_required is True


def test_gate_never_grants_governed_authority():
    result = evaluate_icon_system_gate(classification("asset-a", AssetType.ICON))
    assert not any((
        result.external_write_authorized,
        result.approval_authorized,
        result.classroom_readiness_authorized,
        result.rights_authorized,
        result.privacy_authorized,
        result.source_authority_granted,
        result.production_authorized,
    ))
