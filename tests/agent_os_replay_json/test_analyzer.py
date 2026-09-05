from scripts.agent_os_replay_json import analyze_replay


def test_folder_card_click_is_folder_entry_evidence():
    payload = {"steps": [{
        "type": "click",
        "selectors": [["[data-testid='folder-asset-card-digitalmedia']", "#card-heading"]],
    }]}
    action = analyze_replay(payload)[0]
    assert action.kind == "open_folder"
    assert action.target == "folder-asset-card-digitalmedia"
    assert action.source_indexes == (0,)


def test_folder_preview_click_is_not_folder_entry():
    payload = {"steps": [{
        "type": "click",
        "selectors": [[
            "[data-testid='folder-asset-card-digitalmedia']",
            "[data-testid='preview-button-id']",
        ]],
    }]}
    action = analyze_replay(payload)[0]
    assert action.kind == "click"
    assert action.target == "folder-asset-card-digitalmedia"


def test_cursor_noise_collapses_into_one_rename_with_evidence():
    steps = [{
        "type": "change",
        "value": "My F",
        "selectors": [["[data-testid='editor-document-title']", "#renameInputBox", "input"]],
    }]
    steps.extend({"type": "keyDown", "key": "ArrowLeft"} for _ in range(120))
    steps.extend({"type": "keyUp", "key": "ArrowLeft"} for _ in range(120))
    steps.append({
        "type": "change",
        "value": "My First Project",
        "selectors": [["[data-testid='editor-document-title']", "#renameInputBox", "input"]],
    })
    action = analyze_replay({"steps": steps})[0]
    assert action.kind == "rename"
    assert action.value == "My First Project"
    assert len(action.source_indexes) == 242
    assert action.source_indexes[0] == 0
    assert action.source_indexes[-1] == 241


def test_missing_change_value_is_not_invented_as_empty_text():
    action = analyze_replay({"steps": [{
        "type": "change",
        "selectors": [["[data-testid='editor-document-title']"]],
    }]})[0]
    assert action.value is None
    assert not any(item.startswith("value=") for item in action.evidence)


def test_explicit_empty_change_value_remains_empty_text():
    action = analyze_replay({"steps": [{
        "type": "change",
        "value": "",
        "selectors": [["[data-testid='editor-document-title']"]],
    }]})[0]
    assert action.value == ""
    assert "value=" in action.evidence


def test_click_and_double_click_remain_distinct():
    payload = {"steps": [
        {"type": "click", "selectors": [["aria/Your Stuff"]]},
        {"type": "doubleClick", "selectors": [["aria/Your Stuff"]]},
    ]}
    actions = analyze_replay(payload)
    assert actions[0].interaction == "click"
    assert actions[1].interaction == "doubleClick"


def test_loading_and_upload_actions_are_recovery_not_instructional():
    payload = {"steps": [
        {"type": "click", "selectors": [["[data-testid='x-loading-view']", "x-loading-folder-card"]]},
        {"type": "click", "selectors": [["[data-testid='editor-upload-in-progress-dialog']"]]},
    ]}
    actions = analyze_replay(payload)
    assert all(action.recovery for action in actions)
    assert all(not action.instructional for action in actions)


def test_account_specific_urn_and_search_history_are_fragile():
    payload = {"steps": [
        {"type": "navigate", "url": "https://example.test/folders/urn:aaid:sc:VA6C2:123"},
        {"type": "click", "selectors": [["[data-testid='search-history']", "#sp-menu-item-abcd"]]},
    ]}
    actions = analyze_replay(payload)
    assert actions[0].fragile is True
    assert actions[1].fragile is True


def test_malformed_selector_members_are_not_stringified_into_evidence():
    action = analyze_replay({"steps": [{
        "type": "click",
        "selectors": [["aria/Folder", 123, {"fake": "selector"}], 456],
    }]})[0]
    assert action.evidence == ("aria/Folder",)
    assert action.target == "aria/Folder"


def test_non_list_selector_container_fails_closed_to_no_selector_evidence():
    action = analyze_replay({"steps": [{"type": "click", "selectors": {"bad": "shape"}}]})[0]
    assert action.evidence == ()
    assert action.target is None


def test_missing_navigate_url_preserves_missing_target():
    action = analyze_replay({"steps": [{"type": "navigate"}]})[0]
    assert action.target is None


def test_present_navigate_url_is_unchanged():
    action = analyze_replay({"steps": [{"type": "navigate", "url": "https://example.test"}]})[0]
    assert action.target == "https://example.test"


def test_missing_steps_fails_closed():
    try:
        analyze_replay({})
    except ValueError as exc:
        assert "steps[]" in str(exc)
    else:
        raise AssertionError("expected ValueError")
