"""Rule-generated practice plans and session-only completion; no real HTTP."""
from copy import deepcopy
import importlib.util
import unittest
from unittest.mock import patch

import app
from src.learning_plan import build_plan
from src.pathway import confirmed_profile
from src.scoring import Score, rank_roles
from test_pathway import answers


class PlanRulesTests(unittest.TestCase):
    """Check mapping, budget, quality exclusions and no invented gap tasks."""

    def setUp(self) -> None:
        """Compute genuine engine traces from synthetic fixtures."""
        profile, roles, trends = app.load_demo()
        self.roles = {role['code']: role for role in roles['roles']}
        self.rows = rank_roles(profile, roles['roles'], trends['topics'])
        self.row = next(row for row in self.rows if row['code'] == '15-2051.00')
        self.role = self.roles[self.row['code']]

    def test_gap_mapping_budget_reproducibility_and_no_mutation(self) -> None:
        """Every task refers to an actual positive gap and weekly minutes equal budget."""
        before = deepcopy((self.row, self.role))
        small = build_plan(self.row, self.role, 3)
        large = build_plan(self.row, self.role, 10)
        self.assertEqual(small, build_plan(self.row, self.role, 3))
        self.assertNotEqual(small['id'], large['id'])
        self.assertLess(len(small['tasks']), len(large['tasks']))
        self.assertTrue(any(task['group'] == 'knowledge' for task in large['tasks']))
        for plan, hours in ((small, 3), (large, 10)):
            for week in range(1, 5):
                self.assertEqual(sum(t['minutes'] for t in plan['tasks'] if t['week'] == week), hours * 60)
            for task in plan['tasks']:
                gap = next(g for g in self.row[task['group']]['gaps'] if g['id'] == task['area'])
                self.assertGreater(gap['gap'], 0)
                self.assertEqual(task['gap']['gap'], gap['gap'])
                self.assertTrue(task['action'])
                self.assertTrue(task['evidence'])
        self.assertEqual(before, (self.row, self.role))
        other = next(row for row in self.rows if row['code'] != self.row['code'])
        self.assertNotEqual(small['id'], build_plan(other, self.roles[other['code']], 3)['id'])
        with self.assertRaises(ValueError):
            build_plan(self.row, self.roles[other['code']], 3)

    def test_blocked_components_items_and_source_flags_excluded(self) -> None:
        """Even a stale positive gap cannot bypass component or field quality blocks."""
        row, role = deepcopy((self.row, self.role))
        row['skills']['score'] = Score(None, ('Suppressed skill component',))
        plan = build_plan(row, role, 10)
        self.assertTrue(plan['tasks'])
        self.assertTrue(all(t['group'] == 'knowledge' for t in plan['tasks']))
        self.assertTrue(any('Suppressed' in reason for reason in plan['excluded']))
        for flags in ({'issues': ['Not Relevant=Y']},
                      {'sources': {'LV': {'issues': ['Unknown quality']}}}):
            role = deepcopy(self.role)
            role['skills']['skill_04'].update(flags)
            plan = build_plan(self.row, role, 10)
            self.assertFalse(any(t['area'] == 'skill_04' for t in plan['tasks']))
            self.assertTrue(any('skill_04' in reason for reason in plan['excluded']))

    def test_no_gaps_unavailable_and_invalid_budgets(self) -> None:
        """Complete coverage and blocked components never result in fallback exercises."""
        profile = confirmed_profile(answers() | {key: 4 for key in (*app.LABELS,)})
        row = rank_roles(profile, [self.role], app.load_demo()[2]['topics'])[0]
        self.assertEqual(build_plan(row, self.role, 5)['tasks'], [])
        blocked = deepcopy(self.row)
        for group in ('skills', 'knowledge'):
            blocked[group]['score'] = Score(None, ('Missing requirement',))
        plan = build_plan(blocked, self.role, 5)
        self.assertEqual(plan['tasks'], [])
        self.assertEqual(len(plan['excluded']), 2)
        for budget in (0, 4, True):
            with self.assertRaises(ValueError):
                build_plan(self.row, self.role, budget)


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class PlanUITests(unittest.TestCase):
    """Select a matched occupation and track completion in real Streamlit session state."""

    def test_selection_budget_completion_and_navigation(self) -> None:
        """Completion survives role switches; time changes create distinct plans, scores stay fixed."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            draft = answers() | {'Weekly learning time': '5 hours'}
            page.session_state['pathway_draft'] = draft
            page.session_state['pathway_confirmed'] = confirmed_profile(draft)
            page.session_state['pathway_step'] = 7
            page.run()
            self.assertFalse(page.exception)
            self.assertFalse(page.checkbox)
            page.selectbox(key='learning_role').set_value('15-2051.00').run()
            self.assertFalse(page.exception)
            self.assertEqual(page.selectbox(key='learning_hours').value, 5)
            count = len(page.checkbox)
            self.assertEqual(count, 8)
            scores = [item.value for item in page.markdown if '/ 100' in item.value]
            key = page.checkbox[0].key
            page.checkbox(key=key).check().run()
            self.assertTrue(any(f'1 / {count} tasks completed' in p.proto.text for p in page.get('progress')))
            page.selectbox(key='learning_role').set_value('15-1252.00').run()
            self.assertFalse(any(box.value for box in page.checkbox))
            page.selectbox(key='learning_role').set_value('15-2051.00').run()
            self.assertTrue(page.checkbox(key=key).value)
            page.selectbox(key='learning_hours').set_value(3).run()
            self.assertEqual(len(page.checkbox), 4)
            self.assertFalse(any(box.value for box in page.checkbox))
            self.assertEqual(scores, [item.value for item in page.markdown if '/ 100' in item.value])
            self.assertFalse(page.exception)
            self.assertTrue(any('Verified learning resources' in info.value for info in page.info))
            # Coverage already meets all synthetic requirements: no task widgets are fabricated.
            full = answers() | {key: 4 for key in app.LABELS}
            page.session_state['pathway_confirmed'] = confirmed_profile(full)
            page.run()
            self.assertFalse(page.checkbox)
            self.assertTrue(any('A plan cannot be generated' in info.value for info in page.info))
