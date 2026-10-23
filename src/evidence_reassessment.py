"""Shared GitHub evidence refresh and main-result ranking; synthetic requirements stay explicit."""
from src.i18n import localized_selectbox, career_name, tr, display_text, table_text, translated_options, translate_error
from copy import deepcopy
from typing import Any, Callable

from src.github_trends import ROLE_TOPICS, MAPPING_STATUS, evidence_score, snapshot_expired
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


def load_cached_evidence(state: dict, client: Any) -> None:
    """Load valid last-success evidence without HTTP; pin it until an explicit refresh."""
    snapshots = state.setdefault('snapshots', {})
    for code in ROLE_TOPICS:
        if evidence_score(snapshots.get(code), code).value is not None:
            continue
        snapshots.pop(code, None)
        outcome = client.cached(code)
        if evidence_score(outcome.get('snapshot'), code).value is not None:
            snapshots[code] = deepcopy(outcome['snapshot'])
        state.setdefault('outcomes', {})[code] = deepcopy(outcome)


def render_evidence_reassessment(st: Any, assessment: dict, official_loader: Callable,
                                 client_factory: Callable) -> list[dict]:
    """Choose the main ranking basis; cache reads are offline, refreshes explicit."""
    st.subheader(tr('Trend evidence for your recommendations'))
    st.warning(tr('Synthetic occupational requirements + GitHub technical activity. Repository creation is not hiring demand and does not predict job growth or decline.'))
    source = st.radio(tr('Recommendation trend source'), ('GitHub snapshots', 'Synthetic demo'),
                      key='recommendation_source', format_func=translated_options())
    state = st.session_state.setdefault('pathway_evidence', {})
    client = client_factory()
    load_cached_evidence(state, client)
    names = {role['code']: career_name(role['code'], role['title']) for role in assessment['roles']['roles']}
    st.caption(tr('Mapping: {v0}. Refresh ONE occupation at a time: two topics × two 90-day windows, four searches on a complete cache miss. Cache and shared limits still apply; no automatic refresh.', v0=display_text(MAPPING_STATUS)))
    with st.expander(tr('Technical details'), expanded=False):
        st.caption(tr('Anonymous requests: at most 10 per rolling minute, shared in this process. Each uncached successful Refresh sends 4 requests for ONE occupation (2 topics × 2 windows). Fresh cache reuse sends 0; a failure stops early. Successful snapshots are reused for 15 minutes. Server limits may be stricter. A failed refresh retains the last complete successful snapshot, including its original dates.'))
    code = localized_selectbox(st, tr('Occupation evidence to refresh'), tuple(ROLE_TOPICS),
                        format_func=translated_options(lambda value: names.get(value, value)), key='evidence_role')
    if st.button(tr('Refresh evidence and reassess'), key='evidence_refresh'):
        before = deepcopy(state.get('snapshots', {}))
        refresh_evidence(state, client, code)
        if before != state.get('snapshots'):
            st.info(tr('Evidence updated. Your profile and selected career are unchanged. Fixed-career skill gaps and plan tasks do not change with trends.'))
    snapshots = state.get('snapshots', {})
    for role_code in ROLE_TOPICS:
        snapshot = snapshots.get(role_code)
        outcome = state.get('outcomes', {}).get(role_code, {})
        if snapshot is None:
            st.warning(tr('{career}: no valid GitHub snapshot. Its real trend and combined scores are unavailable.', career=names[role_code]))
            if outcome.get('error'):
                with st.expander(names[role_code] + ' · ' + tr('Technical details')):
                    st.write(translate_error(outcome['error']))
            continue
        try:
            expired = snapshot_expired(snapshot, client.now())
        except (ValueError, KeyError, TypeError):
            expired = True
        st.caption(tr('{career} · GitHub snapshot fetched: {date}', career=names[role_code], date=snapshot['fetched_at']))
        if expired:
            st.warning(tr('{career}: using an expired snapshot from {date}. Refresh manually; old evidence is not a current observation.', career=names[role_code], date=snapshot['fetched_at']))
        if outcome.get('error'):
            st.warning(tr('Refresh failed. Retaining the last successful evidence; no failed counts were used.'))
        if outcome.get('message'):
            st.caption(translate_error(outcome['message']))
        with st.expander(names[role_code] + tr(' · Evidence changes')):
            st.table(table_text(snapshot_comparison(state.get('previous', {}).get(role_code), snapshot, role_code)))
            for topic, record in snapshot['topics'].items():
                for window in ('recent', 'previous'):
                    result = record['results'][window]
                    st.markdown(tr('[Source query: {topic} / {window}]({url})', topic=topic, window=window, url=result['source_url']))
            with st.expander(tr('Technical details')):
                if outcome.get('error'):
                    st.write(translate_error(outcome['error']))
                st.json(snapshot, expanded=False)
    if source == 'Synthetic demo':
        st.warning(tr('Synthetic demo selected: invented trend counts are used. These are not real GitHub observations.'))
        rows = assessment['rows']
    else:
        rows = evidence_ranking(assessment['profile'], assessment['roles']['roles'], snapshots)
        available = sum(row['moderate'].value is not None for row in rows)
        if available != len(ROLE_TOPICS):
            st.info(tr('Only {count} of 3 careers have complete scores. Rankings cover available careers only; missing evidence is never filled with synthetic counts. Select Synthetic demo explicitly to explore invented trends.', count=available))
    # Keep the fixed synthetic baseline for reproducible profile comparisons/plan transfer.
    # This is the exact projection used by the main ranking and learning-plan inputs.
    assessment['recommendation_rows'] = deepcopy(rows)
    assessment['recommendation_source'] = source
    assessment['recommendation_snapshots'] = deepcopy(snapshots) if source == 'GitHub snapshots' else {}
    if source == 'GitHub snapshots' and state.get('previous'):
        prior_snapshots = {key: state['previous'].get(key, value) for key, value in snapshots.items()}
        prior = {row['code']: row for row in evidence_ranking(
            assessment['profile'], assessment['roles']['roles'], prior_snapshots)}
        changes = []
        for row in rows:
            old = prior[row['code']]
            for scenario in ('moderate', 'fast'):
                for kind in ('score', 'rank'):
                    before = old[scenario].value if kind == 'score' else old[scenario + '_rank']
                    after = row[scenario].value if kind == 'score' else row[scenario + '_rank']
                    changes.append({'Career': career_name(row['code'], row['title']), 'Measure': scenario.title() + ' ' + kind,
                                    'Previous': before if before is not None else 'Unavailable',
                                    'Current': after if after is not None else 'Unavailable',
                                    'Change': after - before if before is not None and after is not None else 'Unavailable'})
        with st.expander(tr('Trend refresh · previous / current')):
            st.caption(tr('Same confirmed profile and synthetic requirements; only trend snapshots differ. Ranks cover available careers only.'))
            st.table(table_text(changes))
    with st.expander(tr('Official O*NET quality boundary')):
        for role in official_loader()['roles']:
            if role['code'] in ROLE_TOPICS:
                official_row = evidence_ranking(assessment['profile'], [role], snapshots)[0]
                reasons = tuple(dict.fromkeys((*role.get('data_issues', []), *official_row['moderate'].issues)))
                if reasons:
                    st.warning(translate_error(career_name(role['code'], role['title']) + tr(' · Official ranking blocked: ') + '; '.join(reasons)))
    scenario_label = localized_selectbox(st, tr('Scenario for career-switch suggestion'), ('Moderate', 'Fast disruption'),
                                  key='evidence_scenario', format_func=translated_options())
    scenario = 'moderate' if scenario_label == 'Moderate' else 'fast'
    ranked = [row for row in rows if row[scenario + '_rank'] is not None]
    selected = st.session_state.get('learning_role') or assessment.get('selected_role')
    if ranked and selected:
        top = min(ranked, key=lambda row: row[scenario + '_rank'])['code']
        if top != selected:
            st.info(tr('The current {scenario} ranking favours {career}. Your selected career and plan remain unchanged until you confirm a switch.', scenario=display_text(scenario_label), career=names[top]))
            if st.button(tr('Confirm switch to ') + names[top], key='evidence_confirm_switch'):
                confirm_career_switch(st.session_state, top)
    st.caption(tr('Evidence changes affect T and scenario scores, not skill gaps. Plans change only when you confirm a different career or edit your profile/time budget. Equal or clipped counts may leave ranks unchanged.'))
    return rows
