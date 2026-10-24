"""Source-version, occupation mapping, sensitivity and last-good-cache checks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from app import load_onet
from src.career_pool import official_ranking
from src.official_labor_evidence import (
    CAREERS, build_snapshot, exact_comparison, load_snapshot, parse_bls_table,
    parse_onet_crosswalk, refresh_snapshot, validate_snapshot,
)
from src.pathway import confirmed_profile
from test_pathway import answers


ROOT = Path(__file__).resolve().parents[1]


def fixture_sources(information_security=21.0, operations=11.9, environmental=6.3):
    bls = {
        '13-1199': ('Business operations specialists, all other', 1157.6, 1202.3, 44.7, 3.9, 98.7),
        '15-1212': ('Information security analysts', 192.9, 233.4, 40.6, information_security, 14.1),
        '15-2031': ('Operations research analysts', 113.1, 126.6, 13.5, operations, 7.5),
        '17-2081': ('Environmental engineers', 39.1, 41.6, 2.4, environmental, 2.3),
        '17-2199': ('Engineers, all other', 166.7, 173.0, 6.2, 3.7, 8.8),
    }
    rows = []
    for code, (title, start, end, change, pct, openings) in bls.items():
        values = [title, code, 'Line item', str(start), str(end), '0.0', '0.0', str(change),
                  str(pct), '—', str(openings), '100,000', "Bachelor's degree", 'None', 'None', '—']
        rows.append('<tr>' + ''.join(f'<td>{v}</td>' for v in values) + '</tr>')
    titles = {
        '13-1199.05': ('Sustainability Specialists', '13-1199', 'Business Operations Specialists, All Other'),
        '15-1212.00': ('Information Security Analysts', '15-1212', 'Information Security Analysts'),
        '15-2031.00': ('Operations Research Analysts', '15-2031', 'Operations Research Analysts'),
        '17-2081.00': ('Environmental Engineers', '17-2081', 'Environmental Engineers'),
        '17-2199.03': ('Energy Engineers, Except Wind and Solar', '17-2199', 'Engineers, All Other'),
        '17-2199.08': ('Robotics Engineers', '17-2199', 'Engineers, All Other'),
    }
    crosswalk = ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in (code, *value)) + '</tr>'
                        for code, value in titles.items())
    faq = ('The most recent projections are for 2025–35 and were released on the BLS website '
           'on August 27, 2026.')
    return '<table>' + ''.join(rows) + '</table>', '<table>' + crosswalk + '</table>', faq


class OfficialLaborEvidenceTests(unittest.TestCase):
    def test_bundled_snapshot_matches_current_official_html_rows(self):
        snapshot = load_snapshot()
        self.assertEqual(snapshot['release_date'], '2026-08-27')
        self.assertEqual(snapshot['period'], '2025-2035')
        self.assertEqual(set(snapshot['careers']), set(CAREERS))
        self.assertEqual(snapshot['careers']['15-1212.00']['projection']['employment_change_percent'], 21.0)
        self.assertEqual(snapshot['careers']['15-2031.00']['projection']['employment_change_percent'], 11.9)
        self.assertEqual(snapshot['careers']['17-2081.00']['projection']['employment_change_percent'], 6.3)
        self.assertEqual(snapshot['careers']['13-1199.05']['mapping_precision'], 'aggregate')
        self.assertEqual(snapshot['careers']['17-2199.03']['soc_code'], '17-2199')
        self.assertEqual(snapshot['careers']['17-2199.08']['soc_code'], '17-2199')

    def test_html_parser_builds_versioned_snapshot_from_real_source_shape(self):
        table, crosswalk, faq = fixture_sources()
        parsed = parse_bls_table(table)
        self.assertEqual(parsed['15-1212']['employment_change_percent'], 21.0)
        self.assertEqual(parse_onet_crosswalk(crosswalk)['17-2199.08']['soc_code'], '17-2199')
        snapshot = build_snapshot(table, crosswalk, faq, retrieved_at='2026-10-23T00:00:00+00:00')
        validate_snapshot(snapshot)
        self.assertEqual(snapshot['retrieved_at'], '2026-10-23T00:00:00+00:00')
        self.assertEqual(snapshot['release_date'], '2026-08-27')
        self.assertEqual(snapshot['careers']['17-2199.03']['mapping_precision'], 'aggregate')

    def test_refresh_is_atomic_and_keeps_last_good_snapshot_on_failure(self):
        original = load_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_text(json.dumps(original), encoding='utf-8')
            before = path.read_bytes()
            with self.assertRaises(OSError):
                refresh_snapshot(path, fetch=lambda _: (_ for _ in ()).throw(OSError('offline')))
            self.assertEqual(path.read_bytes(), before)
            table, crosswalk, faq = fixture_sources(information_security=22.0)
            data = {url: value for url, value in zip(('table', 'crosswalk', 'faq'),
                                                      (table, crosswalk, faq))}
            calls = iter(data.values())
            updated = refresh_snapshot(path, fetch=lambda _: next(calls),
                                       retrieved_at='2026-10-24T00:00:00+00:00')
            self.assertEqual(load_snapshot(path), updated)
            self.assertEqual(updated['careers']['15-1212.00']['projection']['employment_change_percent'], 22.0)
        future_faq = 'The most recent projections are for 2026–36 and were released on the BLS website on August 26, 2027.'
        future = build_snapshot(table, crosswalk, future_faq, retrieved_at='2027-01-01T00:00:00+00:00')
        self.assertEqual(future['period'], '2026-2036')
        self.assertEqual((future['base_year'], future['target_year']), (2026, 2036))

    def test_two_controlled_snapshots_change_evidence_and_sensitivity_only(self):
        profile = confirmed_profile(answers())
        rows = [row for row in official_ranking(profile, load_onet()) if row['personal_rank'] is not None]
        first = load_snapshot()
        second = deepcopy(first)
        second['careers']['15-1212.00']['projection']['employment_change_percent'] = 2.0
        second['careers']['17-2081.00']['projection']['employment_change_percent'] = 25.0
        second['data_status'] = 'controlled_test_fixture'
        before, after = exact_comparison(rows, first), exact_comparison(rows, second)
        a, b = {item['code']: item for item in before}, {item['code']: item for item in after}
        self.assertEqual(set(a), {'15-1212.00', '15-2031.00', '17-2081.00'})
        self.assertNotEqual(a['15-1212.00']['normalized_projection'], b['15-1212.00']['normalized_projection'])
        self.assertNotEqual(a['17-2081.00']['result']['combined'],
                            b['17-2081.00']['result']['combined'])
        self.assertNotEqual(a['15-1212.00']['result']['rank'],
                            b['15-1212.00']['result']['rank'])
        self.assertEqual(a['15-1212.00']['personal_fit'], b['15-1212.00']['personal_fit'])

    def test_weight_sensitivity_reports_stable_and_changed_rankings(self):
        from types import SimpleNamespace
        rows = [{'code': code, 'P': SimpleNamespace(value=value)} for code, value in (
            ('15-1212.00', 89.7374621023427),
            ('15-2031.00', 81.51301495081809),
            ('17-2081.00', 84.31462510599013),
        )]
        snapshot = load_snapshot()
        stable = exact_comparison(rows, snapshot)
        for item in stable:
            self.assertEqual(item['result']['weight'], 0.20)
            self.assertAlmostEqual(item['result']['personal_contribution'], 0.80 * item['personal_fit'])
            self.assertAlmostEqual(item['result']['projection_contribution'], 0.20 * item['normalized_projection'])
            self.assertAlmostEqual(item['result']['combined'],
                                   item['result']['personal_contribution'] + item['result']['projection_contribution'])
        self.assertEqual({x['result']['rank'] for x in stable},
                         {x['sensitivity']['rank'] for x in stable})

        # Controlled hypothetical personal-fit values exercise the UI's changed-rank branch.
        changed_rows = [{'code': code, 'P': SimpleNamespace(value=value)} for code, value in (
            ('15-1212.00', 60), ('15-2031.00', 85), ('17-2081.00', 70),
        )]
        changed = exact_comparison(changed_rows, snapshot)
        self.assertNotEqual({x['code']: x['result']['rank'] for x in changed},
                            {x['code']: x['sensitivity']['rank'] for x in changed})

    def test_sensitivity_ui_explains_stability_or_only_shows_rank_delta(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from src.career_pool import render_official_labor_evidence
        snapshot = load_snapshot()
        titles = [{'code': code, 'title': item['title']} for code, item in CAREERS.items()]
        def render(values):
            rows = [{'code': code, 'P': SimpleNamespace(value=value)} for code, value in values]
            st = MagicMock(); st.session_state = {}
            with patch('src.career_pool.load_snapshot', return_value=snapshot):
                render_official_labor_evidence(st, rows, {'roles': titles})
            return st
        stable = render([('15-1212.00', 89.74), ('15-2031.00', 81.51), ('17-2081.00', 84.31)])
        self.assertTrue(any('Rankings are stable within the current assumption range.' in str(call)
                            for call in stable.info.call_args_list))
        self.assertEqual(stable.table.call_count, 1)  # Main Result only
        changed = render([('15-1212.00', 60), ('15-2031.00', 85), ('17-2081.00', 70)])
        self.assertEqual(changed.table.call_count, 2)  # Result plus rank movement only
        sensitivity_table = changed.table.call_args_list[-1].args[0]
        self.assertEqual(set(sensitivity_table[0]), {
            'Career', 'Result rank (20%)', 'Rank at 40% evidence weight', 'Rank movement'})

    def test_app_shows_three_exact_evidence_cards_and_preserves_plan_progress(self):
        from streamlit.testing.v1 import AppTest
        page = AppTest.from_file(str(ROOT / 'app.py')).run()
        page.button(key='scenario_explore').click().run()
        page.button(key='pathway_sample').click().run()
        self.assertFalse(page.exception)
        tables = [element.value.to_dict('records') for element in page.table]
        evidence = next(rows for rows in tables if rows and 'BLS projected employment change (%)' in rows[0])
        self.assertEqual(len(evidence), 3)
        self.assertEqual({row['BLS projected employment change (%)'] for row in evidence}, {21.0, 11.9, 6.3})
        self.assertTrue(all('Result' in row and 'Personal contribution (80%)' in row
                            and 'BLS contribution (20%)' in row for row in evidence))
        self.assertFalse(any('Scenario A' in str(row) or 'Scenario B' in str(row) for row in evidence))
        self.assertTrue(any('Rankings are stable within the current assumption range.' in item.value
                            for item in page.info))
        self.assertTrue(any('Aggregate reference only' in item.label for item in page.get('expander')))
        self.assertTrue(any('Assumption variation test' in item.label for item in page.get('expander')))
        page.selectbox(key='learning_role').set_value('15-2031.00').run()
        box = next(item for item in page.checkbox if item.key.startswith('learning_check_'))
        box.check().run()
        old_progress = deepcopy(page.session_state['learning_progress'])
        page.selectbox(key='labor_scenario_career').set_value('17-2081.00').run()
        page.button(key='use_labor_scenario_career').click().run()
        self.assertFalse(page.exception)
        self.assertEqual(page.session_state['learning_role'], '17-2081.00')
        for plan_id, completed in old_progress.items():
            self.assertEqual(page.session_state['learning_progress'][plan_id], completed)
        for language in ('zh', 'ms', 'en'):
            page.session_state['ui_language'] = language; page.run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['learning_role'], '17-2081.00')
            tables = [element.value.to_dict('records') for element in page.table
                      if element.value is not None and len(element.value.to_dict('records'))]
            evidence = next(table for table in tables
                            if 'BLS projected employment change (%)' in table[0]
                            or 'BLS 预测就业变化（%）' in table[0]
                            or 'Perubahan pekerjaan unjuran BLS (%)' in table[0])
            result_heading = {'en':'Result', 'zh':'结果', 'ms':'Keputusan'}[language]
            self.assertIn(result_heading, evidence[0])
            self.assertTrue(any(
                {'en':'Rankings are stable within the current assumption range.',
                 'zh':'在当前假设范围内，排名保持稳定。',
                 'ms':'Kedudukan kekal stabil dalam julat andaian semasa.'}[language] in item.value
                for item in page.info))
            for plan_id, completed in old_progress.items():
                self.assertEqual(page.session_state['learning_progress'][plan_id], completed)

        from unittest.mock import patch
        with patch('src.career_pool.refresh_snapshot', side_effect=OSError('offline')):
            page.button(key='refresh_official_employment_evidence').click().run()
        self.assertFalse(page.exception)
        self.assertTrue(any('previous valid snapshot' in item.value for item in page.warning))
        self.assertEqual(page.session_state['learning_role'], '17-2081.00')
        for plan_id, completed in old_progress.items():
            self.assertEqual(page.session_state['learning_progress'][plan_id], completed)

    def test_controlled_snapshots_change_rendered_scenario_values_without_changing_personal_fit(self):
        from streamlit.testing.v1 import AppTest
        from unittest.mock import patch
        page = AppTest.from_file(str(ROOT / 'app.py')).run()
        page.button(key='scenario_explore').click().run()
        page.button(key='pathway_sample').click().run()
        first, second = load_snapshot(), load_snapshot()
        second = deepcopy(second)
        second['careers']['15-1212.00']['projection']['employment_change_percent'] = 2.0
        second['careers']['17-2081.00']['projection']['employment_change_percent'] = 25.0
        second['data_status'] = 'controlled_test_fixture'
        active = [first]
        def evidence_table():
            return next(element.value.to_dict('records') for element in page.table
                        if element.value is not None and len(element.value.to_dict('records'))
                        and 'BLS projected employment change (%)' in element.value.to_dict('records')[0])
        with patch('src.career_pool.load_snapshot', side_effect=lambda: active[0]):
            page.run()
            before = evidence_table()
            before_fit = {row['Career']: row['Personal fit P (0–100)'] for row in before}
            active[0] = second
            page.run()
            after = evidence_table()
            after_fit = {row['Career']: row['Personal fit P (0–100)'] for row in after}
            self.assertTrue(any('Controlled test data' in item.value for item in page.warning))
        self.assertNotEqual(before, after)
        self.assertEqual(before_fit, after_fit)


if __name__ == '__main__':
    unittest.main()
