"""Public use-case routing, translated placeholders and durable student state."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import app
from src.i18n import CATALOGS, LANGUAGES
from src.onboarding import SCENARIOS


class OnboardingTests(unittest.TestCase):
    def page(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(app.ROOT/'app.py')).run()

    def healthy(self, page):
        self.assertFalse(page.exception)
        self.assertFalse(page.error)

    def test_translated_scenarios_and_isolated_placeholders(self):
        for language in LANGUAGES:
            with self.subTest(language=language), patch('src.pathway.render_cv_intake') as cv, \
                 patch('src.pathway.render_restore') as restore, \
                 patch('src.pathway.rank_roles') as rank:
                page = self.page()
                page.selectbox(key='ui_language').set_value(language).run()
                self.healthy(page)
                catalog = CATALOGS[language]
                self.assertEqual([b.key for b in page.button],
                                 ['scenario_explore', 'scenario_professional', 'scenario_team'])
                self.assertEqual(page.header[0].value, catalog["Let's get started"])
                self.assertTrue(any(item.value == catalog['Choose the direction that best fits your current needs.']
                                    for item in page.markdown))
                for code, title, description in SCENARIOS:
                    self.assertEqual(page.button(key='scenario_' + code).label, catalog[title])
                    self.assertTrue(any(item.value == catalog[description] for item in page.caption))
                self.assertEqual(len(page.get('file_uploader')), 0)
                self.assertEqual(len(page.radio(key='page_mode').options), 2)
                for scenario, count in (('professional', 3), ('team', 2)):
                    page.button(key='scenario_' + scenario).click().run()
                    self.healthy(page)
                    self.assertEqual(page.info[0].value, catalog['Coming soon'])
                    planned = [b for b in page.button if b.key.startswith('planned_')]
                    self.assertEqual(len(planned), count)
                    self.assertTrue(all(b.disabled and catalog['Coming soon'] in b.label for b in planned))
                    if scenario == 'team':
                        self.assertEqual(planned[1].label, catalog['Batch upload'] + ' · ' + catalog['Coming soon'])
                    self.assertEqual(len(page.get('file_uploader')), 0)
                    self.assertFalse(any(b.key.startswith('pathway_') for b in page.button))
                    self.assertNotIn('pathway_step', page.session_state)
                    page.button(key='onboarding_back').click().run()
                    self.assertEqual(page.session_state['onboarding_scenario'], scenario)
                cv.assert_not_called()
                restore.assert_not_called()
                rank.assert_not_called()

    def test_personal_entry_labels_in_all_languages(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                page = self.page()
                page.selectbox(key='ui_language').set_value(language).run()
                page.button(key='scenario_explore').click().run()
                self.healthy(page)
                catalog = CATALOGS[language]
                self.assertEqual(page.header[0].value, catalog['Let us get to know you…'])
                self.assertEqual(page.button(key='pathway_start').label,
                                 catalog['Complete the questionnaire to create a profile'])
                self.assertEqual(page.button(key='pathway_sample').label, catalog['Try with a sample profile'])
                for label in ('Upload a PDF CV', 'Restore a saved plan'):
                    self.assertTrue(any(e.label == catalog[label] for e in page.expander))

    def test_personal_entries_and_navigation_preserve_drafts(self):
        page = self.page()
        page.button(key='scenario_explore').click().run()
        self.healthy(page)
        self.assertEqual(page.header[0].value, CATALOGS['en']['Let us get to know you…'])
        self.assertTrue(page.button(key='pathway_start'))
        self.assertTrue(page.button(key='pathway_sample'))
        self.assertTrue(any(e.label == CATALOGS['en']['Upload a PDF CV'] for e in page.expander))
        self.assertTrue(any(e.label == CATALOGS['en']['Restore a saved plan'] for e in page.expander))
        self.assertEqual(len(page.get('file_uploader')), 2)
        page.button(key='pathway_start').click().run()
        page.selectbox(key='pathway_Identity').set_value('Recent graduate').run()
        page.text_area(key='pathway_Optional career goal').set_value('Keep my goal').run()
        draft = deepcopy(page.session_state['pathway_draft'])
        page.button(key='onboarding_back').click().run()
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.assertEqual(page.session_state['onboarding_scenario'], 'explore')
            self.assertEqual(page.session_state['pathway_draft'], draft)
        page.button(key='scenario_team').click().run()
        page.button(key='onboarding_back').click().run()
        page.button(key='scenario_explore').click().run()
        self.healthy(page)
        self.assertEqual(page.session_state['pathway_step'], 1)
        self.assertEqual(page.session_state['pathway_draft'], draft)
        self.assertEqual(page.text_area(key='pathway_Optional career goal').value, 'Keep my goal')
        page.button(key='pathway_identity').click().run()
        page.button(key='pathway_sample').click().run()
        self.healthy(page)
        self.assertEqual(page.session_state['pathway_step'], 7)
        self.assertTrue(page.session_state['pathway_assessment'])
