"""Rule-generated practice plans and session-only completion; no real HTTP."""
from ui_helpers import open_personal_profile
from copy import deepcopy
import importlib.util
import unittest
from unittest.mock import patch

import app
from src.learning_plan import build_plan, LEARNING_RESOURCES, RESOURCE_BY_SKILL
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

    def test_every_supported_weekly_budget_sums_per_week(self) -> None:
        """Task minutes are per-week allocations, not four weeks of work in one week."""
        for hours in (3, 5, 8, 10):
            with self.subTest(hours=hours):
                plan=build_plan(self.row,self.role,hours)
                self.assertEqual(plan['weekly_hours'],hours)
                for week in range(1,5):
                    week_tasks=[task for task in plan['tasks'] if task['week']==week]
                    self.assertTrue(week_tasks)
                    self.assertEqual(sum(task['minutes'] for task in week_tasks),hours*60)

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

    def test_official_career_gap_resources_budget_and_language_fallback(self) -> None:
        """All six current official roles schedule only real positive gaps and approved resource IDs."""
        from src.career_pool import official_ranking
        from src.learning_plan import resources_for_plan
        dataset = app.load_onet()
        selected_codes = ('13-1199.05', '15-1212.00', '15-2031.00',
                          '17-2081.00', '17-2199.03', '17-2199.08')
        profiles = [confirmed_profile(answers()), confirmed_profile(answers() | {
            **{f'skill_{i:02}': i % 2 for i in range(1, 12)},
            **{f'knowledge_{i:02}': 4 - i % 3 for i in range(1, 8)}})]
        observed = set()
        for profile, hours in zip(profiles, (3, 8)):
            rows = official_ranking(profile, dataset)
            by_code = {role['code']: role for role in dataset['roles']}
            for code in selected_codes:
                row = next(item for item in rows if item['code'] == code)
                plan = build_plan(row, by_code[code], hours, 'Chinese')
                self.assertTrue(plan['tasks'])
                for week in range(1, 5):
                    week_tasks = [task for task in plan['tasks'] if task['week'] == week]
                    self.assertEqual(sum(task['minutes'] for task in week_tasks), hours * 60)
                    self.assertTrue(all(task['resource_study_minutes'] + task['project_minutes'] == task['minutes']
                                        for task in week_tasks))
                for task in plan['tasks']:
                    gap = next(item for item in row[task['group']]['gaps'] if item['id'] == task['area'])
                    self.assertGreater(gap['gap'], 0)
                    if task['resource_id']:
                        resource = LEARNING_RESOURCES[task['resource_id']]
                        self.assertIn(task['area'], resource['skill_ids'])
                        self.assertIn('en', resource['teaching_languages'])
                        self.assertEqual(resource['verified_on'], '2026-10-23')
                        observed.add(task['area'])
                resources = resources_for_plan(plan)
                self.assertEqual(len(resources), len({r['id'] for r in resources}))
                self.assertEqual(plan['id'], build_plan(row, by_code[code], hours, 'Bahasa Malaysia')['id'])
        self.assertGreaterEqual(len(observed), 6)

    def test_resource_catalog_records_provenance_and_no_invented_duration(self) -> None:
        """Unknown source duration stays unknown and every mapped ID resolves to a dated source record."""
        self.assertIn('mit-ocw-15-053', LEARNING_RESOURCES)
        self.assertIsNone(LEARNING_RESOURCES['mit-ocw-15-053']['official_duration_minutes'])
        self.assertEqual(set(RESOURCE_BY_SKILL) - set(app.LABELS), set())
        for resource in LEARNING_RESOURCES.values():
            for key in ('id', 'name', 'provider', 'url', 'skill_ids', 'teaching_languages',
                        'prerequisites', 'cost', 'duration_basis', 'verified_on'):
                self.assertTrue(resource[key])


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class PlanUITests(unittest.TestCase):
    """Select a matched occupation and track completion in real Streamlit session state."""

    def test_selection_budget_completion_and_navigation(self) -> None:
        """Completion survives role switches; time changes create distinct plans, scores stay fixed."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')):
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
            draft = answers() | {'Weekly learning time': '5 hours'}
            page.session_state['pathway_draft'] = draft
            page.session_state['pathway_confirmed'] = confirmed_profile(draft)
            page.session_state['pathway_step'] = 7
            page.run()
            self.assertFalse(page.exception)
            self.assertFalse(page.checkbox)
            page.selectbox(key='learning_role').set_value('17-2081.00').run()
            self.assertFalse(page.exception)
            self.assertEqual(page.selectbox(key='learning_hours').value, 5)
            count = len(page.checkbox)
            self.assertEqual(count, 8)
            scores = [item.value for item in page.markdown if '/ 100' in item.value]
            key = page.checkbox[0].key
            page.checkbox(key=key).check().run()
            self.assertTrue(any(f'1 / {count} tasks completed' in p.proto.text for p in page.get('progress')))
            page.selectbox(key='learning_role').set_value('13-1199.05').run()
            self.assertFalse(any(box.value for box in page.checkbox))
            page.selectbox(key='learning_role').set_value('17-2081.00').run()
            self.assertTrue(page.checkbox(key=key).value)
            page.selectbox(key='learning_hours').set_value(3).run()
            self.assertEqual(len(page.checkbox), 4)
            self.assertFalse(any(box.value for box in page.checkbox))
            self.assertEqual(scores, [item.value for item in page.markdown if '/ 100' in item.value])
            self.assertFalse(page.exception)
            saved_plan = page.session_state['pathway_assessment']['plans']['17-2081.00']['plan']
            self.assertTrue(all(task['area'] in app.LABELS for task in saved_plan['tasks']))
            self.assertTrue(all(task['step_id'] in (1, 2, 3, 4) for task in saved_plan['tasks']))
            # Coverage already meets all synthetic requirements: no task widgets are fabricated.
            full = answers() | {key: 4 for key in app.LABELS}
            page.session_state['pathway_confirmed'] = confirmed_profile(full)
            page.run()
            self.assertFalse(page.checkbox)
            self.assertTrue(any('A plan cannot be generated' in info.value for info in page.info))

    def test_official_resources_render_in_three_languages_and_keep_progress(self) -> None:
        """Official gaps show verified sources; locale changes preserve role, plan and checks."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('No external HTTP in UI test')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            page.button(key='scenario_explore').click().run()
            page.button(key='pathway_sample').click().run()
            page.selectbox(key='learning_role').set_value('17-2081.00').run()
            self.assertFalse(page.exception)
            page.session_state['pathway_draft']['Preferred learning language'] = 'Chinese'
            page.run()
            self.assertTrue(any('No matched resources were verified' in item.value for item in page.info))
            plan = page.session_state['pathway_assessment']['plans']['17-2081.00']['plan']
            self.assertTrue(any(task.get('resource_id') for task in plan['tasks']))
            plan_id = plan['id']
            box = next(item for item in page.checkbox if item.key.startswith('learning_check_'))
            box.check().run()
            self.assertEqual(sum(page.session_state['learning_progress'][plan_id].values()), 1)
            for language in ('zh', 'ms', 'en'):
                page.session_state['ui_language'] = language; page.run()
                self.assertFalse(page.exception)
                self.assertEqual(page.session_state['learning_role'], '17-2081.00')
                self.assertEqual(page.session_state['pathway_assessment']['plans']['17-2081.00']['plan']['id'], plan_id)
                self.assertEqual(sum(page.session_state['learning_progress'][plan_id].values()), 1)
