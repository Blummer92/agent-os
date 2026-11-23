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


class ContinuationConsumerLessonCatalogTests(unittest.TestCase):
    """#3690 reviewed knowledge only: preserve one-write and activation boundaries."""

    def test_reviewed_continuation_candidate_is_bounded_and_provenance_scoped(self):
        from scripts.agent_os_notion_lessons_write.catalog import (
            CONTINUATION_CONSUMER_REQUEST_ID, validate_entry,
        )
        key = CONTINUATION_CONSUMER_REQUEST_ID
        self.assertEqual(key, 'continuation-live-consumer-2026-10-30')
        self.assertIsNone(target_for(key))
        self.assertIs(validate_entry(LESSONS[key]), LESSONS[key])
        values = lesson_for(key)
        self.assertEqual(values['Source Link'], 'https://github.com/Blummer92/agent-os/issues/3690')
        self.assertEqual(values['Area'], 'Governance')
        self.assertEqual(values['Learning Type'], 'Mistake')
        self.assertFalse(PROTECTED_FIELDS & set(values))
        for name, value in values.items():
            if isinstance(value, str):
                self.assertLessEqual(len(value), 512, name)
        self.assertIn('30 MCP tests passed', values['What Happened'])
        self.assertIn('remains unverified', values['What Happened'])
        self.assertIn('Owner-reported Cloud Shell runs', values['What Happened'])
        self.assertIn('excludes all continuation-named tools', values['What Happened'])
        self.assertIn('separate owner decision', values['Guardrail'])

    def test_new_candidate_uses_existing_owner_comment_admission(self):
        from scripts.agent_os_notion_lessons_write.catalog import CONTINUATION_CONSUMER_REQUEST_ID
        command = '/agent-os notion-write ' + CONTINUATION_CONSUMER_REQUEST_ID
        request = admit(event(command, number=3417, state='closed'), **CONTEXT)
        self.assertEqual(request.request_id, CONTINUATION_CONSUMER_REQUEST_ID)
        self.assertEqual(request.expected_lesson_id, None)
        with self.assertRaises(WriteBlocked):
            admit(event(command + ' LL-93 2026-10-06T23:07:00.000Z', number=3417), **CONTEXT)

    def test_reviewed_candidate_does_not_prove_notion_write_or_activation(self):
        from scripts.agent_os_notion_lessons_write.catalog import CONTINUATION_CONSUMER_REQUEST_ID
        key = CONTINUATION_CONSUMER_REQUEST_ID
        self.assertNotIn('Status', lesson_for(key))
        self.assertNotIn('Surface Before Work?', lesson_for(key))
        self.assertNotIn('Applies To', lesson_for(key))
        self.assertNotIn('Owner / Agent', lesson_for(key))
