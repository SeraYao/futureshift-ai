"""Opt-in real GitHub check of main rankings and plans, using a synthetic profile.

Runs the main page with AppTest and the actual GitHub client. Only the client
factory is bridged so its requests/cache can be observed; HTTP is not mocked.
Refreshes one career and persists successful public snapshots to the normal cache.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import monotonic
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest
import app
from src.evidence_reassessment import evidence_ranking
from src.github_trends import GitHubTrends, ROLE_TOPICS, snapshot_expired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', choices=tuple(ROLE_TOPICS), default='15-2051.00')
    parser.add_argument('--cache-only', action='store_true', help='Verify saved real evidence without HTTP.')
    args = parser.parse_args()
    path = app.ROOT / 'data/cache/github_trends.json'
    client = GitHubTrends(path)
    started = monotonic()
    with patch('src.github_trends.shared_client', return_value=client), \
         patch.object(client, '_search', wraps=client._search) as searches:
        page = AppTest.from_file(str(app.ROOT / 'app.py')).run()
        page.button(key='scenario_explore').click().run()
        page.button(key='pathway_sample').click().run()
        assert not page.exception
        assert searches.call_count == 0
        assert page.radio(key='recommendation_source').value == 'GitHub snapshots'
        current = page.session_state['pathway_assessment']
        profile = deepcopy(current['profile'])
        page.selectbox(key='learning_role').set_value('15-1252.00').run()
        page.checkbox[0].check().run()
        plan = deepcopy(current['plans']['15-1252.00'])
        page.selectbox(key='evidence_role').set_value(args.refresh).run()
        if not args.cache_only:
            page.button(key='evidence_refresh').click().run(timeout=70)
        assert not page.exception
        assert current['profile'] == profile
        assert current['plans']['15-1252.00'] == plan
        assert page.selectbox(key='learning_role').value == '15-1252.00'
        outcome = page.session_state['pathway_evidence']['outcomes'][args.refresh]
        if outcome.get('error'):
            print(json.dumps({'real_query_success': False, 'error': outcome['error'],
                              'query_attempts': searches.call_count, 'http_attempts': len(client.attempts), 'old_snapshot_retained': bool(outcome.get('snapshot'))}))
            return 1
        snapshots = current['recommendation_snapshots']
        expected = evidence_ranking(profile, current['roles']['roles'], snapshots)
        assert current['recommendation_rows'] == expected
        table = next(t.value for t in page.table if 'Moderate score' in t.value.columns)
        for row in expected:
            if row['moderate'].value is not None:
                cell = table[table['Career'] == row['title']].iloc[0]
                assert cell['Moderate score'] == row['moderate'].value
        query_attempts = searches.call_count
        if not args.cache_only:
            page.button(key='evidence_refresh').click().run()
        assert searches.call_count == query_attempts
        assert current['recommendation_snapshots'] == snapshots
        assert GitHubTrends(path).cached(args.refresh)['snapshot'] == snapshots[args.refresh]
        ranked = [r for r in expected if r['moderate_rank'] is not None]
        top = min(ranked, key=lambda r: r['moderate_rank'])['code']
        if page.selectbox(key='learning_role').value == top:
            other = next(r['code'] for r in ranked if r['code'] != top)
            page.selectbox(key='learning_role').set_value(other).run()
        previous_role = page.selectbox(key='learning_role').value
        page.button(key='evidence_confirm_switch').click().run()
        assert not page.exception
        assert page.selectbox(key='learning_role').value == top
        assert current['plans'][top]['plan']['tasks']
        print(json.dumps({
            'real_query_success': query_attempts > 0,
            'cache_only': args.cache_only,
            'fresh_cache_used_without_query': query_attempts == 0 and not snapshot_expired(snapshots[args.refresh], client.now()),
            'query_attempts': query_attempts, 'http_attempts': len(client.attempts), 'refreshed_role': args.refresh,
            'fetched_at': snapshots[args.refresh]['fetched_at'],
            'elapsed_seconds': round(monotonic() - started, 3),
            'profile_preserved': True, 'fixed_career_plan_preserved': True,
            'repeat_refresh_no_http': True if not args.cache_only else None, 'disk_cache_verified': True,
            'confirmed_switch': [previous_role, top],
            'main_scores': [{'code': r['code'], 'P': r['P'].value, 'T': r['trend']['score'].value,
                             'moderate': r['moderate'].value, 'moderate_rank': r['moderate_rank'],
                             'fast': r['fast'].value, 'fast_rank': r['fast_rank']} for r in expected],
            'snapshot_dates': {code: snapshot['fetched_at'] for code, snapshot in snapshots.items()},
            'expired_snapshots': {code: snapshot_expired(snapshot, client.now()) for code, snapshot in snapshots.items()},
        }))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
