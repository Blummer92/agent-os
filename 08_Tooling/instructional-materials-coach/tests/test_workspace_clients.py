from unittest.mock import MagicMock

from instructional_materials_coach.workspace_clients import apply_docs_requests, apply_slides_requests


def test_apply_slides_requests_calls_batch_update():
    service = MagicMock()
    apply_slides_requests(service, "presentation-id", [{"replaceAllText": {}}])
    service.presentations.return_value.batchUpdate.assert_called_once_with(
        presentationId="presentation-id", body={"requests": [{"replaceAllText": {}}]}
    )


def test_apply_slides_requests_skips_empty_requests():
    service = MagicMock()
    apply_slides_requests(service, "presentation-id", [])
    service.presentations.return_value.batchUpdate.assert_not_called()


def test_apply_docs_requests_calls_batch_update():
    service = MagicMock()
    apply_docs_requests(service, "doc-id", [{"replaceAllText": {}}])
    service.documents.return_value.batchUpdate.assert_called_once_with(
        documentId="doc-id", body={"requests": [{"replaceAllText": {}}]}
    )


def test_apply_docs_requests_skips_empty_requests():
    service = MagicMock()
    apply_docs_requests(service, "doc-id", [])
    service.documents.return_value.batchUpdate.assert_not_called()
