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
from scripts.agent_os_notion_lessons_write.catalog import LESSONS, REQUEST_ID, lesson_for
from scripts.agent_os_notion_lessons_write.writer import execute, properties
from tests.agent_os_notion_lessons_write.test_writer import Client, CONTEXT, PAGE_ID, REVISION, event, page


class CatalogTests(unittest.TestCase):
    def test_second_reviewed_request_uses_same_admission_and_writer(self):
        lesson = {**lesson_for(REQUEST_ID), 'Lesson Learned': 'Synthetic reviewed second lesson'}
        with patch('scripts.agent_os_notion_lessons_write.catalog.LESSONS', {**LESSONS, 'second-lesson': lesson}):
            request = admit(event('/agent-os notion-write second-lesson'), **CONTEXT)
            existing = page()
            for name, prop in properties('second-lesson').items():
                existing['properties'][name] = {'type': next(iter(prop)), **prop}
            client = Client(existing)
            result = execute(request, client)
            self.assertEqual(result['request_id'], 'second-lesson')
            self.assertEqual(result['status'], 'unchanged')
            self.assertNotIn('write', client.calls)
            existing['properties']['What Happened']['rich_text'] = [{'type': 'text', 'text': {'content': 'Earlier'}}]
            client = Client(existing)
            request = admit(event('/agent-os notion-write second-lesson ' + PAGE_ID + ' ' + REVISION), **CONTEXT)
            result = execute(request, client)
            self.assertEqual(result['status'], 'persisted')
            self.assertEqual(client.calls.count('write'), 1)
            self.assertEqual(client.calls[-2:], ['write', 'get'])

    def test_unknown_or_unreviewed_payload_is_refused(self):
        for command in ('/agent-os notion-write unknown', '/agent-os notion-write https://other.example',
                        '/agent-os notion-write ' + REQUEST_ID + ' private student details'):
            with self.subTest(command=command), self.assertRaises(WriteBlocked):
                admit(event(command), **CONTEXT)
        for lesson in ({**lesson_for(REQUEST_ID), 'Approval': True},
                       {**lesson_for(REQUEST_ID), 'Guardrail': 'x' * 513}):
            with patch('scripts.agent_os_notion_lessons_write.catalog.LESSONS', {'invalid': lesson}):
                client = Client()
                self.assertEqual(execute(AdmittedRequest(1, request_id='invalid'), client)['status'], 'blocked')
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
