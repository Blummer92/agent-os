def classify_requested_delivery(text: str) -> str:
    normalized = text.casefold()
    if "copy" in normalized and "paste" in normalized and "prompt" in normalized:
        return "prompt-text"
    return "unspecified"


def test_copy_paste_image_prompts_resolve_to_text_not_artifact_generation():
    assert classify_requested_delivery("Give me copy and paste image prompts") == "prompt-text"


def test_negative_pdf_correction_does_not_imply_image_artifact():
    assert classify_requested_delivery("Not a PDF; I want copy-paste image prompts") == "prompt-text"
