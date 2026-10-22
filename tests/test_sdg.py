"""SDG evidence and rendering never enter matching or plan data; no external HTTP."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import app
from src.i18n import CATALOGS, LANGUAGES, set_language, validate_catalogs
from src.sdg import CATALOG, associations, render_sdg_details, render_sdg_preview
from src.scoring import rank_roles


class SDGDataTests(unittest.TestCase):
    def tearDown(self):
        set_language('en')

    def test_reviewed_records_have_task_target_sources_and_translations(self):
        validate_catalogs()
        codes = {role['code'] for role in app.load_onet()['roles']}
        self.assertEqual(set(CATALOG['roles']), codes)
        checked = set()
        for code, record in CATALOG['roles'].items():
            mappings = associations(code)
            self.assertLessEqual(len(mappings), 2)
            if not mappings:
                self.assertEqual(record, {'status': 'pending_validation', 'mappings': []})
            for item in mappings:
                checked.add(code)
                self.assertTrue(item['target_id'].startswith(item['sdg_id'] + '.'))
                self.assertTrue(item['task_summary'])
                self.assertIn(code, item['occupation_source'])
                self.assertIn('https://www.onetonline.org/', item['occupation_source'])
                self.assertTrue(item['target_source'].startswith(('https://sdgs.un.org/', 'https://unstats.un.org/')))
                self.assertEqual(item['relation_type'], 'Potential contribution')
                for language in LANGUAGES:
                    self.assertIn(item['reason'], CATALOGS[language])
                    self.assertIn(CATALOG['goals'][item['sdg_id']]['name'], CATALOGS[language])
        self.assertEqual(checked, {'17-2199.03', '17-2081.00', '13-1199.05'})
        self.assertEqual(associations('unknown'), [])

    def test_detail_title_has_a_plain_translation_key_in_all_languages(self):
        key = 'How this pathway can contribute to the SDGs'
        for language in LANGUAGES:
            self.assertIn(key, CATALOGS[language])
            self.assertTrue(CATALOGS[language][key].strip())
            self.assertFalse(CATALOGS[language][key].startswith('#'))
            self.assertNotIn('#### ' + key, CATALOGS[language])

    def test_rendering_and_mapping_changes_cannot_change_scores_or_inputs(self):
        from unittest.mock import MagicMock
        profile, roles, trends = app.load_demo()
        original = deepcopy((profile, roles, trends))
        before = rank_roles(profile, roles['roles'], trends['topics'])
        altered = deepcopy(CATALOG)
        altered['roles']['15-2051.00'] = deepcopy(CATALOG['roles']['17-2199.03'])
        by_code = {role['code']: role for role in roles['roles']}
        with patch('src.sdg.CATALOG', altered):
            for language in LANGUAGES:
                set_language(language)
                for row in before:
                    app.render_role(MagicMock(), row, by_code[row['code']], profile)
            after = rank_roles(profile, roles['roles'], trends['topics'])
        self.assertEqual(before, after)
        self.assertEqual((profile, roles, trends), original)


class SDGPageTests(unittest.TestCase):
    def setUp(self):
        self.http = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No network'))
        self.http.start()
        self.addCleanup(self.http.stop)

    def page(self):
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_file(str(app.ROOT/'app.py')).run()
        self.healthy(page)
        return page

    def healthy(self, page):
        self.assertFalse(page.exception)
        self.assertFalse(page.error)

    def previews(self, page):
        return [item.value for item in page.markdown if 'data-sdg-preview=' in item.value]

    def test_real_app_recovers_stale_catalogs_and_renders_detail_titles(self):
        import src.i18n as i18n
        page = self.page()
        page.button(key='pathway_sample').click().run()
        mappings = deepcopy(CATALOG)
        assessment = deepcopy(page.session_state['pathway_assessment'])
        title = 'How this pathway can contribute to the SDGs'
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            stale = deepcopy(i18n.CATALOGS)
            for catalog in stale.values():
                catalog.pop(title)
            # Streamlit can rerun app.py while keeping src.i18n and its old catalogs.
            with patch.object(i18n, 'CATALOGS', stale):
                page.run()
                self.healthy(page)
                self.assertIn(title, i18n.CATALOGS[language])
            expected = '#### ' + CATALOGS[language][title]
            self.assertEqual(sum(item.value == expected for item in page.markdown), 3)
            self.assertEqual(page.session_state['pathway_assessment'], assessment)
            from streamlit.testing.v1 import AppTest
            audit = AppTest.from_file(str(app.ROOT/'scripts/onet_audit.py')).run()
            audit.selectbox(key='ui_language').set_value(language).run()
            self.healthy(audit)
            self.assertEqual(sum(item.value == expected for item in audit.markdown), 10)
            for code in ('17-2199.03', '15-2051.00'):
                block = next(item for item in audit.expander if item.label.startswith(code + ' · '))
                self.assertTrue(any(item.value == expected for item in block.markdown))
            page.radio(key='page_mode').set_value('Career pathway prototype').run()
            self.healthy(page)
        self.assertEqual(CATALOG, mappings)

    def test_each_pathway_and_simulation_preview_has_pending_slot(self):
        page = self.page()
        page.button(key='pathway_sample').click().run()
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.healthy(page)
            previews = self.previews(page)
            self.assertEqual(len(previews), 6)
            for code in CATALOG['roles']:
                count = sum(f'data-sdg-preview="{code}"' in item for item in previews)
                self.assertEqual(count, 2 if code in ('15-2051.00', '15-2031.00', '15-1252.00') else 0)
            for item in previews:
                self.assertIn(CATALOGS[language]['SDG mapping pending validation'], item)
                self.assertNotIn('border-left:', item)
            page.radio(key='page_mode').set_value('Synthetic simulation').run()
            if 'simulation_profile' not in page.session_state:
                page.checkbox(key='simulation_confirm').check()
                page.button[0].click().run()
            self.healthy(page)
            self.assertEqual(len(self.previews(page)), 6)
            self.assertTrue(all(CATALOGS[language]['SDG mapping pending validation'] in p for p in self.previews(page)))
            page.radio(key='page_mode').set_value('Career pathway prototype').run()

    def test_real_audit_shows_supported_goals_reasons_sources_and_pending(self):
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_file(str(app.ROOT/'scripts/onet_audit.py')).run()
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.healthy(page)
            self.assertEqual(len(self.previews(page)), 10)
            for code, record in CATALOG['roles'].items():
                block = next(item for item in page.expander if item.label.startswith(code + ' · '))
                preview = next(item.value for item in block.markdown if 'data-sdg-preview=' in item.value)
                mappings = associations(code)
                if not mappings:
                    self.assertIn(CATALOGS[language]['SDG mapping pending validation'], preview)
                    self.assertTrue(any(item.value == CATALOGS[language]['SDG mapping pending validation'] for item in block.info))
                    self.assertFalse(any('https://sdgs.un.org/' in item.value for item in block.markdown))
                for item in mappings:
                    self.assertIn('SDG ' + item['sdg_id'], preview)
                    self.assertIn(CATALOGS[language][CATALOG['goals'][item['sdg_id']]['name']], preview)
                    self.assertTrue(any(entry.value == CATALOGS[language][item['reason']] for entry in block.markdown))
                    self.assertTrue(any(item['target_id'] in entry.value for entry in block.markdown))
                    self.assertTrue(any(item['occupation_source'] in entry.value and item['target_source'] in entry.value for entry in block.markdown))
                    self.assertTrue(any(entry.value == CATALOGS[language]['Contribution depends on the actual role and application context.'] for entry in block.markdown))
                self.assertEqual(preview.count('border-left:'), len(mappings))
            self.assertNotIn('simulation_profile', page.session_state)
            self.assertNotIn('pathway_confirmed', page.session_state)

    def test_language_switch_preserves_answers_results_plan_and_progress(self):
        page = self.page()
        page.button(key='pathway_start').click().run()
        page.selectbox(key='pathway_Identity').set_value('Recent graduate').run()
        draft = deepcopy(page.session_state['pathway_draft'])
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.assertEqual(page.session_state['pathway_draft'], draft)
        page.button(key='pathway_sample').click().run()
        page.selectbox(key='learning_role').set_value('15-2051.00').run()
        key = next(box.key for box in page.checkbox if box.key.startswith('learning_check_'))
        page.checkbox(key=key).check().run()
        page.run()
        saved = {key: deepcopy(page.session_state[key]) for key in
                 ('pathway_step', 'pathway_draft', 'pathway_confirmed', 'pathway_assessment', 'learning_progress')}
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.healthy(page)
            for key, value in saved.items():
                self.assertEqual(page.session_state[key], value)
