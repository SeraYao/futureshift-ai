"""Explicit GitHub evidence refresh, isolated from the synthetic simulation baseline."""
from copy import deepcopy
from typing import Any, Callable

from src.github_trends import ROLE_TOPICS, MAPPING_STATUS, evidence_score
from src.scoring import github_trend, rank_roles


def refresh_evidence(state: dict, client: Any, code: str) -> dict:
    """Retain old successful evidence; failures and cache hits never invent a new snapshot."""
    if code not in ROLE_TOPICS:
        raise ValueError('No approved mapping for this occupation')
    current = state.setdefault('snapshots', {})
    previous = state.setdefault('previous', {})
    cached = client.cached(code)
    if code not in current and evidence_score(cached.get('snapshot'), code).value is not None:
        current[code] = deepcopy(cached['snapshot'])
    outcome = client.refresh(code)
    snapshot = outcome.get('snapshot')
    if not outcome.get('error') and evidence_score(snapshot, code).value is not None:
        if current.get(code) != snapshot:
            if code in current:
                previous[code] = deepcopy(current[code])
            current[code] = deepcopy(snapshot)
    state.setdefault('outcomes', {})[code] = deepcopy(outcome)
    return outcome


def snapshot_comparison(old: dict | None, new: dict, code: str) -> list[dict]:
    """Expose exact per-topic counts, windows, timestamps and unchanged-formula scores."""
    rows = []
    for topic, weight in ROLE_TOPICS[code].items():
        for label, snapshot in (('Previous success', old), ('Current success', new)):
            if snapshot is None:
                continue
            record = snapshot['topics'][topic]
            rows.append({'Snapshot': label, 'Topic': topic, 'Weight': weight,
                         'Recent count': record['recent'], 'Previous count': record['previous'],
                         'Recent window (UTC, end exclusive)': record['recent_window']['start'] + ' → ' + record['recent_window']['end_exclusive'],
                         'Previous window (UTC, end exclusive)': record['previous_window']['start'] + ' → ' + record['previous_window']['end_exclusive'],
                         'Topic score': github_trend(record['recent'], record['previous']).value,
                         'Fetched (UTC)': snapshot['fetched_at']})
    return rows


def evidence_ranking(profile: dict, roles: list[dict], snapshots: dict) -> list[dict]:
    """Use real evidence only for approved roles; absent evidence remains unscorable.

    Synthetic requirements remain explicitly synthetic. Official quality-gated
    nulls and issues block the corresponding components, with no filled values.
    """
    selected, topics = [], {}
    for original in roles:
        code = original['code']
        if code not in ROLE_TOPICS:
            continue
        role = deepcopy(original)
        role['topics'] = {code + ':' + topic: weight for topic, weight in ROLE_TOPICS[code].items()}
        snapshot = snapshots.get(code)
        if evidence_score(snapshot, code).value is not None:
            for topic, record in snapshot['topics'].items():
                topics[code + ':' + topic] = deepcopy(record)
        for group in ('skills', 'knowledge'):
            for item in role[group].values():
                if item.get('issues') or any(rating.get('issues') for rating in item.get('sources', {}).values()):
                    item['required'] = None
        if role.get('data_issues'):
            # Conservative official quality gate: unresolved role issues block completeness.
            role['riasec'] = [None] * 6
        selected.append(role)
    return rank_roles(profile, selected, topics)


def confirm_career_switch(state: Any, code: str) -> None:
    """Change the selected learning career only following an explicit confirmation click."""
    if code not in ROLE_TOPICS:
        raise ValueError('Occupation is outside approved scope')
    state['learning_role'] = code
    if state.get('pathway_assessment') is not None:
        state['pathway_assessment']['selected_role'] = code


def render_evidence_reassessment(st: Any, assessment: dict, official_loader: Callable,
                                 client_factory: Callable) -> None:
    """Render an opt-in evidence experiment, never automatically querying GitHub."""
    st.subheader('Refresh evidence and reassess')
    st.warning('Prototype experiment: synthetic occupational requirements + real GitHub topic activity. '
               'Not a recruitment-demand or employment-growth forecast. Original synthetic matches remain separate.')
    st.caption(f'Mapping: {MAPPING_STATUS}. Refresh ONE occupation at a time: two topics × two 90-day windows, '
               'four searches on a complete cache miss. Cache and shared limits still apply; no automatic refresh.')
    state = st.session_state.setdefault('pathway_evidence', {})
    names = {role['code']: role['title'] for role in assessment['roles']['roles']}
    code = st.selectbox('Occupation evidence to refresh', tuple(ROLE_TOPICS),
                        format_func=lambda value: names.get(value, value), key='evidence_role')
    if st.button('Refresh evidence and reassess', key='evidence_refresh'):
        refresh_evidence(state, client_factory(), code)
    snapshots = state.get('snapshots', {})
    last_outcome = state.get('outcomes', {}).get(code, {})
    if last_outcome.get('error') and code not in snapshots:
        st.warning('Refresh failed and no successful evidence is available for this occupation. '
                   'No zero counts or scenario scores have been substituted.')
        with st.expander('Technical details', expanded=False):
            st.write(last_outcome['error'])
    if not snapshots:
        st.info('No successful evidence loaded in this experiment. Click Refresh to fetch or reuse a valid cache.')
        return
    for role_code, snapshot in snapshots.items():
        with st.expander(names.get(role_code, role_code) + ' · Evidence changes'):
            outcome = state.get('outcomes', {}).get(role_code, {})
            if outcome.get('error'):
                st.warning('Refresh failed. Retaining the last successful evidence; no failed counts were used.')
            st.caption(f"cached: {outcome.get('cached')} · expired: {outcome.get('expired')} · "
                       f"Original fetched time: {snapshot['fetched_at']}")
            old = state.get('previous', {}).get(role_code)
            st.table(snapshot_comparison(old, snapshot, role_code))
            current_score = evidence_score(snapshot, role_code).value
            if old is None:
                st.write(f'Trend score T: {current_score:.2f}. No earlier successful snapshot for comparison.')
            else:
                old_score = evidence_score(old, role_code).value
                st.write(f'Trend score T: {old_score:.2f} → {current_score:.2f}; '
                         f'change {current_score-old_score:+.2f}. '
                         + ('Unchanged.' if old_score == current_score else 'Changed.'))
            with st.expander('Technical details', expanded=False):
                if outcome.get('error'):
                    st.write(outcome['error'])
                st.json({'previous': old, 'current': snapshot}, expanded=False)
    rows = evidence_ranking(assessment['profile'], assessment['roles']['roles'], snapshots)
    st.markdown('#### Evidence-adjusted prototype scenarios')
    complete = len(rows) == 3 and all(row['moderate'].value is not None for row in rows)
    if not complete:
        st.info('Full three-career ranking is unavailable until all three have usable evidence and personal components. '
                'Missing evidence is not replaced by synthetic counts. Original synthetic rankings above are unchanged.')
    baseline = {row['code']: row for row in assessment['rows']}
    prior_snapshots = {key: state.get('previous', {}).get(key, value) for key, value in snapshots.items()}
    prior_rows = {row['code']: row for row in evidence_ranking(
        assessment['profile'], assessment['roles']['roles'], prior_snapshots)}
    prior_complete = len(prior_rows) == 3 and all(row['moderate'].value is not None for row in prior_rows.values())
    for row in rows:
        with st.expander(row['title'] + ' · Scenario evidence impact'):
            for scenario in ('moderate', 'fast'):
                value = row[scenario].value
                if value is None:
                    st.warning(scenario.title() + ': unavailable. ' + '; '.join(row[scenario].issues))
                    continue
                base = baseline[row['code']]
                st.write(f"{scenario.title()} score: {value:.2f} · Original all-synthetic score: "
                         f"{base[scenario].value:.2f}" if base[scenario].value is not None else
                         f'{scenario.title()} score: {value:.2f} · Original score unavailable')
                if complete:
                    old_rank = base[scenario + '_rank']
                    rank = row[scenario + '_rank']
                    st.write(f'Original synthetic rank: {old_rank} → evidence-adjusted rank: {rank}. '
                             + ('Unchanged.' if old_rank == rank else 'Changed.'))
                    if prior_complete:
                        prior = prior_rows[row['code']]
                        st.caption(f"Previous-success comparison: score {prior[scenario].value:.2f} → {value:.2f}; "
                                   f"rank {prior[scenario+'_rank']} → {rank}.")
    official = official_loader()
    st.markdown('#### Official O*NET quality boundary')
    for role in official['roles']:
        if role['code'] in ROLE_TOPICS:
            official_row = evidence_ranking(assessment['profile'], [role], snapshots)[0]
            reasons = tuple(dict.fromkeys((*role.get('data_issues', []), *official_row['moderate'].issues)))
            if reasons:
                st.warning(role['title'] + ' · Official ranking blocked: ' + '; '.join(reasons))
            else:
                st.caption(role['title'] + ': components available; official ranking is not combined with this synthetic experiment.')
    if complete:
        scenario_label = st.selectbox('Scenario for career-switch suggestion', ('Moderate', 'Fast disruption'),
                                      key='evidence_scenario')
        scenario = 'moderate' if scenario_label == 'Moderate' else 'fast'
        top = min(rows, key=lambda row: row[scenario + '_rank'])['code']
        selected = st.session_state.get('learning_role') or assessment.get('selected_role')
        if selected and top != selected:
            st.info(f"The evidence-adjusted {scenario_label} scenario favours {names[top]}. "
                    'Your selected career and plan have not been changed. Switching uses that career’s synthetic gaps.')
            if st.button('Confirm switch to ' + names[top], key='evidence_confirm_switch'):
                confirm_career_switch(st.session_state, top)
    st.caption('Evidence changes affect T and scenario scores, not skill gaps. Plans change only when you confirm '
               'a different career or edit your profile/time budget. Equal or clipped counts may leave ranks unchanged.')
