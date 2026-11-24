"""Reviewed-request reuse and fail-closed catalog validation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts.agent_os_notion_lessons_write.admission import admit, AdmittedRequest, WriteBlocked
from scripts.agent_os_notion_lessons_write.catalog import (
    LESSONS, LL93_METADATA_REQUEST_ID, PROTECTED_FIELDS, REQUEST_ID, lesson_for, target_for,
)
from scripts.agent_os_notion_lessons_write.writer import execute, properties
from tests.agent_os_notion_lessons_write.test_writer import Client, CONTEXT, event


def entry(properties, target=None):
    return {'target_lesson_id': target, 'properties': properties}


class CatalogTests(unittest.TestCase):
    def test_second_reviewed_request_uses_same_admission_and_writer(self):
        # #3417 onboarding: a reviewed catalog entry needs no executor change.
        lesson = {**lesson_for(REQUEST_ID), 'Lesson Learned': 'Synthetic reviewed second lesson',
                  'Area': 'Testing', 'Learning Type': 'Testing lesson'}
        with patch('scripts.agent_os_notion_lessons_write.catalog.LESSONS', {**LESSONS, 'second-lesson': entry(lesson)}):
            request = admit(event('/agent-os notion-write second-lesson', number=4000, state='closed'), **CONTEXT)
            client = Client()
            result = execute(request, client)
            self.assertEqual((result['request_id'], result['status']), ('second-lesson', 'persisted'))
            self.assertEqual(client.calls.count('write'), 1)
            self.assertEqual(set(client.sent[0]), set(lesson))
            client.rows = [deepcopy(client.page)]
            for name, prop in properties('second-lesson').items():
                client.rows[0]['properties'][name] = {'type': next(iter(prop)), **deepcopy(prop)}
            client.page = deepcopy(client.rows[0])
            self.assertEqual(execute(request, client)['status'], 'unchanged')
            self.assertEqual(client.calls.count('write'), 1)

    def test_shipped_catalog_entries_are_valid_and_activation_free(self):
        for request_id in LESSONS:
            with self.subTest(request_id=request_id):
                self.assertFalse(PROTECTED_FIELDS & set(lesson_for(request_id)))
        self.assertEqual(target_for(LL93_METADATA_REQUEST_ID), 'LL-93')
        self.assertIsNone(target_for(REQUEST_ID))

    def test_unknown_or_unreviewed_payload_is_refused(self):
        for command in ('/agent-os notion-write unknown', '/agent-os notion-write https://other.example',
                        '/agent-os notion-write ' + REQUEST_ID + ' private student details'):
            with self.subTest(command=command), self.assertRaises(WriteBlocked):
                admit(event(command), **CONTEXT)
        base = dict(lesson_for(REQUEST_ID))
        invalid = {
            'governed': entry({**base, 'Approval': True}),
            'oversized': entry({**base, 'Guardrail': 'x' * 513}),
            'status': entry({**base, 'Status': 'Applied'}),
            'surface': entry({**base, 'Surface Before Work?': True}),
            'activation-update': entry({'Status': 'Applied'}, 'LL-93'),
            'foreign-link': entry({**base, 'Source Link': 'https://example.com/x'}),
            'missing-narrative': entry({'Area': 'Testing'}),
            'bad-target': entry({'Area': 'Testing'}, 'lesson-93'),
            'shape': {**entry(base), 'extra': 1},
        }
        for name, value in invalid.items():
            with self.subTest(name=name), patch('scripts.agent_os_notion_lessons_write.catalog.LESSONS', {name: value}):
                client = Client()
                self.assertEqual(execute(AdmittedRequest(1, request_id=name), client)['status'], 'blocked')
                self.assertEqual(client.calls, [])


class LL82ContinuationRefinementCatalogTests(unittest.TestCase):
    """#3417 LL-82 refinement: reviewed update entry, duplicate create retired."""

    def test_ll82_update_entry_is_bounded_and_provenance_corrected(self):
        from scripts.agent_os_notion_lessons_write.catalog import (
            LL82_CONTINUATION_REFINEMENT_REQUEST_ID, validate_entry,
        )
        key = LL82_CONTINUATION_REFINEMENT_REQUEST_ID
        self.assertEqual(key, 'll-82-continuation-refinement-2026-11-23')
        self.assertEqual(target_for(key), 'LL-82')
        self.assertIs(validate_entry(LESSONS[key]), LESSONS[key])
        values = lesson_for(key)
        # Corrected provenance: incident #3485, implementation PR #3670.
        self.assertEqual(values['Source Link'], 'https://github.com/Blummer92/agent-os/issues/3485')
        self.assertIn('https://github.com/Blummer92/agent-os/pull/3670', values['Supporting Source Links'])
        self.assertNotIn('3690', values['Source Link'])
        self.assertLessEqual(len(values['Supporting Source Links']), 5)
        self.assertEqual(values['Area'], 'Automation')
        self.assertEqual(values['Learning Type'], 'Mistake')
        self.assertFalse(PROTECTED_FIELDS & set(values))
        for name, value in values.items():
            if isinstance(value, str):
                self.assertLessEqual(len(value), 512, name)
        # Evidence distinctions: verified emission vs unverified host dispatch.
        self.assertIn('#3485', values['What Happened'])
        self.assertIn('remain unverified', values['What Happened'])
        self.assertIn('not independently reproduced', values['What Happened'])
        self.assertIn('not host next-dispatch', values['Guardrail'])

    def test_ll82_update_uses_owner_comment_admission_with_revision_binding(self):
        from scripts.agent_os_notion_lessons_write.catalog import LL82_CONTINUATION_REFINEMENT_REQUEST_ID
        command = '/agent-os notion-write ' + LL82_CONTINUATION_REFINEMENT_REQUEST_ID + ' LL-82 2026-11-15T00:40:00.000Z'
        request = admit(event(command, number=3417, state='closed'), **CONTEXT)
        self.assertEqual(request.request_id, LL82_CONTINUATION_REFINEMENT_REQUEST_ID)
        self.assertEqual(request.expected_lesson_id, 'LL-82')
        self.assertEqual(request.expected_revision, '2026-11-15T00:40:00.000Z')
        # A wrong target lesson cannot be bound to this reviewed entry.
        with self.assertRaises(WriteBlocked):
            admit(event(command.replace('LL-82 2026', 'LL-93 2026'), number=3417), **CONTEXT)

    def test_retired_duplicate_create_candidate_is_not_admissible(self):
        self.assertNotIn('continuation-live-consumer-2026-10-30', LESSONS)
        with self.assertRaises(WriteBlocked):
            admit(event('/agent-os notion-write continuation-live-consumer-2026-10-30', number=3417), **CONTEXT)

    def test_ll82_update_does_not_prove_notion_write_or_activation(self):
        from scripts.agent_os_notion_lessons_write.catalog import LL82_CONTINUATION_REFINEMENT_REQUEST_ID
        values = lesson_for(LL82_CONTINUATION_REFINEMENT_REQUEST_ID)
        self.assertNotIn('Status', values)
        self.assertNotIn('Surface Before Work?', values)
        self.assertNotIn('Owner / Agent', values)
