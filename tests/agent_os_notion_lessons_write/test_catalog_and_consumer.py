"""Reviewed-request reuse and the separate CKR6 activation boundary."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '08_Tooling/agent-memory-context-manager/src'))
from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_activation_bridge import normalize_lesson_row, LessonActivationSkip
from agent_memory_context_manager.lesson_preflight import consume_lesson_preflight
from scripts.agent_os_notion_lessons_write.admission import admit, AdmittedRequest, WriteBlocked
from scripts.agent_os_notion_lessons_write.catalog import (
    LESSONS, LL93_METADATA_REQUEST_ID, LL87_GUARDRAIL_REQUEST_ID, PROTECTED_FIELDS, REQUEST_ID, lesson_for, target_for,
)
from scripts.agent_os_notion_lessons_write.writer import execute, properties
from tests.agent_os_notion_lessons_write.test_writer import Client, CONTEXT, event, page


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

    def test_ll87_refinement_is_reviewed_guardrail_only_and_revision_bound(self):
        # AOS-3483-F: exact proposal receipt 6096274166; no activation or write authority.
        self.assertEqual(target_for(LL87_GUARDRAIL_REQUEST_ID), 'LL-87')
        self.assertEqual(lesson_for(LL87_GUARDRAIL_REQUEST_ID), {
            'Guardrail': 'If a PR description contains a GitHub closing keyword referencing an issue, merging may close that issue. When live acceptance remains, use a non-closing Part of reference and verify the PR description before merge.',
        })
        self.assertFalse(PROTECTED_FIELDS & set(lesson_for(LL87_GUARDRAIL_REQUEST_ID)))
        command = '/agent-os notion-write ' + LL87_GUARDRAIL_REQUEST_ID + ' LL-87 2026-10-05T13:06:00.000Z'
        request = admit(event(command, number=3418), **CONTEXT)
        self.assertEqual(request.request_id, LL87_GUARDRAIL_REQUEST_ID)
        self.assertEqual(request.target_lesson_id, 'LL-87')

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


class ConsumerTests(unittest.TestCase):
    def row(self):
        row = page()
        for name in properties():
            prop = row['properties'][name]
            for text in prop[prop['type']]:
                text['plain_text'] = text['text']['content']
        row['properties'].update({
            'Lesson ID': {'type': 'unique_id', 'unique_id': {'prefix': 'LL', 'number': 999}},
            'Status': {'type': 'select', 'select': {'name': 'New'}},
            'Surface Before Work?': {'type': 'checkbox', 'checkbox': False},
            'Area': {'type': 'select', 'select': None},
        })
        return row

    def test_persisted_narrative_does_not_imply_consumer_eligibility(self):
        result = normalize_lesson_row(self.row())
        self.assertIsInstance(result, LessonActivationSkip)
        self.assertEqual(result.reason, 'ambiguous-area-vocabulary')

    def test_live_ll93_metadata_gap_rejects_before_selection(self):
        # Sanitized shape confirmed by read-only run 37548974650; no raw row stored.
        row = self.row()
        row['properties']['Status']['select'] = None
        result = normalize_lesson_row(row)
        self.assertIsInstance(result, LessonActivationSkip)
        self.assertEqual(result.reason, 'ambiguous-status-vocabulary')

    def test_owner_supplied_metadata_allows_existing_readonly_selector(self):
        row = self.row()
        row['properties'].update({
            'Surface Before Work?': {'type': 'checkbox', 'checkbox': True},
            'Area': {'type': 'select', 'select': {'name': 'Governance'}},
            'Learning Type': {'type': 'select', 'select': {'name': 'Mistake'}},
            'Applies To': {'type': 'multi_select', 'multi_select': [{'name': 'Notion'}]},
            'Source Link': {'type': 'url', 'url': 'https://github.com/Blummer92/agent-os/issues/3305'},
        })
        request = CodingKnowledgeRequest(task_reference='CKR6 consumer regression',
                                         known_knowledge_refs=('LL-999',), capability_keywords=('failure-avoidance',),
                                         specialized_knowledge_required=True)
        before = deepcopy(row)
        result = consume_lesson_preflight(request, (normalize_lesson_row(row),))
        self.assertEqual(result.selected_lesson_ids, ('LL-999',))
        self.assertEqual(result.lesson_retrieval_status.value, 'sufficient')
        self.assertEqual(row, before)
        row['properties']['Surface Before Work?']['checkbox'] = False
        self.assertEqual(consume_lesson_preflight(request, (normalize_lesson_row(row),)).selected_lesson_ids, ())
        row['properties']['Surface Before Work?']['checkbox'] = True
        row['properties']['Source Link']['url'] = None
        self.assertNotEqual(consume_lesson_preflight(request, (normalize_lesson_row(row),)).lesson_retrieval_status.value, 'sufficient')


class DescriptiveMetadataIsNotActivationTests(unittest.TestCase):
    def test_reviewed_ll93_metadata_still_requires_governed_status_and_surface(self):
        row = page(metadata=dict(lesson_for(LL93_METADATA_REQUEST_ID)))
        for name in ('Lesson Learned', 'What Happened', 'What To Do Next Time', 'Guardrail'):
            prop = row['properties'][name]
            for text in prop[prop['type']]:
                text['plain_text'] = text['text']['content']
        result = normalize_lesson_row(row)
        self.assertIsInstance(result, LessonActivationSkip)
        self.assertEqual(result.reason, 'ambiguous-status-vocabulary')
        # Even with an owner-set Status, Surface Before Work? stays governed.
        row['properties']['Status'] = {'type': 'select', 'select': {'name': 'New'}}
        evidence = normalize_lesson_row(row)
        self.assertFalse(evidence.surface_before_work)
        self.assertEqual(evidence.canonical_github_refs, ('https://github.com/Blummer92/agent-os/issues/3305',))
