"""One-click synthetic intake and separation from personal questionnaire drafts."""
from copy import deepcopy
import importlib.util
import unittest
from unittest.mock import patch

import app
from src.pathway import (sample_answers, scoring_errors, confirmed_profile,
                         switch_profile_workspace)
from src.scoring import rank_roles


class SampleTests(unittest.TestCase):
    """A sample is complete and cannot replace the independent manual workspace."""

    def test_complete_rankable_synthetic(self) -> None:
        """All scored questions are supplied and use the existing scoring engine."""
        draft = sample_answers()
        self.assertFalse(scoring_errors(draft))
        profile = confirmed_profile(draft)
        self.assertEqual(profile['data_status'], 'synthetic')
        _, roles, trends = app.load_demo()
        rows = rank_roles(profile, roles['roles'], trends['topics'])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row['moderate_rank'] is not None for row in rows))
        draft['skill_04'] = 4
        self.assertEqual(confirmed_profile(draft)['data_status'], 'synthetic')
        self.assertEqual(sample_answers()['skill_04'], 2)

    def test_workspace_round_trip_preserves_answers_and_snapshots(self) -> None:
        """Sample edits never mutate existing answers, plans, results or progress."""
        state = {'pathway_draft': {'skill_04': 1, 'Optional career goal': 'My existing goal'},
                 'pathway_assessment': {'rows': ['existing']},
                 'learning_progress': {'old': {'task': True}}, 'page_mode': 'Career pathway prototype'}
        original = deepcopy(state)
        switch_profile_workspace(state, 'sample')
        state['pathway_draft'] = sample_answers()
        state['pathway_draft']['skill_04'] = 4
        switch_profile_workspace(state, 'manual')
        for key, value in original.items():
            self.assertEqual(state[key], value)
        switch_profile_workspace(state, 'sample')
        self.assertEqual(state['pathway_draft']['skill_04'], 4)
        self.assertEqual(state['pathway_draft']['data_status'], 'synthetic')


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class SampleUITests(unittest.TestCase):
    """Use the real page, with no server and no real external requests."""

    def test_sample_button_visible_on_identity_and_background(self) -> None:
        """Both a fresh visit and an existing background session have the working shortcut."""
        from streamlit.testing.v1 import AppTest
        for step in (0, 1):
            with self.subTest(step=step), patch('urllib.request.urlopen', side_effect=AssertionError('No HTTP')):
                page = AppTest.from_file(str(app.ROOT/'app.py')).run()
                if step == 1:
                    page.button(key='pathway_start').click().run()
                button = page.button(key='pathway_sample')
                self.assertEqual(button.label, 'Try with a sample profile')
                self.assertFalse(button.disabled)
                if step == 0:
                    self.assertEqual(page.button(key='pathway_start').label, 'Fill in my profile')
                button.click().run()
                self.assertFalse(page.exception)
                self.assertEqual(page.session_state['pathway_step'], 7)
                self.assertEqual(page.session_state['pathway_confirmed']['data_status'], 'synthetic')
                rows = page.session_state['pathway_assessment']['rows']
                self.assertEqual(len(rows), 3)
                self.assertTrue(all(row['moderate_rank'] is not None for row in rows))
                self.assertTrue(any('SAMPLE PROFILE' in warning.value for warning in page.warning))

    def test_one_click_edit_reassess_and_restore_personal_draft(self) -> None:
        """Sample ranks immediately, offers a plan, remains synthetic after editing, and restores manual input."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            page.button(key='pathway_start').click().run()
            page.text_area(key='pathway_Optional career goal').set_value('My saved exploration goal').run()
            page.button(key='pathway_next').click().run()
            page.selectbox(key='pathway_skill_04').set_value(1).run()
            saved = deepcopy(page.session_state['pathway_draft'])
            page.button(key='pathway_identity').click().run()
            page.button(key='pathway_sample').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_step'], 7)
            self.assertEqual(page.session_state['pathway_confirmed']['data_status'], 'synthetic')
            self.assertEqual(len(page.session_state['pathway_assessment']['rows']), 3)
            self.assertTrue(any('SAMPLE PROFILE' in w.value for w in page.warning))
            page.selectbox(key='learning_role').set_value('15-2051.00').run()
            self.assertTrue(page.checkbox)
            page.button(key='pathway_reassess').click().run()
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.selectbox(key='pathway_skill_04').value, 2)
            page.selectbox(key='pathway_skill_04').set_value(4).run()
            page.session_state['pathway_step'] = 6
            page.run()
            page.button(key='pathway_confirm').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_assessment']['profile']['data_status'], 'synthetic')
            self.assertTrue(any('What changed' in item.value for item in page.subheader))
            self.assertEqual(page.session_state['profile_workspaces']['manual']['pathway_draft'], saved)
            page.button(key='pathway_identity').click().run()
            page.button(key='pathway_start').click().run()
            self.assertEqual(page.text_area(key='pathway_Optional career goal').value, 'My saved exploration goal')
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.selectbox(key='pathway_skill_04').value, 1)
            self.assertFalse(any('SAMPLE PROFILE' in w.value for w in page.warning))
            self.assertFalse(page.exception)
