"""Complete translation catalogs and real page interactions; all network is forbidden."""
from ui_helpers import open_personal_profile
import ast
import importlib
from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import Mock, patch

import app
from src.i18n import (CATALOGS, LANGUAGES, display_text, set_language, tr,
                      translated_options, validate_catalogs)
from src.pathway import BACKGROUND, DIMENSIONS, INTERESTS, PREFERENCES, SDGS, STEPS
from src.learning_plan import PHASES, PRACTICE
from src.plan_transfer import export_plan


class CatalogTests(unittest.TestCase):
    def tearDown(self):
        set_language('en')

    def test_complete_nonempty_catalogs_and_placeholders(self):
        validate_catalogs()
        for code in LANGUAGES:
            for mutate in ('missing', 'empty', 'placeholder'):
                catalogs = deepcopy(CATALOGS)
                if mutate == 'missing':
                    catalogs[code].pop('Next')
                elif mutate == 'empty':
                    catalogs[code]['Next'] = ' '
                else:
                    catalogs[code]['Next'] = 'Next {unexpected}'
                with self.subTest(code=code, mutate=mutate), self.assertRaises(ValueError):
                    validate_catalogs(catalogs)
            set_language(code)
            with self.assertRaises(KeyError):
                tr('unregistered UI message')

    def test_language_state_always_uses_supported_codes(self):
        from src.i18n import initialize_language
        for saved, expected in ((None, 'en'), ('English', 'en'), ('中文', 'zh'),
                                ('简体中文', 'zh'), ('Bahasa Melayu', 'ms'),
                                ('en', 'en'), ('zh', 'zh'), ('ms', 'ms'), ('obsolete', 'en')):
            state = {'pathway_draft': {'skill_04': 3}, 'pathway_restored': True}
            if saved is not None:
                state['ui_language'] = saved
            self.assertEqual(initialize_language(state), expected)
            self.assertEqual(state, {'pathway_draft': {'skill_04': 3}, 'pathway_restored': True,
                                     'ui_language': expected})

    def test_every_static_translation_call_is_registered_and_imported(self):
        helpers = {'tr', 'display_text', 'display_value', 'table_text', 'translated_options', 'translate_error'}
        for path in [app.ROOT/'app.py', *sorted((app.ROOT/'src').glob('*.py'))]:
            if path.name == 'i18n.py':
                continue
            tree = ast.parse(path.read_text())
            imported = {alias.asname or alias.name for node in tree.body
                        if isinstance(node, ast.ImportFrom) and node.module == 'src.i18n'
                        for alias in node.names}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id in helpers:
                    self.assertIn(node.func.id, imported, str(path))
                if node.func.id == 'tr' and isinstance(node.args[0], ast.Constant):
                    for code in LANGUAGES:
                        self.assertIn(node.args[0].value, CATALOGS[code], str(path))

    def test_all_application_translators_resolve_at_runtime(self):
        for path in [app.ROOT/'app.py', *sorted((app.ROOT/'src').rglob('*.py')),
                     *sorted((app.ROOT/'scripts').rglob('*.py'))]:
            tree = ast.parse(path.read_text())
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'tr']
            if not calls:
                continue
            module_name = '.'.join(path.relative_to(app.ROOT).with_suffix('').parts)
            module = importlib.import_module(module_name)
            with self.subTest(module=module_name):
                self.assertIs(module.tr, tr)
        from src.pathway import render_pathway
        self.assertIs(render_pathway.__globals__['tr'], tr)

    def test_indirect_questionnaire_and_plan_labels_are_registered(self):
        labels = [*app.LABELS.values(), *app.LEVELS, *DIMENSIONS, *STEPS, *SDGS,
                  *(text for _, text in INTERESTS), *BACKGROUND, *PREFERENCES,
                  *(value for values in BACKGROUND.values() for value in values),
                  *(value for values in PREFERENCES.values() for value in values),
                  *PHASES, *(value for pair in PRACTICE.values() for value in pair)]
        for code in LANGUAGES:
            for label in labels:
                self.assertIn(label, CATALOGS[code])

    def test_formatters_capture_locale_and_keep_internal_options(self):
        set_language('zh')
        formatter = translated_options()
        rating = translated_options(lambda n: f'{n} — {app.LEVELS[n]}')
        set_language('ms')
        self.assertEqual(formatter('Current student'), '在校学生')
        self.assertEqual(rating(2), '2 — 在指导下应用')
        self.assertEqual(translated_options()('Current student'), 'Pelajar semasa')

    def test_template_values_free_text_and_external_responses_are_verbatim(self):
        from src.i18n import table_text, translate_error
        set_language('zh')
        self.assertEqual(tr('{v0} · {v1}', v0='Programming', v1='Critical Thinking'),
                         'Programming · Critical Thinking')
        original = [{'Field': 'Optional career goal', 'Answer': 'Programming'},
                    {'Field': 'SDG preferences', 'Answer': ['4. Quality education', '13. Climate action']}]
        before = deepcopy(original)
        rendered = table_text(original)
        self.assertEqual(rendered[0]['回答'], 'Programming')
        self.assertEqual(rendered[1]['回答'], '4. 优质教育, 13. 气候行动')
        self.assertEqual(original, before)
        self.assertEqual(translate_error('GitHub request failed: RIASEC zero vector'),
                         'GitHub 请求失败：RIASEC zero vector')


class LanguagePageTests(unittest.TestCase):
    def setUp(self):
        from src.github_trends import GitHubTrends
        self.network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No model HTTP'))
        self.urlopen = patch('urllib.request.urlopen', side_effect=AssertionError('No GitHub HTTP'))
        self.client = GitHubTrends(opener=Mock(side_effect=AssertionError('No HTTP')))
        self.shared = patch('src.github_trends.shared_client', return_value=self.client)
        self.internal_shared = patch('app.shared_client', return_value=self.client)
        for patcher in (self.network, self.urlopen, self.shared, self.internal_shared):
            patcher.start()
            self.addCleanup(patcher.stop)

    def page(self):
        from streamlit.testing.v1 import AppTest
        page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
        self.healthy(page)
        return page

    def healthy(self, page, allow_error=False):
        self.assertFalse(page.exception)
        if not allow_error:
            self.assertFalse(page.error)

    def switch(self, page, language, allow_error=False):
        page.selectbox(key='ui_language').set_value(language).run()
        self.healthy(page, allow_error)
        self.assertEqual(page.session_state['ui_language'], language)
        self.assertEqual(page.selectbox(key='ui_language').value, language)
        self.assertEqual(page.selectbox(key='ui_language').options, ['English', '中文', 'Bahasa Melayu'])
        return page

    def text(self, code, key):
        return CATALOGS[code][key]

    def test_real_pathway_navigation_in_each_language(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                page = self.page()
                self.switch(page, language)
                page.radio(key='page_mode').set_value('Career pathway prototype').run()
                self.healthy(page)
                self.assertTrue(any(item.value == self.text(language, 'Let us get to know you')
                                    for item in page.header))
                page.button(key='pathway_start').click().run()
                self.healthy(page)
                self.assertTrue(any(item.value == self.text(language, 'Background')
                                    for item in page.subheader))
                page.radio(key='pathway_Identity').set_value('Recent graduate').run()
                draft = deepcopy(page.session_state['pathway_draft'])
                for code in LANGUAGES:
                    self.switch(page, code)
                    self.assertEqual(page.session_state['pathway_draft'], draft)
                self.switch(page, language)
                page.button(key='pathway_sample').click().run()
                self.healthy(page)
                self.assertTrue(any(item.value == self.text(language, 'Career matches')
                                    for item in page.subheader))
                page.selectbox(key='learning_role').set_value('15-2051.00').run()
                page.selectbox(key='learning_hours').set_value(8).run()
                task = next(box.key for box in page.checkbox if box.key.startswith('learning_check_'))
                page.checkbox(key=task).check().run()
                page.run()
                snapshots = {key: deepcopy(page.session_state[key]) for key in
                             ('pathway_confirmed', 'pathway_assessment', 'learning_progress')}
                for code in LANGUAGES:
                    self.switch(page, code)
                    for key, value in snapshots.items():
                        self.assertEqual(page.session_state[key], value, key)
                    self.assertTrue(page.checkbox(key=task).value)
                    self.assertEqual(page.selectbox(key='learning_hours').value, 8)
                page.button(key='pathway_identity').click().run()
                page.button(key='pathway_start').click().run()
                self.healthy(page)
                self.assertEqual(page.session_state['pathway_draft'], draft)

    def test_default_and_all_questionnaire_pages(self):
        page = self.page()
        self.assertEqual(page.session_state['ui_language'], 'en')
        self.assertEqual(page.button(key='pathway_start').label, 'Complete a CV questionnaire')
        for language in LANGUAGES:
            self.switch(page, language)
            self.assertTrue(any(self.text(language, '### Navigate change. Shape your future.') == item.value
                                for item in page.markdown))
            self.assertEqual(page.button(key='pathway_start').label, self.text(language, 'Complete a CV questionnaire'))
            page.button(key='pathway_start').click().run()
            for step in range(1, 7):
                page.session_state['pathway_step'] = step
                page.run()
                self.healthy(page, allow_error=step == 6)
                self.assertTrue(any(item.value == self.text(language, STEPS[step]) for item in page.subheader))
                if step == 1:
                    self.assertEqual(page.radio(key='pathway_Identity').label, self.text(language, 'Identity'))
                    self.assertIn(self.text(language, 'Current student'), page.radio(key='pathway_Identity').options)
                elif step == 2:
                    self.assertEqual(page.radio(key='pathway_skill_04').label, self.text(language, 'Programming'))
                    self.assertEqual(page.radio(key='pathway_skill_04').options, ['0', '1', '2', '3', '4'])
                elif step == 4:
                    self.assertEqual(page.radio(key='pathway_R1').label, self.text(language, INTERESTS[0][1]))
                elif step == 6:
                    self.assertTrue(any(self.text(language, 'Complete scoring questions before confirming: ') in item.value
                                        for item in page.error))
            page.button(key='pathway_identity').click().run()
        self.assertEqual(self.page().session_state['ui_language'], 'en')

    def test_start_with_legacy_display_name(self):
        from streamlit.testing.v1 import AppTest
        for saved, code in (('English', 'en'), ('中文', 'zh'), ('Bahasa Melayu', 'ms')):
            page = AppTest.from_file(str(app.ROOT/'app.py'))
            page.session_state['ui_language'] = saved
            page.run()
            self.healthy(page)
            self.assertEqual(page.selectbox(key='ui_language').value, code)
            self.switch(page, 'zh')
            self.switch(page, 'ms')
            self.switch(page, 'en')

    def test_invalid_saved_language_recovers_before_widget_creation(self):
        from streamlit.testing.v1 import AppTest
        for saved in ('obsolete', '', None, 42, ['zh']):
            with self.subTest(saved=saved):
                page = AppTest.from_file(str(app.ROOT/'app.py'))
                page.session_state['ui_language'] = saved
                page.run()
                self.healthy(page)
                self.assertEqual(page.selectbox(key='ui_language').value, 'en')
                for code in ('zh', 'ms', 'en'):
                    self.switch(page, code)

    def test_answers_confirmation_and_raw_text_survive_switch(self):
        page = self.page()
        page.button(key='pathway_start').click().run()
        page.radio(key='pathway_Identity').set_value('Recent graduate').run()
        goal = 'Programming · 原文自由文本'
        page.text_area(key='pathway_Optional career goal').set_value(goal).run()
        draft = deepcopy(page.session_state['pathway_draft'])
        for code in ('zh', 'ms', 'en'):
            self.switch(page, code)
            self.assertEqual(page.radio(key='pathway_Identity').value, 'Recent graduate')
            self.assertEqual(page.text_area(key='pathway_Optional career goal').value, goal)
            self.assertEqual(page.session_state['pathway_draft'], draft)
        page.button(key='pathway_next').click().run()
        page.radio(key='pathway_skill_04').set_value(3).run()
        page.session_state['pathway_confirmed'] = {'preserved': True}
        for code in ('zh', 'ms', 'en'):
            self.switch(page, code)
            self.assertEqual(page.radio(key='pathway_skill_04').value, 3)
            self.assertEqual(page.session_state['pathway_draft']['skill_04'], 3)
            self.assertEqual(page.session_state['pathway_confirmed'], {'preserved': True})

    def test_sample_results_tasks_and_reassessment_snapshots_survive(self):
        page = self.page()
        page.button(key='pathway_sample').click().run()
        self.healthy(page)
        page.selectbox(key='learning_role').set_value('15-2051.00').run()
        page.selectbox(key='learning_hours').set_value(8).run()
        key = next(box.key for box in page.checkbox if box.key.startswith('learning_check_'))
        page.checkbox(key=key).check().run()
        page.run()
        profile = deepcopy(page.session_state['pathway_confirmed'])
        current = deepcopy(page.session_state['pathway_assessment'])
        progress = deepcopy(page.session_state['learning_progress'])
        baseline_export = export_plan(current, current['plans']['15-2051.00']['plan'],
                                      current['plans']['15-2051.00']['completion'], '2026-10-22T00:00:00+00:00')
        for language in ('zh', 'ms', 'en'):
            self.switch(page, language)
            self.assertEqual(page.session_state['pathway_confirmed'], profile)
            self.assertEqual(page.session_state['pathway_assessment'], current)
            self.assertEqual(page.session_state['learning_progress'], progress)
            self.assertTrue(page.checkbox(key=key).value)
            self.assertEqual(page.selectbox(key='learning_hours').value, 8)
            self.assertTrue(any(item.value == self.text(language, 'Your four-week practice plan') for item in page.subheader))
            self.assertEqual(page.button(key='pathway_reassess').label, self.text(language, 'Update my profile and reassess'))
            self.assertEqual(page.get('download_button')[0].proto.label, self.text(language, 'Download my plan'))
            self.assertTrue(any(self.text(language, PRACTICE['skill_04'][0]) in item.value for item in page.markdown))
        page.button(key='pathway_reassess').click().run()
        page.session_state['pathway_draft']['skill_04'] = 4
        page.session_state['pathway_step'] = 6
        page.run()
        page.button(key='pathway_confirm').click().run()
        self.healthy(page)
        previous = deepcopy(page.session_state['pathway_previous'])
        reassessed = deepcopy(page.session_state['pathway_assessment'])
        for code in ('zh', 'ms', 'en'):
            self.switch(page, code)
            self.assertEqual(page.session_state['pathway_previous'], previous)
            self.assertEqual(page.session_state['pathway_assessment'], reassessed)
            self.assertTrue(any(item.value == self.text(code, 'What changed since your last assessment?') for item in page.subheader))
        self.assertEqual(export_plan(current, current['plans']['15-2051.00']['plan'],
                                     current['plans']['15-2051.00']['completion'], '2026-10-22T00:00:00+00:00'), baseline_export)

    def test_removed_intro_elements_are_absent_in_all_public_modes_and_languages(self):
        removed_keys = (
            'Start with Career pathway prototype for the guided student questionnaire. Use Synthetic simulation to edit a demo profile and compare two career scenarios. GitHub activity scores are not hiring demand or employment-growth forecasts.',
            'Prototype simulation — not a labour-market prediction',
            '<div class="eyebrow">Students & Recent Graduates · Career exploration</div>',
        )
        removed_texts = [CATALOGS[code][key] for code in LANGUAGES for key in removed_keys]
        # Also detect the eyebrow text if its HTML wrapper is changed.
        removed_texts.extend(text.split('>', 1)[1].rsplit('<', 1)[0]
                             for text in removed_texts[:] if text.startswith('<div'))

        def assert_absent(page):
            self.healthy(page)
            text = '\n'.join(item.value for kind in ('markdown', 'info', 'warning', 'caption', 'text')
                             for item in page.get(kind))
            for removed in removed_texts:
                self.assertNotIn(removed, text)

        for code in LANGUAGES:
            with self.subTest(language=code):
                page = self.page()
                self.switch(page, code)
                page.radio(key='page_mode').set_value('Career pathway prototype').run()
                assert_absent(page)
                page.button(key='pathway_sample').click().run()
                assert_absent(page)
                self.assertTrue(page.session_state['pathway_assessment'])
                page.radio(key='page_mode').set_value('Synthetic simulation').run()
                assert_absent(page)
                if 'simulation_profile' not in page.session_state:
                    page.checkbox(key='simulation_confirm').check()
                    page.button[0].click().run()
                assert_absent(page)
                self.assertEqual(len(page.get('progress')), 6)

    def test_simulation_and_audit_all_languages_without_requests(self):
        page = self.page()
        page.radio(key='page_mode').set_value('Synthetic simulation').run()
        page.checkbox(key='simulation_confirm').check()
        page.button[0].click().run()
        self.healthy(page)
        profile = deepcopy(page.session_state['simulation_profile'])
        trends = deepcopy(page.session_state['simulation_trends'])
        for code in ('zh', 'ms', 'en'):
            self.switch(page, code)
            self.assertEqual(len(page.radio(key='page_mode').options), 2)
            self.assertFalse(any('O*NET' in item.value for item in page.info))
            self.assertEqual(page.session_state['simulation_profile'], profile)
            self.assertEqual(page.session_state['simulation_trends'], trends)
            self.assertEqual(len(page.get('progress')), 6)
            self.assertTrue(any(item.value == self.text(code, '01 / Your demo profile') for item in page.subheader))
            from streamlit.testing.v1 import AppTest
            audit = AppTest.from_file(str(app.ROOT/'scripts/onet_audit.py')).run()
            self.switch(audit, code)
            self.healthy(audit)
            self.assertTrue(any(item.value == self.text(code, 'Ten occupations · source component availability') for item in audit.subheader))
            self.assertEqual(len(audit.dataframe), 30)
            self.assertEqual(audit.button(key='github_refresh_15-2051.00').label, self.text(code, 'Refresh'))
            self.assertEqual(len(audit.table[0].value), 10)
            page.radio(key='page_mode').set_value('Synthetic simulation').run()

    def test_successful_github_evidence_is_stable_in_all_languages(self):
        from test_github_trends import response
        self.client.opener = Mock(side_effect=[response(23), response(19), response(7), response(5)])
        page = self.page()
        page.button(key='pathway_sample').click().run()
        page.button(key='evidence_refresh').click().run()
        self.healthy(page)
        evidence = deepcopy(page.session_state['pathway_evidence'])
        self.assertEqual(self.client.opener.call_count, 4)
        for code in ('zh', 'ms', 'en'):
            self.switch(page, code)
            self.assertEqual(page.session_state['pathway_evidence'], evidence)
            self.assertEqual(self.client.opener.call_count, 4)
            self.assertTrue(any(self.text(code, 'Trend evidence for your recommendations') == item.value
                                for item in page.subheader))
            from streamlit.testing.v1 import AppTest
            audit = AppTest.from_file(str(app.ROOT/'scripts/onet_audit.py')).run()
            self.switch(audit, code)
            self.healthy(audit)
            count_column = self.text(code, 'Repository count')
            counts = [int(value) for table in audit.table if count_column in table.value
                      for value in table.value[count_column]]
            self.assertEqual(counts, [19, 23, 5, 7])
            page.radio(key='page_mode').set_value('Career pathway prototype').run()
            self.healthy(page)

    def test_restore_preview_progress_and_state_survive_language_changes(self):
        from test_plan_transfer import fixture
        assessment, plan, completion = fixture()
        upload = BytesIO(export_plan(assessment, plan, completion).encode())
        def uploader(*args, **kwargs):
            return upload if kwargs.get('key') == 'restore_plan_upload' else None
        with patch('streamlit.file_uploader', side_effect=uploader):
            page = self.page()
            page.button(key='profile_restore').click().run()
            for code in ('zh', 'ms', 'en'):
                self.switch(page, code)
                self.assertNotIn('pathway_confirmed', page.session_state)
                self.assertEqual(page.button(key='restore_plan_confirm').label, self.text(code, 'Confirm restore and open my plan'))
            page.button(key='restore_plan_confirm').click().run()
            self.healthy(page)
            current = deepcopy(page.session_state['pathway_assessment'])
            restore_state = deepcopy(page.session_state['saved_before_restore'])
            for code in ('zh', 'ms', 'en'):
                self.switch(page, code)
                self.assertTrue(page.session_state['pathway_restored'])
                self.assertEqual(page.session_state['saved_before_restore'], restore_state)
                self.assertEqual(page.session_state['pathway_assessment'], current)
                self.assertEqual(sum(box.value for box in page.checkbox), 1)

    def test_invalid_restore_errors_are_localized(self):
        def uploader(*args, **kwargs):
            return BytesIO(b'{"format_version":"wrong"}') if kwargs.get('key') == 'restore_plan_upload' else None
        with patch('streamlit.file_uploader', side_effect=uploader):
            from streamlit.testing.v1 import AppTest
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='restore')
            for code in ('zh', 'ms', 'en'):
                self.switch(page, code, allow_error=True)
                self.assertTrue(any(self.text(code, 'Cannot restore this file: ') + self.text(code, 'Unsupported plan format version') == item.value
                                    for item in page.error))

    def test_cv_consent_payload_and_evidence_remain_original(self):
        from test_cv_intake import CONFIG, SOURCE, extraction, reply
        from src.cv_client import validate_extraction
        upload = BytesIO(b'%PDF-1.7 synthetic'); upload.name = 'synthetic.pdf'
        def uploader(*args, **kwargs):
            return upload if kwargs.get('key', '').startswith('cv_pdf_upload_') else None
        with patch('streamlit.file_uploader', side_effect=uploader), \
             patch('src.cv_intake.extract_pdf', return_value=SOURCE), \
             patch('src.cv_intake.AIConfig.from_env', return_value=CONFIG):
            page = self.page()
            page.button(key='profile_cv').click().run()
            consent_key = next(box.key for box in page.checkbox if box.key.startswith('cv_consent_'))
            page.checkbox(key=consent_key).check().run()
            for code in ('zh', 'ms', 'en'):
                self.switch(page, code)
                self.assertTrue(page.checkbox(key=consent_key).value)
                self.assertFalse(page.button(key='cv_extract').disabled)
                self.assertTrue(any(item.value == SOURCE for item in page.text))
            from src.cv_client import extract_with_ai
            payloads = []
            for code in LANGUAGES:
                set_language(code)
                opener = Mock(return_value=reply())
                extract_with_ai(SOURCE, True, app.LABELS, config=CONFIG, opener=opener)
                payloads.append(opener.call_args.args[0].data)
            set_language('en')
            self.assertEqual(payloads[0], payloads[1])
            self.assertEqual(payloads[0], payloads[2])
        review = validate_extraction(extraction(), SOURCE, app.LABELS)
        page = self.page()
        page.button(key='profile_cv').click().run()
        page.session_state['cv_review'] = review
        page.run()
        page.selectbox(key='cv_rating_skill_04').set_value(2).run()
        page.text_area(key='cv_edit_experience_0').set_value('Original manual note').run()
        page.checkbox(key='cv_review_confirm').check().run()
        for code in ('zh', 'ms', 'en'):
            self.switch(page, code)
            self.assertEqual(page.session_state['cv_review'], review)
            self.assertEqual(page.selectbox(key='cv_rating_skill_04').value, 2)
            self.assertEqual(page.text_area(key='cv_edit_experience_0').value, 'Original manual note')
            self.assertTrue(page.checkbox(key='cv_review_confirm').value)
            self.assertTrue(any(extraction()['skills'][0]['evidence'] in item.value for item in page.markdown))
            self.assertEqual(page.session_state['pathway_draft'], {})
