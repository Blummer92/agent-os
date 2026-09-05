from scripts.agent_os_replay_json.rewriter import RewriteRequest, apply_request, rewrite_replay


def test_successful_rewrite_does_not_alias_nested_input():
    payload = {
        "metadata": {"tags": ["original"]},
        "steps": [{"type": "click", "selectors": [["aria/Folder", "#folder"]]}],
    }
    result = rewrite_replay(payload)
    result.rewritten_recording["metadata"]["tags"].append("changed")
    result.rewritten_recording["steps"][0]["selectors"][0].append("#changed")
    assert payload["metadata"]["tags"] == ["original"]
    assert payload["steps"][0]["selectors"] == [["aria/Folder", "#folder"]]


def test_successful_selector_change_does_not_alias_nested_input():
    payload = {
        "metadata": {"tags": ["original"]},
        "steps": [{"type": "click", "selectors": [["aria/Folder", "#folder"]]}],
    }
    request = RewriteRequest(
        kind="change-selector",
        semantic_action_id="action-0",
        source_indexes=(0,),
        replacement_selector="aria/Folder",
    )
    result = apply_request(payload, request)
    result.rewritten_recording["metadata"]["tags"].append("changed")
    assert payload["metadata"]["tags"] == ["original"]
    assert payload["steps"][0]["selectors"] == [["aria/Folder", "#folder"]]
