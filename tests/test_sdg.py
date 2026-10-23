"""Static SDG mapping coverage, provenance and three-language presentation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import app
from src.i18n import CATALOGS, LANGUAGES, set_language, validate_catalogs
from src.learning_plan import PRACTICE
from src.official_labor_evidence import CAREERS
from src.sdg import (CATALOG, CAREER_IDS, associations, skill_associations,
                     render_sdg_details, render_local_sdg, validate_career_coverage)
from src.scoring import rank_roles


class SDGDataTests(unittest.TestCase):
    def tearDown(self):
        set_language('en')
    def test_six_official_roles_and_plan_skill_ids_are_reviewed_or_explicitly_unmapped(self):
        validate_catalogs()
        displayed_codes = set(CAREERS) | {'15-1252.00', '15-2051.00'}
        self.assertEqual(displayed_codes, set(CATALOG['unmapped_skill_ids']))
        self.assertEqual(CAREER_IDS, {r['code'] for r in app.load_onet()['roles']})
        self.assertEqual(validate_career_coverage(), CAREER_IDS)
        roles={role['code']:role for role in app.load_onet()['roles']}
        self.assertEqual(len(CAREERS),6)
        for code in displayed_codes:
            record=CATALOG['roles'][code]
            self.assertEqual(record['status'],'analyst_reviewed')
            self.assertTrue(associations(code))
            self.assertTrue(record['mappings'])
            self.assertEqual(record['mappings'][0]['source_checked_on'], '2026-10-23')
            mapped=set(record['skills'])
            unmapped=set(CATALOG['unmapped_skill_ids'][code])
            role_areas=(set(roles[code]['skills'])|set(roles[code]['knowledge'])) if code in CAREERS else set(record.get('plan_area_ids', []))
            possible=set()
            if code in CAREERS:
                for group in ('skills','knowledge'):
                    for area,item in roles[code][group].items():
                        if area in PRACTICE and not item.get('issues') and not any(
                                source.get('issues') for source in item.get('sources',{}).values()):
                            possible.add(area)
            else:
                possible=set(record.get('plan_area_ids', []))
            self.assertEqual(mapped|unmapped,possible)
            self.assertFalse(mapped & unmapped)
            for area in mapped:
                self.assertTrue(skill_associations(code,area))
            for mapping in associations(code):
                self._mapping_is_valid(code,mapping)
            for area,mappings in record['skills'].items():
                self.assertIn(area,PRACTICE)
                self.assertIn(area,role_areas)
                for mapping in mappings:
                    self._mapping_is_valid(code,mapping)
                    self.assertIn('skill_use',mapping)

    def _mapping_is_valid(self,code,mapping):
        self.assertIn(mapping['sdg_id'],CATALOG['goals'])
        self.assertTrue(mapping['target_id'].startswith(mapping['sdg_id']+'.'))
        self.assertEqual(mapping['relation_type'],'Conditional, analyst-reviewed potential contribution')
        self.assertEqual(mapping['source_checked_on'],CATALOG['checked_on'])
        self.assertTrue(mapping['scenario']['en'])
        self.assertTrue(mapping['contribution']['zh'])
        self.assertTrue(mapping['contribution']['ms'])
        self.assertGreaterEqual(len(mapping['source_ids']),3)
        for source_id in mapping['source_ids']:
            source=CATALOG['sources'][source_id]
            self.assertTrue(source['url'].startswith('https://'))
        self.assertIn(code, mapping['source_ids'][0])

    def test_every_target_is_in_the_official_allowlist_and_has_target_link(self):
        expected={'3.4','4.5','6.3','7.3','9.1','9.4','12.2','12.4','12.6'}
        found=set()
        for code in CAREER_IDS:
            for mapping in associations(code):
                found.add(mapping['target_id'])
            for area in CATALOG['roles'][code]['skills']:
                for mapping in skill_associations(code,area):
                    found.add(mapping['target_id'])
        self.assertLessEqual(found,expected)
        for target in found:
            source=CATALOG['sources']['un-target:'+target]
            self.assertIn('sdgs.un.org/goals/goal',source['url'])

    def test_local_rendering_never_changes_scores_or_requests_network(self):
        profile, roles, trends = app.load_demo()
        before_input=deepcopy((profile,roles,trends))
        before=rank_roles(profile,roles['roles'],trends['topics'])
        from unittest.mock import MagicMock
        st=MagicMock()
        st.session_state={'ui_language':'en'}
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No network')):
            render_sdg_details(st,'17-2081.00',{},['skill_05'],{})
        after=rank_roles(profile,roles['roles'],trends['topics'])
        self.assertEqual(before,after)
        self.assertEqual((profile,roles,trends),before_input)
        self.assertTrue(st.expander.called)


class SDGPageTests(unittest.TestCase):
    def setUp(self):
        self.http=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No network'))
        self.http.start(); self.addCleanup(self.http.stop)

    def page(self):
        from ui_helpers import open_personal_profile
        from streamlit.testing.v1 import AppTest
        page=open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
        self.assertFalse(page.exception)
        self.assertFalse(page.error)
        return page

    def test_main_flow_uses_local_mappings_without_ai_configuration(self):
        from streamlit.testing.v1 import AppTest
        page=AppTest.from_file(str(app.ROOT/'app.py')).run()
        page.button(key='scenario_explore').click().run()
        page.button(key='pathway_sample').click().run()
        self.assertFalse(page.exception)
        result_cards=[m.value for m in page.markdown if 'data-sdg-result=' in m.value]
        self.assertEqual(len(result_cards),6)
        self.assertTrue(all(any(code in text for text in result_cards) for code in CAREERS))
        self.assertTrue(any('Reviewed SDG associations' in m.value for m in page.markdown))
        self.assertFalse(any('SDG AI is not configured' in e.value for e in page.info))
        self.assertFalse(any('Generate SDG analysis' in b.label for b in page.button))
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.assertFalse(page.exception)
            visible='\n'.join(str(item.value) for kind in ('markdown','text','caption')
                               for item in page.get(kind))
            cards=[item.value for item in page.markdown if 'data-sdg-result=' in item.value]
            self.assertEqual(len(cards),6)
            mapping=associations('15-2031.00')[0]
            self.assertIn(mapping['contribution'][language],visible)
            goal=CATALOG['goals'][mapping['sdg_id']]['name']
            self.assertIn(CATALOGS[language][goal],visible)
            self.assertNotIn('SDG mapping pending validation',visible)

    def test_synthetic_trend_demo_uses_stable_ids_and_local_sdg_mappings(self):
        from streamlit.testing.v1 import AppTest
        page=AppTest.from_file(str(app.ROOT/'app.py')).run()
        page.radio(key='page_mode').set_value('Synthetic simulation').run()
        page.checkbox(key='simulation_confirm').check()
        page.button[0].click().run()
        self.assertFalse(page.exception)
        previews='\n'.join(x.value for x in page.markdown if 'data-sdg-result=' in x.value)
        for code in ('15-2051.00','15-2031.00','15-1252.00'):
            self.assertIn(f'data-sdg-result="{code}"',previews)
            self.assertTrue(associations(code))
        all_text='\n'.join(x.value for x in page.markdown)
        self.assertIn('4.5',all_text)
        self.assertIn('7.3',all_text)
        self.assertNotIn('No reviewed SDG mapping available',all_text)
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.assertFalse(page.exception)
            localized='\n'.join(str(item.value) for kind in ('markdown','text','caption')
                                 for item in page.get(kind))
            for code in ('15-2051.00','15-2031.00','15-1252.00'):
                self.assertIn(code,'\n'.join(item.value for item in page.markdown
                                              if 'data-sdg-result=' in item.value))
            mapping=associations('15-2051.00')[0]
            self.assertIn(mapping['contribution'][language],localized)

    def test_synthetic_career_catalog_places_all_three_mappings_by_results(self):
        page=self.page();page.button(key='pathway_sample').click().run()
        self.assertFalse(page.exception)
        self.assertEqual(page.radio(key='career_catalog_mode').value,'Synthetic demo')
        cards='\n'.join(x.value for x in page.markdown if 'data-sdg-result=' in x.value)
        for code in ('15-2051.00','15-2031.00','15-1252.00'):
            self.assertIn(code,cards)
            self.assertTrue(associations(code))

    def test_local_mappings_and_expanded_sources_render_in_all_languages(self):
        from streamlit.testing.v1 import AppTest
        page=AppTest.from_file(str(app.ROOT/'scripts/onet_audit.py')).run()
        self.assertFalse(page.exception)
        for language in LANGUAGES:
            page.selectbox(key='ui_language').set_value(language).run()
            self.assertFalse(page.exception)
            self.assertTrue(any(CATALOGS[language]['Reviewed SDG associations'] in x.value for x in page.markdown))
            for code in CAREER_IDS:
                role_block=next(item for item in page.expander if item.label.startswith(code+' · '))
                text='\n'.join(x.value for x in role_block.markdown)
                for mapping in associations(code):
                    self.assertIn(mapping['target_id'],text)
                    source=CATALOG['sources'][mapping['source_ids'][0]]
                    self.assertIn(source['url'],text)
            self.assertNotIn('AI analysis · career and skill links to SDG targets','\n'.join(x.value for x in page.markdown))

    def test_software_and_data_science_demo_ids_show_reviewed_local_mappings(self):
        from unittest.mock import MagicMock
        for language in LANGUAGES:
            set_language(language)
            for code, target, expected_area_ids in (
                ('15-1252.00','4.5',{'skill_01','skill_03','skill_04','knowledge_01','knowledge_02'}),
                ('15-2051.00','7.3',{'skill_01','skill_03','skill_04','knowledge_01','knowledge_02'}),
            ):
                st=MagicMock(); st.session_state={'ui_language':language}
                render_sdg_details(st,code,{},sorted(expected_area_ids),{})
                text='\n'.join(str(call.args[0]) for call in st.markdown.call_args_list + st.write.call_args_list)
                self.assertIn(target,text)
                self.assertIn(CATALOG['roles'][code]['mappings'][0]['scenario'][language],text)
                for area in expected_area_ids:
                    self.assertTrue(skill_associations(code,area))
        set_language('en')

    def test_selected_plan_skill_has_its_own_mapping_or_explicit_gap(self):
        from unittest.mock import MagicMock
        role={r['code']:r for r in app.load_onet()['roles']}['17-2081.00']
        for language in LANGUAGES:
            set_language(language)
            st=MagicMock();st.session_state={'ui_language':language}
            render_sdg_details(st,'17-2081.00',role,['skill_05','knowledge_02'],
                               {'skill_05':'Science','knowledge_02':'Mathematics'})
            written='\n'.join(str(c.args[0]) for c in st.write.call_args_list)
            self.assertIn(CATALOGS[language]['Project team analysis: '],written)
            self.assertIn('6.3', '\n'.join(str(c.args[0]) for c in st.markdown.call_args_list))
            self.assertIn('skill_05', CATALOG['roles']['17-2081.00']['skills'])
        set_language('en')

    def test_official_main_result_and_plan_use_local_mappings_in_all_languages(self):
        from unittest.mock import MagicMock
        from src.career_pool import official_ranking
        dataset=app.load_onet()
        profile={'skills':{f'skill_{i:02}':0 for i in range(1,12)},
                 'knowledge':{f'knowledge_{i:02}':0 for i in range(1,8)},'riasec':[4]*6}
        rows=official_ranking(profile,dataset)
        active=[row for row in rows if row['personal_rank'] is not None]
        roles={role['code']:role for role in dataset['roles']}
        self.assertEqual({row['code'] for row in active},set(CAREERS))
        for language in LANGUAGES:
            set_language(language)
            st=MagicMock();st.session_state={'ui_language':language}
            with patch('src.cv_client.AIConfig.from_env',side_effect=AssertionError('SDG mapping must not need AI')):
                render_local_sdg(st,active,roles,{}, {'answers':{},'selected_hours':3})
            self.assertGreaterEqual(st.expander.call_count,6)
            text='\n'.join(str(call.args[0]) for call in st.write.call_args_list)
            for row in active:
                role_record=CATALOG['roles'][row['code']]
                self.assertIn(role_record['mappings'][0]['scenario'][language],text)
                from src.learning_plan import build_plan
                plan=build_plan(row,roles[row['code']],3)
                for task in plan['tasks']:
                    area=task['area']
                    self.assertTrue(skill_associations(row['code'],area)
                                    or area in CATALOG['unmapped_skill_ids'][row['code']])
        set_language('en')
