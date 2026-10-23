"""Official cohort, null evidence, cross-domain discrimination and existing plans."""
from copy import deepcopy
import json
import unittest
from app import load_onet, load_demo, LABELS, ROOT
from src.career_pool import official_ranking, quality_issues
from src.pathway import confirmed_profile
from src.learning_plan import build_plan
from src.plan_transfer import export_plan, validate_saved_plan
from scripts.prepare_onet import extract_rating
from test_pathway import answers

class CoverageTests(unittest.TestCase):
    def test_real_official_coverage_and_profile_differences(self):
        data = load_onet()
        expected = {'13-1199.05', '15-1212.00', '15-2031.00', '17-2081.00', '17-2199.03', '17-2199.08'}
        self.assertEqual({r['code'] for r in data['roles'] if not quality_issues(r)}, expected)
        profiles = []
        for changes, interest in [({'knowledge_07':4,'skill_10':4,'skill_11':4}, [1,1,2,4,5,4]),
                                 ({'knowledge_03':4,'knowledge_04':4,'skill_08':4,'skill_06':4}, [5,5,1,1,1,1])]:
            draft = {**answers(), **changes}
            for dimension, value in zip('RIASEC', interest):
                draft[dimension+'1'] = draft[dimension+'2'] = value
            profile = confirmed_profile(draft)
            rows = official_ranking(profile, data)
            ranked = [r for r in rows if r['personal_rank']]
            self.assertEqual({r['code'] for r in ranked}, expected)
            self.assertTrue(all(r['trend']['score'].value is None and r['moderate'].value is None for r in rows))
            profiles.append(ranked)
        self.assertEqual(profiles[0][0]['code'], '13-1199.05')
        self.assertEqual(profiles[1][0]['code'], '17-2199.08')
        self.assertNotEqual([r['P'].value for r in profiles[0]], [r['P'].value for r in profiles[1]])
        by_code = {r['code']: r for r in official_ranking(confirmed_profile(answers()), data)}
        self.assertEqual(by_code['15-1212.00']['assessment_coverage']['knowledge'], '5/7')
        self.assertEqual(by_code['15-1212.00']['assessment_coverage']['omitted'], ['Chemistry', 'Biology'])
        self.assertEqual(by_code['15-2031.00']['assessment_coverage']['knowledge'], '6/7')
        self.assertEqual(by_code['15-2031.00']['assessment_coverage']['omitted'], ['Biology'])
        self.assertEqual(by_code['17-2081.00']['assessment_coverage']['knowledge'], '7/7')
        self.assertIsNone(by_code['15-2051.00']['personal_rank'])

    def test_missing_and_suppressed_data_remain_blocked(self):
        data = deepcopy(load_onet());profile = confirmed_profile(answers())
        role = next(r for r in data['roles'] if r['code']=='17-2081.00')
        role['skills']['skill_01']['required'] = None
        row = next(r for r in official_ranking(profile,data) if r['code']==role['code'])
        self.assertIsNone(row['personal_rank']);self.assertIsNone(row['P'].value)
        # A missing user answer also remains unknown, never zero.
        del profile['knowledge']['knowledge_03']
        self.assertTrue(all(r['personal_rank'] is None for r in official_ranking(profile,data)))

    def test_expert_optional_precision_is_not_a_fake_no_flag(self):
        raw={'O*NET-SOC Code':'x','Element ID':'e','Scale ID':'LV','Data Value':'3.5',
             'Recommend Suppress':'','Not Relevant':'N','N':'20','Domain Source':'Occupational Expert'}
        row={'row_number':2,'raw':raw}
        rating=extract_rating([row],'x','e','LV','knowledge')
        self.assertEqual(rating['value'],.5);self.assertEqual(raw['Recommend Suppress'],'')
        for change in ({'Recommend Suppress':'Y'}, {'Domain Source':'Incumbent'}, {'Not Relevant':'Y'}, {'N':'2'}):
            changed={'row_number':2,'raw':{**raw,**change}}
            self.assertIsNone(extract_rating([changed],'x','e','LV','knowledge')['value'])

    def test_official_and_legacy_plan_restore(self):
        a=answers();profile=confirmed_profile(a);data=load_onet();rows=official_ranking(profile,data)
        row=next(r for r in rows if r['personal_rank']);role=next(r for r in data['roles'] if r['code']==row['code'])
        plan=build_plan(row,role,5);completion={plan['tasks'][0]['id']:True}
        saved=export_plan({'answers':a,'profile':profile,'roles':data,'trends':{'topics':{}},'rows':rows},plan,completion)
        prepared=validate_saved_plan(saved.encode(),load_demo)
        self.assertEqual(prepared['plan'],plan)
        self.assertTrue(prepared['completion'][plan['tasks'][0]['id']])

    def test_actual_app_official_default_and_languages(self):
        from streamlit.testing.v1 import AppTest
        from unittest.mock import patch
        page=AppTest.from_file(str(ROOT/'app.py')).run()
        page.button(key='scenario_explore').click().run()
        page.button(key='pathway_sample').click().run()
        self.assertFalse(page.exception)
        self.assertEqual(page.radio(key='career_catalog_mode').value,'Official cross-domain careers')
        coverage_rows = page.table[0].value.to_dict('records')
        self.assertEqual(len(coverage_rows), 6)
        security = next(row for row in coverage_rows if row['Career'] == 'Information Security Analysts')
        self.assertIn('5/7 knowledge', security['Questionnaire coverage'])
        self.assertIn('Chemistry, Biology', security['Questionnaire coverage'])
        self.assertTrue(all(row['moderate'].value is None and row['fast'].value is None
                            for row in page.session_state['pathway_assessment']['rows']))
        page.selectbox(key='learning_role').set_value('17-2081.00').run()
        box=next(b for b in page.checkbox if b.key.startswith('learning_check_'))
        box.check().run()
        saved=deepcopy(page.session_state['pathway_assessment'])
        progress=deepcopy(page.session_state['learning_progress'])
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('unexpected network')):
            for language in ('zh','ms','en'):
                page.selectbox(key='ui_language').set_value(language).run()
                self.assertFalse(page.exception)
                self.assertEqual(page.session_state['pathway_assessment'],saved)
                self.assertEqual(page.session_state['learning_progress'],progress)
                self.assertEqual(page.session_state['learning_role'],'17-2081.00')

    def test_switching_catalogs_requires_confirmation_and_keeps_old_progress(self):
        from streamlit.testing.v1 import AppTest
        page=AppTest.from_file(str(ROOT/'app.py')).run()
        page.button(key='scenario_explore').click().run()
        page.button(key='pathway_sample').click().run()
        page.selectbox(key='learning_role').set_value('17-2081.00').run()
        next(b for b in page.checkbox if b.key.startswith('learning_check_')).check().run()
        old=deepcopy(page.session_state['pathway_assessment']);profile=deepcopy(page.session_state['pathway_confirmed'])
        progress=deepcopy(page.session_state['learning_progress'])
        page.radio(key='career_catalog_mode').set_value('Synthetic demo').run()
        self.assertEqual(page.session_state['pathway_assessment'],old)
        page.button(key='confirm_demo_catalog').click().run()
        self.assertFalse(page.exception)
        self.assertEqual(page.session_state['archived_official_assessment'],old)
        for plan_id, completed in progress.items():
            self.assertEqual(page.session_state['learning_progress'][plan_id],completed)
        self.assertEqual(page.session_state['pathway_confirmed'],profile)
        page.selectbox(key='learning_role').set_value('15-2051.00').run()
        page.radio(key='career_catalog_mode').set_value('Official cross-domain careers').run()
        page.button(key='confirm_official_catalog').click().run()
        self.assertFalse(page.exception)
        for plan_id, completed in progress.items():
            self.assertEqual(page.session_state['learning_progress'][plan_id],completed)
        self.assertEqual(page.session_state['pathway_confirmed'],profile)
