"""Local JSON export, validation and user-confirmed restoration; no external requests."""
from ui_helpers import open_personal_profile
from copy import deepcopy
from io import BytesIO
import importlib.util
import json
import unittest
from unittest.mock import patch

import app
from src.learning_plan import build_plan
from src.pathway import sample_answers, confirmed_profile
from src.plan_transfer import (export_plan, readable_plan, validate_saved_plan, restore_saved_plan, VERSION)
from src.reassessment import store_assessment, begin_reassessment
from src.scoring import rank_roles


def fixture() -> tuple[dict, dict, dict]:
    """Build a genuine confirmed assessment with one completed synthetic task."""
    answers = sample_answers() | {'Optional career goal': 'PRIVATE OPEN TEXT NOT FOR EXPORT',
                                  'name': 'SHOULD NEVER EXPORT', 'api_key': 'NEVER EXPORT'}
    profile = confirmed_profile(answers)
    _, roles, trends = app.load_demo()
    rows = rank_roles(profile, roles['roles'], trends['topics'])
    state = {}
    assessment = store_assessment(state, profile, answers, rows, roles, trends)
    role = roles['roles'][0]
    row = next(row for row in rows if row['code'] == role['code'])
    plan = build_plan(row, role, 5)
    completion = {plan['tasks'][0]['id']: True}
    return assessment, plan, completion


def encoded(document: dict) -> bytes:
    """Encode a mutated transfer for validation tests."""
    return json.dumps(document).encode()


class PlanTransferTests(unittest.TestCase):
    """Validate complete payloads, type boundaries and session reconstruction."""

    def test_export_structure_minimization_and_progress(self) -> None:
        """Export is readable, versioned, scoped, and includes no free text or cache evidence."""
        assessment, plan, completion = fixture()
        text = export_plan(assessment, plan, completion, '2026-10-22T12:00:00+00:00')
        document = json.loads(text)
        self.assertEqual(document['format_version'], VERSION)
        self.assertEqual(document['duration_weeks'], 4)
        self.assertEqual(document['weekly_hours'], 5)
        self.assertEqual(sum(document['completion'].values()), 1)
        self.assertTrue(document['learning_resource_catalog_version'])
        self.assertTrue(document['learning_resources'])
        self.assertTrue(all('url' in resource and 'verified_on' in resource
                            for resource in document['learning_resources']))
        self.assertEqual(len(document['answers']), 31)  # Thirty scored items plus the synthetic label.
        self.assertEqual(document['profile']['data_status'], 'synthetic')
        self.assertEqual(document['career']['code'], plan['role_code'])
        self.assertIn('not employment predictions', document['notice'])
        for private in ('PRIVATE OPEN TEXT', 'SHOULD NEVER EXPORT', 'NEVER EXPORT', 'source_url', 'cached_at'):
            self.assertNotIn(private, text)
        self.assertIn('\n  "', text)

    def test_restore_progress_and_continue_reassessment(self) -> None:
        """Restored tasks keep completion and form the baseline for the next profile assessment."""
        assessment, plan, completion = fixture()
        prepared = validate_saved_plan(export_plan(assessment, plan, completion).encode(), app.load_demo)
        state = {'pathway_draft': {'skill_04': 1}}
        restore_saved_plan(state, prepared)
        self.assertEqual(state['pathway_step'], 7)
        self.assertEqual(state['learning_role'], plan['role_code'])
        self.assertEqual(state['learning_progress'][plan['id']][plan['tasks'][0]['id']], True)
        self.assertEqual(state['pathway_assessment']['rows'], assessment['rows'])
        self.assertNotIn('Optional career goal', state['pathway_draft'])
        begin_reassessment(state)
        self.assertEqual(state['pathway_draft']['skill_04'], 2)
        state['pathway_draft']['skill_04'] = 4
        new_profile = confirmed_profile(state['pathway_draft'])
        new_rows = rank_roles(new_profile, assessment['roles']['roles'], assessment['trends']['topics'])
        store_assessment(state, new_profile, state['pathway_draft'], new_rows,
                         assessment['roles'], assessment['trends'])
        self.assertEqual(state['pathway_previous']['plans'][plan['role_code']]['completion'][plan['tasks'][0]['id']], True)
        self.assertNotEqual(state['pathway_assessment']['rows'], state['pathway_previous']['rows'])

    def test_all_weekly_budgets_round_trip_with_correct_week_totals(self) -> None:
        assessment, _, _ = fixture()
        role=assessment['roles']['roles'][0]
        row=next(item for item in assessment['rows'] if item['code']==role['code'])
        for hours in (3,5,8,10):
            with self.subTest(hours=hours):
                plan=build_plan(row,role,hours)
                text=export_plan(assessment,plan,{})
                document=json.loads(text)
                self.assertEqual(document['weekly_hours'],hours)
                self.assertEqual(document['plan']['weekly_hours'],hours)
                for week in range(1,5):
                    tasks=[task for task in document['plan']['tasks'] if task['week']==week]
                    self.assertEqual(sum(task['minutes'] for task in tasks),hours*60)
                restored=validate_saved_plan(text.encode(),app.load_demo)
                self.assertEqual(restored['plan'],plan)

    def test_invalid_versions_fields_types_and_tampering(self) -> None:
        """Bad schemas, nonboolean completion, altered tasks, scores or fixtures are rejected."""
        assessment, plan, completion = fixture()
        valid = json.loads(export_plan(assessment, plan, completion))
        cases = []
        for key in valid:
            item = deepcopy(valid)
            del item[key]
            cases.append(item)
        for key, value in (('format_version', 'v999'), ('duration_weeks', True), ('weekly_hours', '5'),
                           ('answers', []), ('profile', {}), ('exported_at', 'yesterday'), ('completion', [])):
            cases.append(valid | {key: value})
        changed = deepcopy(valid)
        changed['completion'][next(iter(changed['completion']))] = 1
        cases.append(changed)
        changed = deepcopy(valid)
        changed['plan']['tasks'][0]['action'] = 'arbitrary task'
        cases.append(changed)
        changed = deepcopy(valid)
        changed['last_assessment']['source_fingerprint'] = 'wrong'
        cases.append(changed)
        changed = deepcopy(valid)
        changed['answers']['skill_01'] = None
        cases.append(changed)
        cases.append(valid | {'contact': 'unexpected'})
        for index, document in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_saved_plan(encoded(document), app.load_demo)
        for raw in (b'bad json', b'[]', b'\xff', b' ' * 256001):
            with self.assertRaises(ValueError):
                validate_saved_plan(raw, app.load_demo)

    def test_legacy_v1_plan_restores_into_resource_catalog_without_losing_progress(self) -> None:
        """Prior validated exports remain importable and matching task checks are migrated."""
        from src.learning_plan import build_legacy_plan
        assessment, _, _ = fixture()
        role = assessment['roles']['roles'][0]
        row = next(item for item in assessment['rows'] if item['code'] == role['code'])
        old_plan = build_legacy_plan(row, role, 5)
        self.assertTrue(old_plan['tasks'])
        checked_id = old_plan['tasks'][0]['id']
        old_document = json.loads(export_plan(assessment, old_plan, {checked_id: True},
                                              '2026-10-22T00:00:00+00:00'))
        old_document.pop('learning_resources')
        old_document.pop('learning_resource_catalog_version')
        prepared = validate_saved_plan(encoded(old_document), app.load_demo)
        self.assertEqual(prepared['plan']['version'], 'practice-v2')
        self.assertTrue(prepared['completion'].get(checked_id))


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class PlanTransferUITests(unittest.TestCase):
    """Exercise upload validation/confirmation and task checks in the real Streamlit tree."""

    def test_upload_preview_confirm_progress_and_reassess(self) -> None:
        """The valid upload alone changes nothing; confirmation opens a plan with saved checks."""
        from streamlit.testing.v1 import AppTest
        assessment, plan, completion = fixture()
        upload = BytesIO(export_plan(assessment, plan, completion).encode())
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')), \
             patch('streamlit.file_uploader', return_value=upload):
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='restore')
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_step'], 0)
            self.assertNotIn('pathway_confirmed', page.session_state)
            self.assertTrue(page.button(key='restore_plan_confirm'))
            page.button(key='restore_plan_confirm').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_step'], 7)
            self.assertEqual(sum(box.value for box in page.checkbox), 1)
            downloads = page.get('download_button')
            self.assertEqual(len(downloads), 2)
            self.assertEqual(downloads[0].proto.label, 'Download my plan')
            page.button(key='pathway_reassess').click().run()
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.radio(key='pathway_skill_04').value, 2)
            page.radio(key='pathway_skill_04').set_value(4).run()
            page.session_state['pathway_step'] = 6
            page.run()
            page.button(key='pathway_confirm').click().run()
            self.assertFalse(page.exception)
            self.assertTrue(any('What changed' in item.value for item in page.subheader))

    def test_invalid_upload_preserves_session(self) -> None:
        """An invalid file shows an error and cannot replace an existing answer or assessment."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')), \
             patch('streamlit.file_uploader', return_value=BytesIO(b'{"format_version":"wrong"}')):
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='restore')
            existing = {'skill_04': 3, 'Optional career goal': 'Existing goal'}
            page.session_state['pathway_draft'] = existing
            page.session_state['pathway_assessment'] = {'existing': True}
            page.run()
            self.assertFalse(page.exception)
            self.assertTrue(any('Cannot restore this file' in error.value for error in page.error))
            self.assertEqual(page.session_state['pathway_draft'], existing)
            self.assertEqual(page.session_state['pathway_assessment'], {'existing': True})
            self.assertFalse(any(button.key == 'restore_plan_confirm' for button in page.button))
    def test_readable_exports_localize_without_changing_portable_data(self):
        from src.i18n import set_language, career_name, CATALOGS
        assessment, plan, completion = fixture()
        frozen = deepcopy((assessment, plan, completion))
        baseline = export_plan(assessment, plan, completion, '2026-10-22T00:00:00+00:00')
        try:
            for language in ('en', 'zh', 'ms'):
                set_language(language)
                text = readable_plan(assessment, plan, completion, app.LABELS)
                self.assertIn(career_name(plan['role_code']), text)
                self.assertIn(plan['role_code'], text)
                self.assertIn(plan['id'], text)
                self.assertIn(CATALOGS[language]['Write a small program that summarizes an invented numeric list; test empty and unusual inputs.'], text)
                self.assertIn('- [x]', text)
                self.assertIn(CATALOGS[language]['Verified learning resources'], text)
                self.assertIn(CATALOGS[language]['This week: {step}'].split('{step}')[0].strip(), text)
                for resource in json.loads(baseline)['learning_resources']:
                    self.assertIn(resource['url'], text)
                    self.assertIn(resource['name'], text)
                self.assertEqual(export_plan(assessment, plan, completion, '2026-10-22T00:00:00+00:00'), baseline)
                self.assertEqual((assessment, plan, completion), frozen)
                validate_saved_plan(baseline.encode(), app.load_demo)
        finally:
            set_language('en')
