"""Mock-only tests: never call the real GitHub API."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from src import github_trends as gh
from src.scoring import github_trend

CODE = '15-2051.00'
# Test-only configuration, not an approved real query mapping.
TEST_MAPPING = {CODE: {'test-topic': 1.0}}


def response(count: int = 20, incomplete: bool = False, headers: dict | None = None) -> Mock:
    """Build a mock urllib context-managed JSON response."""
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.status = 200
    result.headers = headers or {}
    result.read.return_value = json.dumps({'total_count': count, 'incomplete_results': incomplete}).encode()
    return result


class GitHubTrendsTests(unittest.TestCase):
    """Check provenance, atomic caches, errors and request limits without HTTP traffic."""

    def setUp(self) -> None:
        """Inject a fixed UTC clock and a clearly test-only approved mapping."""
        self.time = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        self.mapping = patch.dict(gh.ROLE_TOPICS, TEST_MAPPING, clear=True)
        self.mapping.start()
        self.addCleanup(self.mapping.stop)
        self.no_network = patch('urllib.request.urlopen', side_effect=AssertionError('Real HTTP forbidden in tests'))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    def client(self, opener: Mock, path: Path | None = None) -> gh.GitHubTrends:
        """Construct a test client with all side effects explicitly injected."""
        return gh.GitHubTrends(path, opener=opener, now=lambda: self.time)

    def test_windows_complete_adjacent_including_leap_year(self) -> None:
        """Each window has exactly 90 days, without overlaps or today's partial day."""
        for day in (date(2026,10,21), date(2024,3,1), date(2026,1,1)):
            ranges = gh.windows(day)
            for window in ranges.values():
                self.assertEqual((date.fromisoformat(window['end_exclusive'])-
                                  date.fromisoformat(window['start'])).days,90)
            self.assertEqual(ranges['previous']['end_exclusive'],ranges['recent']['start'])
            self.assertEqual(ranges['recent']['end_exclusive'],day.isoformat())
        self.assertEqual(gh.windows(date(2026,10,21))['recent']['start'],'2026-07-23')

    def test_explicit_refresh_only_and_full_provenance(self) -> None:
        """Construction/cache reads stay offline; explicit refresh performs two count queries."""
        opener = Mock(side_effect=[response(100), response(80)])
        client = self.client(opener)
        self.assertIsNone(client.cached(CODE)['snapshot'])
        opener.assert_not_called()
        result = client.refresh(CODE)
        self.assertEqual(opener.call_count,2)
        self.assertFalse(result['cached'])
        snapshot = result['snapshot']
        self.assertEqual(snapshot['role_code'],CODE)
        self.assertEqual(snapshot['fetched_at'],self.time.isoformat())
        topic = snapshot['topics']['test-topic']
        self.assertEqual((topic['recent'],topic['previous']),(100,80))
        recent = topic['results']['recent']
        self.assertEqual(recent['query'],'topic:test-topic visibility:public fork:false created:2026-07-23..2026-10-20')
        params = parse_qs(urlparse(recent['source_url']).query)
        self.assertEqual(params['q'],[recent['query']])
        self.assertEqual(params['per_page'],['1'])
        self.assertEqual(gh.evidence_score(snapshot,CODE),github_trend(100,80))
        self.assertIsNone(gh.evidence_score(snapshot,'15-2031.00').value)

    def test_fresh_cache_reused_and_disk_reload_is_offline(self) -> None:
        """A repeated Refresh within TTL uses cache; disk snapshots survive client restart."""
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache.json'
            opener=Mock(side_effect=[response(20),response(20)])
            client=self.client(opener,path)
            first=client.refresh(CODE)
            second=client.refresh(CODE)
            self.assertTrue(second['cached'])
            self.assertFalse(second['expired'])
            self.assertEqual(first['snapshot'],second['snapshot'])
            self.assertEqual(opener.call_count,2)
            offline=Mock(side_effect=AssertionError('No refresh requested'))
            restored=self.client(offline,path)
            self.assertEqual(restored.cached(CODE)['snapshot'],first['snapshot'])
            offline.assert_not_called()

    def test_failure_preserves_last_good_snapshot_and_timestamp(self) -> None:
        """An error after expiry returns explicitly cached old evidence, not zero or fake time."""
        opener=Mock(side_effect=[response(20),response(10),TimeoutError('timeout')])
        client=self.client(opener)
        first=client.refresh(CODE)['snapshot']
        self.time += timedelta(minutes=16)
        failed=client.refresh(CODE)
        self.assertEqual(failed['snapshot'],first)
        self.assertTrue(failed['cached'])
        self.assertTrue(failed['expired'])
        self.assertIn('timeout',failed['error'])
        self.assertIn('timeout',client.cached(CODE)['error'])

    def test_partial_role_refresh_never_commits_mixed_counts(self) -> None:
        """A second-window failure cannot combine a new recent count with an old previous count."""
        opener=Mock(side_effect=[response(10),response(5),response(100),URLError('offline')])
        client=self.client(opener)
        first=client.refresh(CODE)['snapshot']
        self.time+=timedelta(minutes=16)
        result=client.refresh(CODE)
        self.assertEqual(result['snapshot'],first)
        self.assertEqual(result['snapshot']['topics']['test-topic']['recent'],10)

    def test_rate_limit_headers_stop_further_requests(self) -> None:
        """403/429 honor cooldown; repeated clicks do not hammer GitHub."""
        for status in (403,429):
            with self.subTest(status=status):
                headers=Message();headers['Retry-After']='120'
                failure=HTTPError(gh.API_URL,status,'rate limited',headers,BytesIO(b'{}'))
                opener=Mock(side_effect=failure)
                client=self.client(opener)
                first=client.refresh(CODE)
                self.assertIsNone(first['snapshot'])
                self.assertIn(str(status),first['error'])
                client.refresh(CODE)
                self.assertEqual(opener.call_count,1)
                self.assertEqual(client.blocked_until,self.time+timedelta(seconds=120))

    def test_success_exhausting_server_budget_blocks_next_window(self) -> None:
        """A success header showing zero remaining requests prevents subsequent calls."""
        opener=Mock(return_value=response(10,headers={'X-RateLimit-Remaining':'0',
                    'X-RateLimit-Reset':str(int((self.time+timedelta(minutes=5)).timestamp()))}))
        result=self.client(opener).refresh(CODE)
        self.assertEqual(opener.call_count,1)
        self.assertIsNone(result['snapshot'])
        self.assertIn('Rate limited',result['error'])

    def test_local_rolling_limit_is_ten_attempts(self) -> None:
        """Invalid HTTP attempts count against the same rolling-minute budget."""
        opener=Mock(side_effect=URLError('offline'))
        client=self.client(opener)
        for _ in range(12):
            result=client.refresh(CODE)
        self.assertEqual(opener.call_count,10)
        self.assertIn('10 anonymous',result['error'])
        self.time+=timedelta(seconds=61)
        client.refresh(CODE)
        self.assertEqual(opener.call_count,11)

    def test_incomplete_bad_json_and_api_errors_never_become_zero(self) -> None:
        """Timeout, malformed payloads, API failures and incomplete results remain unavailable."""
        bad=response();bad.read.return_value=b'not JSON'
        missing=response();missing.read.return_value=b'{}'
        values=[response(0,True),bad,missing,TimeoutError('slow'),URLError('DNS'),
                HTTPError(gh.API_URL,500,'server error',{},BytesIO(b''))]
        for value in values:
            with self.subTest(value=value):
                opener=Mock(side_effect=[value])
                result=self.client(opener).refresh(CODE)
                self.assertIsNone(result['snapshot'])
                self.assertTrue(result['error'])
        # A real successful count of zero remains a count, unlike a failed request.
        result=self.client(Mock(side_effect=[response(0),response(0)])).refresh(CODE)
        self.assertEqual(gh.evidence_score(result['snapshot'],CODE).value,50)

    def test_unmapped_occupation_never_queries_or_reuses_another_cache(self) -> None:
        """Only explicitly mapped occupations can fetch their own evidence."""
        opener=Mock(side_effect=[response(),response()])
        client=self.client(opener)
        client.refresh(CODE)
        result=client.refresh('17-2199.08')
        self.assertIsNone(result['snapshot'])
        self.assertEqual(opener.call_count,2)

    def test_next_utc_day_expires_previous_windows_even_within_ttl(self) -> None:
        """The cache is not labeled current when its date windows have rolled over."""
        self.time=datetime(2026,10,21,23,59,tzinfo=timezone.utc)
        client=self.client(Mock(side_effect=[response(),response()]))
        client.refresh(CODE)
        self.time+=timedelta(minutes=2)
        self.assertTrue(client.cached(CODE)['expired'])

    def test_corrupt_cache_is_reported_without_network(self) -> None:
        """Disk parsing failures are visible, and do not trigger automatic HTTP recovery."""
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache.json';path.write_text('invalid')
            opener=Mock()
            result=self.client(opener,path).cached(CODE)
            self.assertIn('Cache unavailable',result['error'])
            self.assertIsNone(result['snapshot'])
            opener.assert_not_called()


class GitHubAuditIntegrationTests(unittest.TestCase):
    """Audit-only real-evidence rendering, with HTTP strictly mocked."""

    def setUp(self) -> None:
        """Use test-only mappings and forbid default urllib network traffic."""
        self.mapping = patch.dict(gh.ROLE_TOPICS, TEST_MAPPING, clear=True)
        self.mapping.start(); self.addCleanup(self.mapping.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('Real HTTP forbidden'))
        network.start(); self.addCleanup(network.stop)

    def test_audit_does_not_fetch_until_refresh_and_keeps_quality_blockers(self) -> None:
        """Refresh fetches the selected role; rerender uses cache, with no match total."""
        import app
        from test_modes import RecordingUI

        class RefreshUI(RecordingUI):
            """Click exactly one explicit Refresh control in the recording renderer."""

            def button(self, label: str, **kwargs) -> bool:
                """Report an explicit test click for the mapped occupation only."""
                return kwargs['key'] == 'github_refresh_' + CODE

        opener = Mock(side_effect=[response(100), response(80)])
        client = gh.GitHubTrends(opener=opener,
                                 now=lambda: datetime(2026,10,21,12,tzinfo=timezone.utc))
        official = app.load_onet()
        with patch('app.load_demo', side_effect=AssertionError('No demo data in audit')), \
             patch('app.rank_roles', side_effect=AssertionError('No totals/rankings in audit')):
            app.render_live_trends(RecordingUI(), official, client)
            opener.assert_not_called()
            ui = RefreshUI()
            app.render_live_trends(ui, official, client)
            self.assertEqual(opener.call_count,2)
            warnings = [args[0] for method,args,_ in ui.calls if method=='warning']
            self.assertTrue(any('Recommend Suppress=Y' in warning for warning in warnings))
            writes = str([args for method,args,_ in ui.calls if method=='write'])
            self.assertIn('trend score T', writes)
            self.assertNotIn('Match(', writes)
            app.render_live_trends(RecordingUI(), official, client)
            self.assertEqual(opener.call_count,2)

    def test_synthetic_renderer_never_reads_client_or_cache(self) -> None:
        """The simulation branch never consults GitHub even when a live cache exists."""
        # Data-only simulation operations stay valid when the live client is unusable.
        import app
        with patch('app.get_trend_client', side_effect=AssertionError('Live data forbidden')):
            profile,roles,trends = app.load_demo()
            from src.scoring import rank_roles
            rows = rank_roles(profile,roles['roles'],trends['topics'])
        self.assertTrue(all(row['moderate_rank'] is not None for row in rows))
        self.assertTrue(all(row['data_status']=='synthetic' for row in rows))

    def test_role_mapping_cache_signature_prevents_cross_mapping_reuse(self) -> None:
        """Changing an approved query mapping invalidates older evidence instead of relabeling it."""
        client = gh.GitHubTrends(opener=Mock(side_effect=[response(),response()]),
                                 now=lambda: datetime(2026,10,21,12,tzinfo=timezone.utc))
        snapshot = client.refresh(CODE)['snapshot']
        with patch.dict(gh.ROLE_TOPICS,{CODE:{'different-test-topic':1.0}},clear=True):
            self.assertIsNone(client.cached(CODE)['snapshot'])
            self.assertIsNone(gh.evidence_score(snapshot,CODE).value)

    def test_clients_share_budget_across_streamlit_reruns(self) -> None:
        """Repeated application wrappers return the module-level client instead of resetting quotas."""
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'no-cache.json'
            gh.shared_client.cache_clear()
            self.addCleanup(gh.shared_client.cache_clear)
            first=gh.shared_client(path)
            first.attempts.append(datetime(2026,10,21,tzinfo=timezone.utc))
            second=gh.shared_client(path)
            self.assertIs(first,second)
            self.assertEqual(len(second.attempts),1)


class ConfirmedMappingTests(unittest.TestCase):
    """Exercise the production three-role scope with only mocked HTTP responses."""

    def test_confirmed_mapping_exactly_matches_three_occupations(self) -> None:
        """No additional occupation or guessed topic can enter the production mapping."""
        self.assertEqual(gh.ROLE_TOPICS, {
            '15-2051.00': {'machine-learning':.5, 'data-science':.5},
            '15-2031.00': {'operations-research':.5, 'optimization':.5},
            '15-1252.00': {'code-generation':.5, 'software-testing':.5},
        })
        self.assertEqual(gh.MAPPING_STATUS, '原型假设，尚待验证')

    def test_each_occupation_refresh_sends_only_its_four_queries(self) -> None:
        """Each uncached success requests only two approved topics and their two windows."""
        for code, weights in gh.ROLE_TOPICS.items():
            with self.subTest(code=code):
                opener=Mock(side_effect=[response(100),response(80),response(40),response(60)])
                client=gh.GitHubTrends(opener=opener,
                    now=lambda:datetime(2026,10,21,12,tzinfo=timezone.utc))
                with patch('urllib.request.urlopen',side_effect=AssertionError('Real HTTP forbidden')):
                    outcome=client.refresh(code)
                    self.assertEqual(opener.call_count,4)
                    result=outcome['snapshot']
                    self.assertEqual(result['role_code'],code)
                    self.assertEqual(result['topic_weights'],weights)
                    self.assertEqual(result['mapping_status'],gh.MAPPING_STATUS)
                    self.assertEqual(set(result['topics']),set(weights))
                    expected=(github_trend(100,80).value+github_trend(40,60).value)/2
                    self.assertAlmostEqual(gh.evidence_score(result,code).value,expected)
                    queries=[parse_qs(urlparse(call.args[0].full_url).query)['q'][0]
                             for call in opener.call_args_list]
                    self.assertEqual(len(queries),4)
                    for topic in weights:
                        self.assertEqual(sum(query.startswith('topic:'+topic+' ') for query in queries),2)
                        self.assertEqual(set(result['topics'][topic]['results']),{'recent','previous'})
                        self.assertTrue(all(record['http_status']==200
                                            for record in result['topics'][topic]['results'].values()))
                    self.assertTrue(client.refresh(code)['cached'])
                    self.assertEqual(opener.call_count,4)  # repeated click sends no HTTP
                    for other in gh.ROLE_TOPICS:
                        if other!=code:
                            self.assertIsNone(client.cached(other)['snapshot'])

    def test_production_scope_excludes_all_other_seven(self) -> None:
        """Audited occupations outside the exact three-role list never request evidence."""
        import app
        opener=Mock(side_effect=AssertionError('Unmapped roles must not request'))
        client=gh.GitHubTrends(opener=opener)
        others=[role for role in app.load_onet()['roles'] if role['code'] not in gh.ROLE_TOPICS]
        self.assertEqual(len(others),7)
        for role in others:
            self.assertIsNone(client.refresh(role['code'])['snapshot'])
        opener.assert_not_called()

    def test_page_refresh_only_queries_clicked_role_and_displays_hypothesis(self) -> None:
        """UI triggers four requests for a single clicked card, retaining explicit status text."""
        import app
        from test_modes import RecordingUI

        class ClickOneUI(RecordingUI):
            """Click only Operations Research Analysts in the three-card evidence section."""

            def button(self,label: str, **kwargs) -> bool:
                """Simulate exactly one explicit Refresh click."""
                return kwargs['key']=='github_refresh_15-2031.00'

        opener=Mock(side_effect=[response(10),response(5),response(8),response(4)])
        client=gh.GitHubTrends(opener=opener,
                             now=lambda:datetime(2026,10,21,12,tzinfo=timezone.utc))
        ui=ClickOneUI()
        with patch('app.load_demo',side_effect=AssertionError('No synthetic inputs in audit')):
            app.render_live_trends(ui,app.load_onet(),client)
        self.assertEqual(opener.call_count,4)
        snapshots=[args[0] for method,args,_ in ui.calls if method=='json']
        self.assertEqual(len(snapshots),1)
        self.assertEqual(snapshots[0]['role_code'],'15-2031.00')
        self.assertTrue(any('Prototype hypothesis, not yet validated' in str(args) for _,args,_ in ui.calls))
        self.assertTrue(any('not hiring counts' in str(args) for _,args,_ in ui.calls))


class TrendCountDisplayTests(unittest.TestCase):
    """Rendering must use precisely the counts and windows in the displayed snapshot."""

    def test_disk_cached_and_fresh_count_displays_are_identical(self) -> None:
        """Cache reload changes the cache label, never the raw table evidence or score."""
        import app
        from test_modes import RecordingUI
        time=datetime(2026,10,21,12,tzinfo=timezone.utc)
        opener=Mock(side_effect=[response(101),response(83),response(42),response(61)])
        with tempfile.TemporaryDirectory() as tmp, \
             patch('urllib.request.urlopen',side_effect=AssertionError('Real API forbidden')):
            path=Path(tmp)/'cache.json'
            client=gh.GitHubTrends(path,opener=opener,now=lambda:time)
            fresh=client.refresh(CODE)['snapshot']
            cache_bytes=path.read_bytes()
            fresh_ui=RecordingUI()
            app.render_trend_breakdown(fresh_ui,fresh,gh.evidence_score(fresh,CODE))
            no_fetch=Mock(side_effect=AssertionError('Cached display cannot refresh'))
            restored=gh.GitHubTrends(path,opener=no_fetch,now=lambda:time)
            cached=restored.cached(CODE)
            self.assertTrue(cached['cached'])
            cached_ui=RecordingUI()
            app.render_live_trends(cached_ui,app.load_onet(),restored)
            no_fetch.assert_not_called()
            self.assertEqual(opener.call_count,4)
            fresh_tables=[args[0] for method,args,_ in fresh_ui.calls if method=='table']
            cached_tables=[args[0] for method,args,_ in cached_ui.calls if method=='table']
            self.assertEqual(fresh_tables,cached_tables)
            self.assertEqual(len(cached_tables),2)
            for topic,table in zip(cached['snapshot']['topic_weights'],cached_tables):
                record=cached['snapshot']['topics'][topic]
                for name,row in zip(('previous','recent'),table):
                    self.assertEqual(row['Repository count'],record[name])
                    self.assertEqual(row['Repository count'],record['results'][name]['count'])
                    self.assertEqual(row['Start date (UTC, inclusive)'],record[name+'_window']['start'])
                    self.assertEqual(row['End date (UTC, exclusive)'],record[name+'_window']['end_exclusive'])
            text=str([args for _,args,_ in cached_ui.calls])
            self.assertIn('Normalized share: **50%**',text)
            self.assertIn('Topic score T_k',text)
            self.assertIn('T = sum(weight_k',text)
            self.assertIn('20',text)
            self.assertEqual(path.read_bytes(),cache_bytes)

    def test_failed_refresh_displays_old_counts_and_original_windows(self) -> None:
        """Expired fallback evidence must not show failed/new-window counts as current data."""
        import app
        from test_modes import RecordingUI
        current=[datetime(2026,10,21,12,tzinfo=timezone.utc)]
        opener=Mock(side_effect=[response(0),response(7),response(9),response(0),TimeoutError('test timeout')])
        client=gh.GitHubTrends(opener=opener,now=lambda:current[0])
        first=client.refresh(CODE)['snapshot']
        current[0]+=timedelta(days=1)
        failed=client.refresh(CODE)
        self.assertTrue(failed['cached'])
        self.assertTrue(failed['expired'])
        self.assertEqual(failed['snapshot'],first)
        ui=RecordingUI()
        with patch('urllib.request.urlopen',side_effect=AssertionError('No real HTTP')):
            app.render_live_trends(ui,app.load_onet(),client)
        tables=[args[0] for method,args,_ in ui.calls if method=='table']
        self.assertEqual([row['Repository count'] for table in tables for row in table],[7,0,0,9])
        self.assertEqual(tables[0][1]['End date (UTC, exclusive)'],'2026-10-21')
        self.assertTrue(any('test timeout' in str(args) for method,args,_ in ui.calls if method=='error'))
        self.assertEqual(opener.call_count,5)
