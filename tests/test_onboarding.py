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
                self.assertEqual(page.header[0].value, catalog['Let us get to know you'])
                self.assertEqual(page.button(key='pathway_start').label,
                                 catalog['Complete a CV questionnaire'])
                keys = ['pathway_start', 'profile_cv', 'pathway_sample', 'profile_restore']
                buttons = [b for b in page.button if b.key in keys]
                self.assertEqual([b.key for b in buttons], keys)
                labels = ['Complete a CV questionnaire', 'Recognize a PDF CV with AI',
                          'Try a virtual example', 'Restore a saved plan']
                self.assertEqual([b.label for b in buttons], [catalog[label] for label in labels])
                self.assertTrue(all(not b.disabled and b.proto.type == buttons[0].proto.type for b in buttons))
                # All four buttons are direct siblings, rather than columns or disclosures.
                parents = []
                def walk(node):
                    children = getattr(node, 'children', {})
                    for child in children.values():
                        if getattr(child, 'key', None) in keys:
                            parents.append(id(node))
                        walk(child)
                walk(page._tree)
                self.assertEqual(len(parents), 4)
                self.assertEqual(len(set(parents)), 1)
                self.assertEqual(len(page.get('file_uploader')), 0)
                text = '\n'.join(item.value for kind in ('header', 'subheader', 'markdown', 'info', 'warning', 'caption')
                                 for item in page.get(kind))
                for code in LANGUAGES:
                    for old in ('Choose your identity', '#### Student or recent graduate',
                                'Prototype simulation — not a labour-market prediction'):
                        self.assertNotIn(CATALOGS[code][old].removeprefix('#### '), text)
                page.button(key='profile_cv').click().run()
                self.healthy(page)
                self.assertEqual(len(page.get('file_uploader')), 1)
                self.assertTrue(page.expander[0].proto.expanded)
                self.assertTrue(any(e.label == catalog['Upload a PDF CV'] for e in page.expander))
                page.button(key='profile_restore').click().run()
                self.healthy(page)
                self.assertEqual(len(page.get('file_uploader')), 1)
                self.assertTrue(page.expander[0].proto.expanded)
                self.assertTrue(any(e.label == catalog['Restore a saved plan'] for e in page.expander))

    def test_personal_entries_and_navigation_preserve_drafts(self):
        page = self.page()
        page.button(key='scenario_explore').click().run()
        self.healthy(page)
        self.assertEqual(page.header[0].value, CATALOGS['en']['Let us get to know you'])
        self.assertTrue(page.button(key='pathway_start'))
        self.assertTrue(page.button(key='pathway_sample'))
        self.assertTrue(page.button(key='profile_cv'))
        self.assertTrue(page.button(key='profile_restore'))
        self.assertEqual(len(page.get('file_uploader')), 0)
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
