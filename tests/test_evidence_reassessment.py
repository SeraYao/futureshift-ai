"""Evidence reassessment with mock HTTP only and real Streamlit interactions."""
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
        """Only clicks read real caches; changed rankings never silently replace the selected plan."""
        from streamlit.testing.v1 import AppTest
        client = GitHubTrends(opener=Mock(side_effect=AssertionError('Unexpected HTTP')),
                              now=lambda: datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
        evidence = {code: snapshot(code, 1000 if code == '15-2051.00' else 10, 100)
                    for code in ROLE_TOPICS}
        for code, record in evidence.items():
            client.snapshots[client._key(code)] = record
        with patch('src.github_trends.shared_client', return_value=client) as factory, \
             patch('urllib.request.urlopen', side_effect=AssertionError('Real HTTP forbidden')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            page.button(key='pathway_sample').click().run()
            self.assertFalse(page.exception)
            factory.assert_not_called()
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
