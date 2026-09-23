from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.slides_requests import build_slides_replace_requests


def _sample_content():
    return content_from_dict(
        {
            "title": "Fractions Intro",
            "objectives": ["Add fractions"],
            "slides": [{"index": 1, "bullets": ["Hello"]}],
            "worksheet_questions": ["Q1?"],
        }
    )


def test_build_slides_replace_requests_covers_every_token():
    requests = build_slides_replace_requests(_sample_content())
    texts = {r["replaceAllText"]["containsText"]["text"] for r in requests}
    assert texts == {"{{title}}", "{{objective_1}}", "{{slide_1_bullet_1}}", "{{question_1}}"}


def test_build_slides_replace_requests_maps_correct_replacement_text():
    requests = build_slides_replace_requests(_sample_content())
    by_token = {r["replaceAllText"]["containsText"]["text"]: r["replaceAllText"]["replaceText"] for r in requests}
    assert by_token["{{title}}"] == "Fractions Intro"
    assert by_token["{{slide_1_bullet_1}}"] == "Hello"


def test_build_slides_replace_requests_never_touches_a_file():
    # Pure function: same input always produces the same output, no I/O.
    assert build_slides_replace_requests(_sample_content()) == build_slides_replace_requests(_sample_content())
