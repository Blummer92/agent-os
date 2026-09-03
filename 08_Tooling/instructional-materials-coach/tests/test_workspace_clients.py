from unittest.mock import MagicMock

import pytest

from instructional_materials_coach.workspace_clients import apply_docs_requests, apply_slides_requests


def _request(token="{{title}}"):
    return {"replaceAllText": {"containsText": {"text": token, "matchCase": True}, "replaceText": "Lesson"}}


def test_apply_slides_requests_calls_batch_update():
    service = MagicMock()
    service.presentations.return_value.batchUpdate.return_value.execute.return_value = {"replies": [{"replaceAllText": {"occurrencesChanged": 1}}]}
    request = _request()
    apply_slides_requests(service, "presentation-id", [request])
    service.presentations.return_value.batchUpdate.assert_called_once_with(
        presentationId="presentation-id", body={"requests": [request]}
    )


def test_apply_slides_requests_skips_empty_requests():
    service = MagicMock()
    apply_slides_requests(service, "presentation-id", [])
    service.presentations.return_value.batchUpdate.assert_not_called()


def test_apply_slides_requests_fails_when_required_placeholder_not_replaced():
    service = MagicMock()
    service.presentations.return_value.batchUpdate.return_value.execute.return_value = {"replies": [{"replaceAllText": {"occurrencesChanged": 0}}]}
    with pytest.raises(RuntimeError, match="title"):
        apply_slides_requests(service, "presentation-id", [_request()])


def test_apply_docs_requests_calls_batch_update():
    service = MagicMock()
    service.documents.return_value.batchUpdate.return_value.execute.return_value = {"replies": [{"replaceAllText": {"occurrencesChanged": 1}}]}
    request = _request()
    apply_docs_requests(service, "doc-id", [request])
    service.documents.return_value.batchUpdate.assert_called_once_with(
        documentId="doc-id", body={"requests": [request]}
    )


def test_apply_docs_requests_skips_empty_requests():
    service = MagicMock()
    apply_docs_requests(service, "doc-id", [])
    service.documents.return_value.batchUpdate.assert_not_called()


def test_apply_docs_requests_fails_when_required_placeholder_not_replaced():
    service = MagicMock()
    service.documents.return_value.batchUpdate.return_value.execute.return_value = {"replies": [{"replaceAllText": {"occurrencesChanged": 0}}]}
    with pytest.raises(RuntimeError, match="question_2"):
        apply_docs_requests(service, "doc-id", [_request("{{question_2}}")])


def test_apply_requests_fail_when_reply_count_is_incomplete():
    service = MagicMock()
    service.documents.return_value.batchUpdate.return_value.execute.return_value = {"replies": []}
    with pytest.raises(RuntimeError, match="one result per request"):
        apply_docs_requests(service, "doc-id", [_request()])
