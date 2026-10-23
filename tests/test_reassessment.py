"""Immutable previous runs, exact component comparisons and the real reassessment journey."""
from ui_helpers import open_personal_profile
from copy import deepcopy
import importlib.util
import unittest
from unittest.mock import patch

import app
from src.pathway import confirmed_profile
from src.reassessment import (begin_reassessment, changed_answers, compare_results,
                              store_assessment, task_changes)
from src.learning_plan import build_plan
from src.scoring import rank_roles
from test_pathway import answers


class ComparisonTests(unittest.TestCase):
    """Check independent snapshots, deterministic deltas and plan changes."""

    def test_snapshots_deltas_and_task_changes(self) -> None:
        """Changed skills affect coverage, fixed trends remain unchanged, old plans survive."""
        _, roles, trends = app.load_demo()
        draft = answers()
        profile = confirmed_profile(draft)
        rows = rank_roles(profile, roles['roles'], trends['topics'])
        state = {}
        old = store_assessment(state, profile, draft, rows, roles, trends)
        self.assertNotIn('pathway_previous', state)
        role = roles['roles'][0]
        row = next(row for row in rows if row['code'] == role['code'])
        plan = build_plan(row, role, 10)
        old['plans'][role['code']] = {'plan': plan, 'completion': {plan['tasks'][0]['id']: True}}
        frozen = deepcopy(old)
        begin_reassessment(state)
        self.assertEqual(state['pathway_draft'], draft)
        state['pathway_draft']['skill_04'] = 4
        self.assertEqual(old, frozen)
        new_draft = state['pathway_draft']
        new_profile = confirmed_profile(new_draft)
        new_rows = rank_roles(new_profile, roles['roles'], trends['topics'])
        current = store_assessment(state, new_profile, new_draft, new_rows, roles, trends)
        self.assertEqual(state['pathway_previous'], frozen)
        self.assertEqual(changed_answers(draft, new_draft), [{'field': 'skill_04', 'before': 2, 'after': 4}])
        comparisons = compare_results(rows, new_rows)
        for comparison in comparisons:
            self.assertEqual(comparison['measures']['Trend signal']['status'], 'Unchanged')
            self.assertGreater(comparison['measures']['Skills coverage']['delta'], 0)
            self.assertIn('Matched to your profile rank', comparison['measures'])
            self.assertIn('Matched to your profile score', comparison['measures'])
        new_row = next(row for row in new_rows if row['code'] == role['code'])
        changes = task_changes(plan, build_plan(new_row, role, 10))
        self.assertTrue(changes['removed'])
        self.assertTrue(changes['adjusted'])
        reverse = task_changes(build_plan(new_row, role, 10), plan)
        self.assertTrue(reverse['added'])
        current['answers']['skill_04'] = 0
        self.assertEqual(state['pathway_previous'], frozen)

    def test_missing_and_unchanged_results(self) -> None:
        """Zero interest remains unavailable in comparisons rather than becoming zero."""
        _, roles, trends = app.load_demo()
        profile = confirmed_profile(answers())
        profile['riasec'] = [0] * 6
        rows = rank_roles(profile, roles['roles'], trends['topics'])
        for comparison in compare_results(rows, rows):
            self.assertIsNone(comparison['measures']['Matched to your profile score']['delta'])
            self.assertEqual(comparison['measures']['Personal fit']['status'], 'Unavailable')
            self.assertEqual(comparison['measures']['Capability']['status'], 'Unchanged')


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class ReassessmentUITests(unittest.TestCase):
    """Drive editing, missing validation, confirmation, before/after and plan update."""

    def test_reassessment_journey(self) -> None:
        """Prefilled answers survive modes; only a new confirmation replaces the current result."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')):
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
            draft = answers()
            page.session_state['pathway_draft'] = draft
            page.session_state['pathway_step'] = 6
            page.run()
            page.button(key='pathway_confirm').click().run()
            self.assertFalse(page.exception)
            self.assertTrue(any('First assessment' in info.value for info in page.info))
            page.selectbox(key='learning_role').set_value('15-2051.00').run()
            page.selectbox(key='learning_hours').set_value(10).run()
            page.checkbox[0].check().run()
            original = deepcopy(page.session_state['pathway_assessment'])
            page.button(key='pathway_reassess').click().run()
            self.assertEqual(page.session_state['pathway_step'], 1)
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.radio(key='pathway_skill_04').value, 2)
            page.radio(key='pathway_skill_04').set_value(4).run()
            page.button(key='pathway_back').click().run()
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.radio(key='pathway_skill_04').value, 4)
            page.radio(key='page_mode').set_value('Synthetic simulation').run()
            page.radio(key='page_mode').set_value('Career pathway prototype').run()
            self.assertEqual(page.radio(key='pathway_skill_04').value, 4)
            page.radio(key='pathway_skill_04').set_value(None).run()
            page.session_state['pathway_step'] = 6
            page.run()
            self.assertTrue(page.error)
            self.assertFalse(any(b.key == 'pathway_confirm' for b in page.button))
            self.assertEqual(page.session_state['pathway_assessment'], original)
            page.session_state['pathway_step'] = 2
            page.run()
            page.radio(key='pathway_skill_04').set_value(4).run()
            page.session_state['pathway_step'] = 6
            page.run()
            page.button(key='pathway_confirm').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_previous'], original)
            self.assertEqual(page.selectbox(key='learning_role').value, '15-2051.00')
            self.assertEqual(page.selectbox(key='learning_hours').value, 10)
            current = page.session_state['pathway_assessment']
            self.assertNotEqual(current['rows'], original['rows'])
            self.assertTrue(any('What changed' in h.value for h in page.subheader))
            self.assertTrue(any('skill' in m.value.lower() and '→' in m.value for m in page.markdown))
            self.assertTrue(any('Removed:' in m.value for m in page.markdown))
            self.assertTrue(original['plans']['15-2051.00']['completion'])
            self.assertFalse(any(box.value for box in page.checkbox))
