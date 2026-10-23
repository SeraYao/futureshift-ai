"""Evidence reassessment with mock HTTP only and real Streamlit interactions."""
from ui_helpers import open_personal_profile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

import app
from src.evidence_reassessment import (refresh_evidence, snapshot_comparison, evidence_ranking)
from src.github_trends import GitHubTrends, ROLE_TOPICS
from src.pathway import sample_answers, confirmed_profile
from test_github_trends import response


def snapshot(code: str, recent: int = 10, previous: int = 100) -> dict:
    """Create authentic-shaped evidence using only mocked search responses."""
    client = GitHubTrends(opener=Mock(side_effect=[response(recent), response(previous),
                                                  response(recent), response(previous)]),
                          now=lambda: datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
    return client.refresh(code)['snapshot']


class EvidenceTests(unittest.TestCase):
    """Test last-success preservation and rule-based evidence-to-score integration."""

    def test_comparison_cache_and_failure(self) -> None:
        """Cache reuse is offline; expired success updates; errors retain both snapshots."""
        time = [datetime(2026, 10, 22, 12, tzinfo=timezone.utc)]
        opener = Mock(side_effect=[response(20), response(100), response(20), response(100)])
        client = GitHubTrends(opener=opener, now=lambda: time[0])
        state = {}
        code = '15-2051.00'
        refresh_evidence(state, client, code)
        old = deepcopy(state['snapshots'][code])
        refresh_evidence(state, client, code)
        self.assertEqual(opener.call_count, 4)
        self.assertEqual(state['snapshots'][code], old)
        self.assertNotIn(code, state['previous'])
        time[0] += timedelta(minutes=16)
        opener.side_effect = [response(100), response(100), response(100), response(100)]
        refresh_evidence(state, client, code)
        self.assertEqual(state['previous'][code], old)
        table = snapshot_comparison(old, state['snapshots'][code], code)
        self.assertEqual(len(table), 4)
        self.assertEqual({r['Recent count'] for r in table}, {20, 100})
        self.assertEqual(len({r['Fetched (UTC)'] for r in table}), 2)
        self.assertTrue(all('Previous window (UTC, end exclusive)' in r for r in table))
        good = deepcopy(state)
        time[0] += timedelta(minutes=16)
        opener.side_effect = URLError('offline')
        result = refresh_evidence(state, client, code)
        self.assertTrue(result['error'])
        self.assertEqual(state['snapshots'], good['snapshots'])
        self.assertEqual(state['previous'], good['previous'])
        with self.assertRaises(ValueError):
            refresh_evidence(state, client, '17-2081.00')

    def test_computable_missing_blocked_and_trend_propagation(self) -> None:
        """Use real-query mappings only; missing/blocked data cannot create a total."""
        profile = confirmed_profile(sample_answers())
        roles = app.load_demo()[1]['roles']
        evidence = {code: snapshot(code) for code in ROLE_TOPICS}
        initial = evidence_ranking(profile, roles, evidence)
        self.assertTrue(all(row['moderate_rank'] is not None for row in initial))
        evidence['15-2051.00'] = snapshot('15-2051.00', 1000, 10)
        changed = evidence_ranking(profile, roles, evidence)
        old = {row['code']: row for row in initial}
        new = {row['code']: row for row in changed}
        self.assertNotEqual(old['15-2051.00']['moderate'], new['15-2051.00']['moderate'])
        self.assertNotEqual(old['15-2051.00']['moderate_rank'], new['15-2051.00']['moderate_rank'])
        self.assertEqual(old['15-2051.00']['P'], new['15-2051.00']['P'])
        missing = evidence_ranking(profile, roles, {})
        self.assertTrue(all(row['moderate_rank'] is None for row in missing))
        official = evidence_ranking(profile, app.load_onet()['roles'], evidence)
        self.assertEqual(len(official), 3)
        self.assertTrue(all(row['moderate_rank'] is None for row in official))
        self.assertTrue(all(row['moderate'].issues for row in official))
        # Quality errors must block a stale non-null requirement as well.
        blocked = deepcopy(roles)
        blocked[0]['skills']['skill_04']['issues'] = ['Suppress=Y']
        row = next(r for r in evidence_ranking(profile, blocked, evidence) if r['code'] == blocked[0]['code'])
        self.assertIsNone(row['moderate'].value)
        self.assertNotIn('topic:', str(roles))  # Original fixtures were not changed.


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class EvidencePageTests(unittest.TestCase):
    """Test explicit refreshes, visible blockers and confirmed career/plan switching."""

    def test_refresh_and_confirm_plan_switch(self) -> None:
        """Cache reads are offline; changed rankings never silently replace the selected plan."""
        from streamlit.testing.v1 import AppTest
        client = GitHubTrends(opener=Mock(side_effect=AssertionError('Unexpected HTTP')),
                              now=lambda: datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
        evidence = {code: snapshot(code, 1000 if code == '15-2051.00' else 10, 100)
                    for code in ROLE_TOPICS}
        for code, record in evidence.items():
            client.snapshots[client._key(code)] = record
        with patch('src.github_trends.shared_client', return_value=client) as factory, \
             patch('urllib.request.urlopen', side_effect=AssertionError('Real HTTP forbidden')):
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
            page.button(key='pathway_sample').click().run()
            self.assertFalse(page.exception)
            factory.assert_called()
            page.selectbox(key='learning_role').set_value('15-1252.00').run()
            previous_plan = deepcopy(page.session_state['pathway_assessment']['plans']['15-1252.00'])
            for code in ROLE_TOPICS:
                page.selectbox(key='evidence_role').set_value(code).run()
                page.button(key='evidence_refresh').click().run()
                self.assertFalse(page.exception)
            self.assertEqual(page.selectbox(key='learning_role').value, '15-1252.00')
            self.assertEqual(page.session_state['pathway_assessment']['plans']['15-1252.00'], previous_plan)
            self.assertTrue(any('Official ranking blocked' in w.value for w in page.warning))
            page.button(key='evidence_confirm_switch').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(page.selectbox(key='learning_role').value, '15-2051.00')
            current = page.session_state['pathway_assessment']
            self.assertEqual(current['plans']['15-2051.00']['plan']['role_code'], '15-2051.00')
            self.assertNotEqual(current['plans']['15-2051.00']['plan'], previous_plan['plan'])
            client.opener.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class MainTrendPageTests(unittest.TestCase):
    """Controlled query responses drive the actual main page, not a second scoring path."""

    def page(self, client):
        from streamlit.testing.v1 import AppTest
        self.patch_client = patch('src.github_trends.shared_client', return_value=client)
        self.patch_client.start()
        self.addCleanup(self.patch_client.stop)
        self.patch_network = patch('urllib.request.urlopen', side_effect=AssertionError('Uncontrolled HTTP'))
        self.patch_network.start()
        self.addCleanup(self.patch_network.stop)
        page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
        page.button(key='pathway_sample').click().run()
        self.assertFalse(page.exception)
        self.assertEqual(page.radio(key='recommendation_source').value, 'GitHub snapshots')
        return page

    def test_main_scores_ranks_refresh_confirmation_and_fixed_plan(self):
        clock = [datetime(2026, 10, 22, 12, tzinfo=timezone.utc)]
        client = GitHubTrends(now=lambda: clock[0], opener=Mock())
        for code in ROLE_TOPICS:
            client.snapshots[client._key(code)] = snapshot(code, 10 if code == '15-2051.00' else 100, 100)
        page = self.page(client)
        client.opener.assert_not_called()
        current = page.session_state['pathway_assessment']
        profile = deepcopy(current['profile'])
        old = {r['code']: deepcopy(r) for r in current['recommendation_rows']}
        self.assertEqual(old['15-2051.00']['moderate_rank'], 3)
        page.selectbox(key='learning_role').set_value('15-1252.00').run()
        page.checkbox[0].check().run()
        plan = deepcopy(current['plans']['15-1252.00'])
        clock[0] += timedelta(minutes=16)
        client.opener.side_effect = [response(1000), response(10), response(1000), response(10)]
        page.selectbox(key='evidence_role').set_value('15-2051.00').run()
        page.button(key='evidence_refresh').click().run()
        self.assertFalse(page.exception)
        current = page.session_state['pathway_assessment']
        new = {r['code']: r for r in current['recommendation_rows']}
        self.assertEqual(current['profile'], profile)
        self.assertEqual(new['15-2051.00']['moderate_rank'], 1)
        self.assertEqual(new['15-2051.00']['fast_rank'], 1)
        self.assertAlmostEqual(new['15-2051.00']['moderate'].value - old['15-2051.00']['moderate'].value, 15)
        self.assertAlmostEqual(new['15-2051.00']['fast'].value - old['15-2051.00']['fast'].value, 35)
        for code in ROLE_TOPICS:
            self.assertEqual(old[code]['P'], new[code]['P'])
            self.assertEqual(old[code]['skills'], new[code]['skills'])
            self.assertEqual(old[code]['knowledge'], new[code]['knowledge'])
            if code != '15-2051.00':
                self.assertEqual(old[code]['moderate'], new[code]['moderate'])
        main_table = next(t.value for t in page.table if 'Matched to your profile' in t.value.columns)
        ds = main_table[main_table['Career'] == 'Data Scientists'].iloc[0]
        self.assertAlmostEqual(ds['Matched to your profile'], new['15-2051.00']['moderate'].value)
        self.assertFalse(any('Fast disruption' in item.label for item in page.selectbox))
        self.assertFalse(any(item.key == 'evidence_scenario' for item in page.selectbox))
        self.assertEqual(main_table[main_table['Career'] == 'Data Scientists'].iloc[0]['Rank'], 1)
        self.assertEqual(page.selectbox(key='learning_role').value, '15-1252.00')
        self.assertEqual(current['plans']['15-1252.00'], plan)
        self.assertTrue(any('Official ranking blocked' in w.value for w in page.warning))
        page.button(key='evidence_confirm_switch').click().run()
        self.assertFalse(page.exception)
        self.assertEqual(page.selectbox(key='learning_role').value, '15-2051.00')
        switched = deepcopy(current['plans']['15-2051.00']['plan'])
        self.assertNotEqual(switched['id'], plan['plan']['id'])
        page.button(key='evidence_refresh').click().run()
        self.assertEqual(client.opener.call_count, 4)  # Fresh cache, no extra HTTP.
        page.radio(key='recommendation_source').set_value('Synthetic demo').run()
        self.assertFalse(page.exception)
        self.assertEqual(page.selectbox(key='learning_role').value, '15-2051.00')
        self.assertEqual(current['plans']['15-2051.00']['plan'], switched)
        self.assertEqual(current['recommendation_rows'], current['rows'])

    def test_absent_failed_invalid_and_explicit_demo(self):
        client = GitHubTrends(opener=Mock(side_effect=URLError('controlled offline')))
        invalid = snapshot('15-2051.00')
        invalid['topics']['machine-learning']['recent'] = 999  # Query evidence no longer matches.
        client.snapshots[client._key('15-2051.00')] = invalid
        page = self.page(client)
        current = page.session_state['pathway_assessment']
        self.assertTrue(all(r['moderate'].value is None for r in current['recommendation_rows']))
        self.assertTrue(any('no valid GitHub snapshot' in w.value for w in page.warning))
        self.assertTrue(any('Only 0 of 3' in i.value for i in page.info))
        page.button(key='evidence_refresh').click().run()
        self.assertFalse(page.exception)
        self.assertTrue(all(r['trend']['score'].value is None for r in current['recommendation_rows']))
        self.assertEqual(page.radio(key='recommendation_source').value, 'GitHub snapshots')
        page.radio(key='recommendation_source').set_value('Synthetic demo').run()
        self.assertTrue(all(r['moderate'].value is not None for r in current['recommendation_rows']))
        self.assertTrue(any('invented trend counts' in w.value for w in page.warning))
        self.assertEqual(client.opener.call_count, 1)

    def test_expired_cache_failed_refresh_retains_source_dates_and_plan(self):
        client = GitHubTrends(now=lambda: datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
                              opener=Mock(side_effect=URLError('controlled offline')))
        for code in ROLE_TOPICS:
            client.snapshots[client._key(code)] = snapshot(code, 100, 100)
        page = self.page(client)
        current = page.session_state['pathway_assessment']
        old_rows = deepcopy(current['recommendation_rows'])
        old_snapshots = deepcopy(current['recommendation_snapshots'])
        self.assertTrue(any('expired snapshot' in w.value for w in page.warning))
        page.selectbox(key='learning_role').set_value('15-2051.00').run()
        old_plan = deepcopy(current['plans']['15-2051.00'])
        page.button(key='evidence_refresh').click().run()
        self.assertFalse(page.exception)
        self.assertEqual(current['recommendation_rows'], old_rows)
        self.assertEqual(current['recommendation_snapshots'], old_snapshots)
        self.assertEqual(current['plans']['15-2051.00'], old_plan)
        self.assertTrue(any('Retaining the last successful evidence' in w.value for w in page.warning))
        self.assertGreaterEqual(sum('Source query:' in m.value for m in page.markdown), 12)
        self.assertTrue(any('2026-10-22T12:00:00' in c.value for c in page.caption))
