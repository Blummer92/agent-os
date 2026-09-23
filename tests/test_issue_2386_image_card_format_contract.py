def requested_format(text: str) -> str:
    value = text.casefold()
    if "pdf" in value and ("not" in value or "don't" in value):
        if "visual" in value or "image" in value or "card" in value:
            return "image-cards"
    if "pdf" in value:
        return "pdf"
    return "unspecified"


def test_visual_cards_after_pdf_rejection_resolve_to_images():
    assert requested_format("Not a PDF; make visual image challenge cards") == "image-cards"


def test_explicit_pdf_request_remains_pdf():
    assert requested_format("Make a PDF") == "pdf"
