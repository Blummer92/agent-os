def activity_type(text: str) -> str:
    value = text.casefold()
    if "image" in value and "prompt" in value:
        return "image-prompt-writing"
    if "tool" in value or "interface" in value:
        return "tool-operation"
    return "unspecified"


def test_image_prompt_challenge_is_not_tool_operation_practice():
    assert activity_type("Adobe Express image prompt challenge cards") == "image-prompt-writing"


def test_explicit_tool_operation_remains_distinct():
    assert activity_type("Practice the interface tool operation") == "tool-operation"
