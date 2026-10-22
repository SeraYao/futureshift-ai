"""Strictly separated synthetic simulation and official O*NET audit. Run: python3 -m streamlit run app.py."""
from src.i18n import tr, display_text, display_value, table_text, translated_options, translate_error
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from src.scoring import (
    FAST_LAMBDA, MODERATE_LAMBDA, SCORING_VERSION, Score, github_trend, rank_roles,
)

from src.pathway import render_pathway

from src.github_trends import (
    GitHubTrends, MAPPING_RECORDED_ON, MAPPING_STATUS, ROLE_TOPICS, evidence_score, shared_client,
)

ROOT = Path(__file__).resolve().parent
# Display names follow docs/QUESTIONNAIRE.md; values come only from demo JSON.
LABELS = {
    'skill_01': 'Critical Thinking', 'skill_02': 'Complex Problem Solving',
    'skill_03': 'Mathematics', 'skill_04': 'Programming', 'skill_05': 'Science',
    'skill_06': 'Systems Analysis', 'skill_07': 'Operations Analysis',
    'skill_08': 'Technology Design', 'skill_09': 'Judgment and Decision Making',
    'skill_10': 'Writing', 'skill_11': 'Speaking',
    'knowledge_01': 'Computers and Electronics', 'knowledge_02': 'Mathematics',
    'knowledge_03': 'Engineering and Technology', 'knowledge_04': 'Physics',
    'knowledge_05': 'Chemistry', 'knowledge_06': 'Biology',
    'knowledge_07': 'Administration and Management',
}
RIASEC = ('Realistic', 'Investigative', 'Artistic', 'Social', 'Enterprising', 'Conventional')
LEVELS = ('No exposure', 'Basic awareness', 'Applied with guidance',
          'Independently applied', 'Advanced')


def load_demo(directory: Path = ROOT / 'data') -> tuple[dict, dict, dict]:
    """Load local fixtures only, refusing to present real data as synthetic."""
    documents = tuple(json.loads((directory / name).read_text(encoding='utf-8'))
                      for name in ('demo_profile.json', 'demo_roles.json', 'demo_trends.json'))
    if any(doc.get('data_status') != 'synthetic' for doc in documents):
        raise ValueError('This demo requires data_status="synthetic" in every input file.')
    profile, roles, trends = documents
    if any(role.get('data_status') != 'synthetic' for role in roles['roles']):
        raise ValueError('Every demo role must be marked synthetic.')
    if any(topic.get('data_status') != 'synthetic' for topic in trends['topics'].values()):
        raise ValueError('Every demo trend must be marked synthetic.')
    if len(profile['riasec']) != 6:
        raise ValueError('The profile must contain six RIASEC dimensions.')
    return documents


def load_onet(directory: Path = ROOT / 'data') -> dict:
    """Load only the official extract; never load a profile or trend fixtures."""
    official = json.loads((directory / 'onet_roles.json').read_text(encoding='utf-8'))
    if official.get('database_version') != '31.0' or official.get('data_status') != 'official_derived':
        raise ValueError('Expected O*NET 31.0 official-derived role data')
    if len(official['roles']) != 10 or any(role.get('data_status') != 'official_derived'
                                         for role in official['roles']):
        raise ValueError('The audit requires ten official-derived occupations')
    return official


def trends_from_edits(original: dict, counts: dict[str, dict[str, int]]) -> dict:
    """Apply in-session synthetic counts without overwriting fixture provenance or files."""
    result = deepcopy(original)
    for key, values in counts.items():
        if key not in result['topics']:
            raise ValueError('Cannot invent a topic outside the synthetic fixture')
        for window in ('recent', 'previous'):
            value = values[window]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError('Synthetic counts must be nonnegative integers')
            result['topics'][key][window] = value
        result['topics'][key]['simulation_edited'] = any(
            values[window] != original['topics'][key][window] for window in ('recent', 'previous'))
    return result


def audit_role(role: dict) -> dict:
    """Describe only source-derived components; no user, trend, score or ranking inference."""
    grids = {'skills': [], 'knowledge': [], 'riasec': []}
    components = {}
    for group in ('skills', 'knowledge'):
        valid = 0
        reasons = []
        for key, item in role[group].items():
            usable = (item['required'] is not None and item['importance'] is not None
                      and not item['issues'])
            valid += int(usable)
            reasons.extend(f'{key}: {issue}' for issue in item['issues'])
            for rating in item['sources'].values():
                grids[group].extend(audit_rating_rows(item['name'], key, rating))
        components[group] = {'usable': valid, 'total': len(role[group]), 'blockers': reasons,
                             'status': 'Source complete' if valid == len(role[group]) else 'Source blocked'}
    for name, rating in zip(RIASEC, role['riasec_sources']):
        grids['riasec'].extend(audit_rating_rows(name, rating['element_id'], rating))
    interest_reasons = [issue for rating in role['riasec_sources'] for issue in rating['issues']]
    components['riasec'] = {'usable': sum(v is not None for v in role['riasec']),
                            'total': 6, 'blockers': interest_reasons,
                            'status': 'Source complete' if not interest_reasons and
                            all(v is not None for v in role['riasec']) else 'Source blocked'}
    return {'code': role['code'], 'title': role['title'], 'components': components,
            'rows': grids, 'riasec_vector': list(role['riasec']),
            'blockers': list(role['data_issues']),
            'personal_component_status': {
                'S_skills': 'Not calculated: no user skill responses in audit mode',
                'K_knowledge': 'Not calculated: no user knowledge responses in audit mode',
                'S_capability': 'Not calculated: requires S_skills and K_knowledge',
                'I': 'Not calculated: no user RIASEC vector in audit mode',
                'P': 'Not calculated: requires capability and user interest similarity'}}


def audit_rating_rows(name: str, field_id: str, rating: dict) -> list[dict]:
    """Flatten raw and quality-gated values without replacing unknown flags or nulls."""
    sources = rating['source_rows'] or [{'row_number': None, 'raw': {}}]
    return [{'Item': name, 'Field ID': field_id, 'Element ID': rating['element_id'],
             'Scale': rating['scale_id'], 'Raw value': source['raw'].get('Data Value'),
             'Converted (before quality gate)': rating['normalized_raw'],
             'Usable converted value': rating['value'],
             'Recommend Suppress': source['raw'].get('Recommend Suppress', 'Not supplied'),
             'Not Relevant': source['raw'].get('Not Relevant', 'Not supplied'),
             'Blockers': '; '.join(rating['issues']) or 'None recorded',
             'File': rating['file'], 'CSV row': source['row_number'],
             'Data date': source['raw'].get('Date'),
             'Domain source': source['raw'].get('Domain Source')}
            for source in sources]


def profile_from_edits(original: dict, skills: dict, knowledge: dict,
                       riasec: list[float]) -> dict:
    """Build a new in-memory synthetic profile without modifying fixture data."""
    profile = deepcopy(original)
    profile.update(skills=dict(skills), knowledge=dict(knowledge), riasec=list(riasec))
    return profile


def fingerprint(value: Any) -> str:
    """Identify the exact local JSON inputs with a stable content hash."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]


def display_score(score: Score) -> str:
    """Format available scores without turning missing results into zero."""
    return 'Unavailable' if score.value is None else f'{score.value:.2f}'


def render_breakdown(st: Any, heading: str, breakdown: dict) -> None:
    """Show severity-ordered gaps and the underlying coverage inputs."""
    st.markdown(tr('#### {v0}', v0=display_text(heading)))
    for issue in breakdown['score'].issues:
        st.warning(translate_error(issue))
    if not breakdown['gaps']:
        st.info(tr('No valid items available. Missing data is not treated as zero.'))
        return
    st.table(table_text([{
        'Item': LABELS.get(item['id'], item['id']),
        'Your level (0–1)': item['user'],
        'Synthetic requirement (0–1)': item['required'],
        'Importance': item['importance'],
        'Coverage': item['coverage'],
        'Weighted gap': item['gap'],
    } for item in breakdown['gaps']]))
    st.caption(tr('Sorted by weighted gap, then stable item ID. Coverage is capped at 100%. A zero gap means no gap within this limited, uncalibrated assessment.'))


def render_topic(st: Any, topic: dict) -> None:
    """Show useful synthetic evidence, with stored metadata hidden behind a disclosure."""
    snapshot = topic['snapshot']
    st.markdown(tr('**{v0}**', v0=topic['id']))
    st.write(tr('Topic score: {v0} / 100 · Weight: {v1}', v0=display_value(display_score(topic['score'])), v1=topic['weight']))
    st.table(table_text([{'Window': label, 'Synthetic repositories': snapshot.get(name),
               'Start (inclusive)': snapshot.get(name + '_window', {}).get('start', 'Missing'),
               'End (exclusive)': snapshot.get(name + '_window', {}).get('end_exclusive', 'Missing')}
              for name, label in (('previous', 'Previous 90 days'), ('recent', 'Recent 90 days'))]))
    if snapshot.get('simulation_edited'):
        st.caption(tr('These counts include your in-session simulation edits.'))
    for issue in topic['score'].issues:
        st.warning(translate_error(issue))
    with st.expander(tr('Technical details'), expanded=False):
        st.caption(tr('Synthetic fixture metadata; dates are not evidence of a live fetch.'))
        st.json(snapshot, expanded=False)


def render_role(st: Any, row: dict, role: dict, profile: dict | None = None) -> None:
    """Explain the engine output using templates and its exact calculation trace."""
    st.caption(tr('O*NET occupation identity: {v0} · Synthetic requirements and trends', v0=row['code']))
    st.caption(tr('Official occupation title (English); source descriptions and identifiers are retained verbatim.'))
    cols = st.columns(3)
    cols[0].metric(tr('Skills coverage'), display_value(display_score(row['skills']['score'])))
    cols[1].metric(tr('Knowledge coverage'), display_value(display_score(row['knowledge']['score'])))
    cols[2].metric(tr('Interest similarity'), display_value(display_score(row['I'])))
    st.write(tr('Capability: **{v0}** · Personal fit: **{v1}** · Technical activity: **{v2}**', v0=display_value(display_score(row['S_capability'])), v1=display_value(display_score(row['P'])), v2=display_value(display_score(row['trend']['score']))))
    if row['moderate'].value is not None:
        p, t = row['P'].value, row['trend']['score'].value
        direction = 'raises' if t > p else 'lowers' if t < p else 'leaves unchanged'
        st.write(tr('Your skill and knowledge coverage, together with your RIASEC similarity, produce a personal fit of {v0:.2f}. The synthetic technical activity score is {v1:.2f}. Giving that signal more weight {v2} this role’s score in the fast scenario.', v0=p, v1=t, v2=display_text(direction)))
        st.write(tr('Moderate: **{v0}** (rank {v1}) · Fast: **{v2}** (rank {v3})', v0=display_value(display_score(row['moderate'])), v1=row['moderate_rank'], v2=display_value(display_score(row['fast'])), v3=row['fast_rank']))
        st.caption(tr('Scenario sensitivity · Fast − Moderate: {v0:+.2f} points · Rank movement: {v1:+d} (positive means higher in Fast).', v0=row['score_delta'], v1=row['rank_delta']))
    else:
        for issue in dict.fromkeys(row['moderate'].issues):
            st.warning(translate_error(tr('Cannot rank this role: ') + issue))
    render_breakdown(st, 'Skills gaps', row['skills'])
    render_breakdown(st, 'Knowledge gaps', row['knowledge'])
    st.markdown(tr('#### Interest profile'))
    st.table(table_text([{'Dimension': name, 'Your confirmed interest': user,
               'Synthetic role interest': target}
              for name, user, target in zip(RIASEC, (profile if profile is not None else st.session_state.simulation_profile)['riasec'], role['riasec'])]))
    st.markdown(tr('#### Trend evidence · synthetic'))
    for topic in row['trend']['topics']:
        render_topic(st, topic)
    st.markdown(tr('#### SDG contribution'))
    st.info(tr('待验证 · Pending validation. No reliable role / skill → SDG target mapping is present in these fixtures. SDG is not included in the score.'))
    st.markdown(tr('#### Source identity'))
    st.markdown(tr('[Official occupation identity]({v0})', v0=role['identity_source_url']))
    st.caption(tr('The linked page identifies only the official title and code. All requirements, importance, interests and trend counts used in this simulation are synthetic.'))
    with st.expander(tr('Technical details'), expanded=False):
        st.json(role, expanded=False)
        st.json(asdict(row['S_capability']), expanded=False)
        st.json(json.dumps(row, default=asdict), expanded=False)


def main() -> None:
    """Run the local Streamlit interface, importing Streamlit only at launch."""
    import streamlit as st
    from src.i18n import LANGUAGE_OPTIONS, initialize_language, language_name

    initialize_language(st.session_state)

    st.set_page_config(page_title='FutureShift AI', page_icon='↗', layout='wide')
    st.markdown('<style>\n    .stApp {background: linear-gradient(145deg, #f2f6fb, #fafbff 65%); color: #14283f;}\n    .block-container {max-width: 1240px; padding-top: 2.8rem;}\n    h1, h2, h3 {letter-spacing: -.035em; color: #14283f;}\n    [data-testid="stMetric"] {background: #fff; border: 1px solid #dce5ef;\n      border-radius: 14px; padding: 16px;}\n    [data-testid="stExpander"] {background: #fff; border-radius: 12px;}\n    [data-testid="stForm"] {background: #fff; border-radius: 16px;}\n    .eyebrow {color: #187c76; font-size: .8rem; font-weight: 700;\n      letter-spacing: .14em; text-transform: uppercase;}\n    </style>', unsafe_allow_html=True)
    st.markdown(tr('<div class="eyebrow">Students & Recent Graduates · Career exploration</div>'), unsafe_allow_html=True)
    title_column, language_column = st.columns([5, 2])
    with title_column:
        st.title(tr('FutureShift AI'))
    with language_column:
        st.selectbox('🌐', LANGUAGE_OPTIONS, key='ui_language',
                     format_func=language_name, label_visibility='visible')
    st.markdown(tr('### Navigate change. Shape your future.'))
    st.write(tr('Explore how your capabilities and interests connect to different career pathways.'))
    st.info(tr('Start with Career pathway prototype for the guided student questionnaire. Use Synthetic simulation to edit a demo profile and compare two career scenarios. Use O*NET data audit to inspect official occupational data and GitHub activity evidence. GitHub activity scores are not hiring demand or employment-growth forecasts.'))
    mode = st.radio(tr('Mode'), ('Career pathway prototype', 'Synthetic simulation', 'O*NET data audit'),
                    horizontal=True, key='page_mode', format_func=translated_options())
    if mode != 'Career pathway prototype':
        from src.cv_intake import clear_cv_review
        clear_cv_review(st.session_state)
    try:
        if mode == 'Career pathway prototype':
            render_pathway(st, LABELS, LEVELS, load_demo, render_role, load_onet, get_trend_client)
        elif mode == 'Synthetic simulation':
            render_simulation(st)
        else:
            render_audit(st)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(translate_error(tr('Unable to load or process this mode’s local data: {v0}', v0=exc)))


def render_simulation(st: Any) -> None:
    """Render the synthetic-only editing and matching workflow."""
    original, role_file, trend_file = load_demo()
    roles = role_file['roles']
    st.warning(tr('所有画像、职业要求和趋势数值均为合成演示数据，不能代表真实劳动力市场。'))
    st.caption(tr('SYNTHETIC SIMULATION · All profile, requirement and trend values are invented for demonstration. Edit them to explore the workflow; these are not real labour-market predictions.'))
    with st.expander(tr('Technical details'), expanded=False):
        st.caption(tr('Sources: demo_profile.json, demo_roles.json and demo_trends.json only.'))
        st.caption(tr('Scoring: {v0} · Fixture snapshot: {v1}', v0=SCORING_VERSION, v1=fingerprint((role_file, trend_file))))
    st.subheader(tr('01 / Your demo profile'))
    st.caption(tr('Edit the three skills, two knowledge areas and six interest dimensions in the demo. Results use only your confirmed simulation inputs; fixture files stay unchanged.'))
    with st.form('simulation_editor'):
        columns = st.columns(3)
        edits: dict[str, dict] = {'skills': {}, 'knowledge': {}}
        for column, group, title in zip(columns[:2], ('skills', 'knowledge'), ('Skills', 'Knowledge')):
            with column:
                st.markdown(tr('#### {v0}', v0=display_text(title)))
                for key, value in sorted(original[group].items()):
                    edits[group][key] = st.selectbox(
                        display_text(LABELS.get(key, key)), options=[None, 0, 1, 2, 3, 4],
                        index=0 if value is None else value + 1,
                        format_func=translated_options(lambda n: 'Unanswered' if n is None else f'{n} · {LEVELS[n]}'),
                        key=f'simulation_edit_{key}')

        with columns[2]:
            st.markdown(tr('#### Interests · RIASEC'))
            st.caption(tr('Edit the already-normalized demo vector (0–1). These controls are not a validated interest questionnaire.'))
            interests = [st.slider(display_text(name), 0.0, 1.0, float(value), 0.05, key=f'simulation_interest_{i}')
                         for i, (name, value) in enumerate(zip(RIASEC, original['riasec']))]
        st.markdown(tr('#### Synthetic trend inputs'))
        st.caption(tr('Change the recent or previous 90-day counts to test sensitivity. Submit to recalculate; this is a simulation, not a data refresh.'))
        count_edits = {}
        for key, snapshot in sorted(trend_file['topics'].items()):
            st.markdown(tr('**{v0}**', v0=key))
            left, right = st.columns(2)
            recent = left.number_input(tr('Recent 90-day count'), min_value=0, value=snapshot['recent'],
                                       step=1, key=f'simulation_recent_{key}')
            previous = right.number_input(tr('Previous 90-day count'), min_value=0, value=snapshot['previous'],
                                          step=1, key=f'simulation_previous_{key}')
            count_edits[key] = {'recent': recent, 'previous': previous}
        st.caption(tr('Review your selections above. Results update only when you confirm and submit.'))
        confirmed = st.checkbox(tr('I confirm this synthetic profile for matching.'), key='simulation_confirm')
        submitted = st.form_submit_button(tr('Confirm profile & calculate matches'), type='primary')
    if submitted:
        if confirmed:
            st.session_state.simulation_profile = profile_from_edits(
                original, edits['skills'], edits['knowledge'], interests)
            st.session_state.simulation_trends = trends_from_edits(trend_file, count_edits)
        else:
            st.warning(tr('Confirm the profile before calculating. Any previous results remain unchanged.'))
    if 'simulation_profile' not in st.session_state:
        st.info(tr('Choose your levels, confirm the profile and submit to explore both scenarios.'))
        return
    profile = st.session_state.simulation_profile
    confirmed_trends = st.session_state.simulation_trends
    trends = confirmed_trends['topics']
    st.caption(tr('Results reflect your last confirmed inputs. Reconfirm and submit to apply further edits.'))
    with st.expander(tr('Technical details'), expanded=False):
        st.caption(tr('Confirmed profile: {v0} · Trends: {v1}', v0=fingerprint(profile), v1=fingerprint(confirmed_trends)))
        st.json(profile, expanded=False)
    rows = rank_roles(profile, roles, trends)
    eligible = [row for row in rows if row['moderate_rank'] is not None]
    st.subheader(tr('02 / Two scenarios. More perspective.'))
    st.write(tr('Both scenarios use the same confirmed synthetic profile, requirements and trends. Only the trend weight changes. Scores describe prototype fit, not career outlook probabilities.'))
    if len(eligible) < 5:
        st.info(translate_error(tr('{v0} of {v1} demo roles can be ranked; showing all available results rather than inventing five recommendations.', v0=len(eligible), v1=len(roles))))
    for column, scenario, label, weight in zip(st.columns(2), ('moderate', 'fast'),
            ('Moderate', 'Fast disruption'), (MODERATE_LAMBDA, FAST_LAMBDA)):
        with column:
            st.markdown(tr('### {v0}', v0=display_text(label)))
            st.caption(tr('{v0:.0%} personal fit + {v1:.0%} technical activity', v0=1 - weight, v1=weight))
            selected = sorted(eligible, key=lambda r: r[scenario + '_rank'])[:5]
            for row in selected:
                st.markdown(tr('**{v0:02d} · {v1}**', v0=row[scenario + '_rank'], v1=row['title']))
                st.progress(row[scenario].value / 100,
                            text=tr('{v0:.2f} / 100 · {v1}', v0=row[scenario].value, v1=row['code']))
    st.subheader(tr('03 / Understand each match'))
    shown = {r['code'] for scenario in ('moderate', 'fast')
             for r in sorted(eligible, key=lambda r: r[scenario + '_rank'])[:5]}
    roles_by_code = {role['code']: role for role in roles}
    for row in rows:
        if row['code'] in shown or row['moderate_rank'] is None:
            suffix = 'View details' if row['moderate_rank'] is not None else 'Unavailable · view reasons'
            with st.expander(tr('{v0} · {v1}', v0=row['title'], v1=display_text(suffix))):
                render_role(st, row, roles_by_code[row['code']])
    with st.expander(tr('Technical details'), expanded=False):
        st.markdown(tr('#### How scoring works & what remains uncertain'))
        st.code('S_capability = 0.75 × S_skills + 0.25 × K_knowledge\n'
                'P = 0.70 × S_capability + 0.30 × I\n'
                'T_k = 50 + 50 × clip(log2((Recent + 20)/(Previous + 20)), -1, 1)\n'
                'T = weighted average of mapped topic scores\n'
                'Match = (1 − lambda) × P + lambda × T\n'
                'Moderate: lambda = 0.15 | Fast disruption: lambda = 0.35')
        st.write(tr('These weights and smoothing parameter 20 are unvalidated prototype assumptions. Technical activity is not job demand, wages or employment growth. Self-ratings and occupational requirements are different measurement systems; normalization does not validate their equivalence. Scenario sensitivity is not statistical confidence. Missing inputs block complete ranking; no values are imputed.'))
        st.write(tr('This mode reads only the three demo JSON files. All edits are local simulation inputs; the original fixtures are not overwritten. SDG mappings remain pending validation and do not affect scoring. Career choices remain yours.'))


def get_trend_client() -> GitHubTrends:
    """Share the anonymous request budget across sessions; never fetch on construction."""
    return shared_client(ROOT / 'data/cache/github_trends.json')


def render_trend_breakdown(st: Any, snapshot: dict, score: Score) -> None:
    """Display original cached counts and explain the unchanged topic-weighted formula."""
    st.markdown(tr('#### Raw repository counts · by topic and 90-day window'))
    st.caption(tr('Dates below come from this snapshot, including when it is cached or expired. Start is inclusive; end is exclusive. Counts are repositories, not job postings.'))
    weights = snapshot['topic_weights']
    total_weight = sum(weights.values())
    terms = []
    topic_formulas = []
    for topic, weight in weights.items():
        record = snapshot['topics'][topic]
        topic_score = github_trend(record['recent'], record['previous'])
        st.markdown(tr('**{v0}**', v0=topic))
        st.table(table_text([{
            'Window': label,
            'Start date (UTC, inclusive)': record[name + '_window']['start'],
            'End date (UTC, exclusive)': record[name + '_window']['end_exclusive'],
            'Repository count': record[name],
        } for name, label in (('previous', 'Previous 90 days'), ('recent', 'Recent 90 days'))]))
        st.write(tr('Topic weight: **{v0:g}** · Normalized share: **{v1:.0%}** · Topic score T_k: **{v2} / 100**', v0=weight, v1=weight / total_weight, v2=display_value(display_score(topic_score))))
        topic_formulas.append(f"{topic}: T_k = 50 + 50 × clip(log2(({record['recent']} + 20) / "
                              f"({record['previous']} + 20)), -1, 1) = {display_value(display_score(topic_score))}")
        terms.append(f'{weight:g} × {display_value(display_score(topic_score))}')
    st.caption(tr('The occupation trend score is the equally weighted average of its two topic scores. Overlapping topic counts are not added together. This is an activity indicator, not a hiring-demand forecast.'))
    with st.expander(tr('Technical details'), expanded=False):
        st.markdown(tr('#### How the occupation activity score T is calculated'))
        for formula in topic_formulas:
            st.code(formula)
        st.code('T = sum(weight_k × T_k) / sum(weight_k)\n'
                + 'T = (' + ' + '.join(terms) + ') / '
                + f'{total_weight:g} = {display_value(display_score(score))}')
        st.caption(tr('Smoothing parameter: 20. Log-ratio clipping: −1…1. Displayed scores are rounded; scoring uses unrounded values. These are unvalidated prototype assumptions.'))


def render_live_trends(st: Any, official: dict, client: GitHubTrends | None = None) -> None:
    """Show per-role API evidence; only a clicked Refresh can initiate HTTP calls."""
    st.subheader(tr('GitHub repository activity · evidence only'))
    st.warning(tr('GitHub 仓库活动只是开源活动代理指标，不等于招聘数量、工资或就业增长预测。'))
    st.info(translate_error(tr('Mapping status: {v0} · Prototype hypothesis, not yet validated. Recorded: {v1}.', v0=display_text(MAPPING_STATUS), v1=MAPPING_RECORDED_ON)))
    st.caption(tr('Only the three user-confirmed occupation/topic mappings can be queried. No demo profile, synthetic requirements or synthetic trends are read. No personal fit, scenario total or career ranking is produced.'))
    if not ROLE_TOPICS:
        st.info(tr('No exact real-query mapping is recorded yet. Refresh remains disabled until the three occupation/topic mappings are confirmed in DATA_SOURCES.md.'))
        return
    active_client = client if client is not None else get_trend_client()
    with st.expander(tr('Technical details'), expanded=False):
        st.caption(tr('Anonymous requests: at most 10 per rolling minute, shared in this process. Each uncached successful Refresh sends 4 requests for ONE occupation (2 topics × 2 windows). Fresh cache reuse sends 0; a failure stops early. Successful snapshots are reused for 15 minutes. Server limits may be stricter. A failed refresh retains the last complete successful snapshot, including its original dates.'))
    by_code = {role['code']: role for role in official['roles']}
    for code in ROLE_TOPICS:
        role = by_code.get(code)
        if role is None:
            st.error(translate_error(tr('Approved occupation {v0} is missing from the official extract; no query sent.', v0=code)))
            continue
        with st.expander(tr('GitHub evidence · {v0} · {v1}', v0=code, v1=role['title'])):
            st.caption(tr('Topics: ') + ', '.join(ROLE_TOPICS[code]))
            clicked = st.button(tr('Refresh'), key=f'github_refresh_{code}')
            outcome = active_client.refresh(code) if clicked else active_client.cached(code)
            if outcome.get('error'):
                st.warning(tr('The update could not be completed. Any available saved evidence is shown below.'))
            snapshot = outcome.get('snapshot')
            if snapshot is None:
                st.info(tr('No successful API evidence for this occupation. Use Refresh to fetch; an absent or failed result is not a zero count.'))
                with st.expander(tr('Technical details'), expanded=False):
                    if outcome.get('error'):
                        st.error(translate_error(outcome['error']))
                continue
            if outcome['expired']:
                st.warning(tr('Showing older saved evidence. Review the window dates before interpreting it.'))
            score = evidence_score(snapshot, code)
            st.write(tr('GitHub activity trend score T: **{v0} / 100**', v0=display_value(display_score(score))))
            if score.issues:
                st.warning(tr('This evidence could not be scored. See Technical details for the reason.'))
            if score.value is not None:
                render_trend_breakdown(st, snapshot, score)
            if role['data_issues']:
                st.warning(tr('Some official occupational data needs review. The trend score does not remove those limitations or produce an overall career match.'))
            with st.expander(tr('Technical details'), expanded=False):
                st.write(tr('Cache state:'), {'cached': outcome['cached'], 'expired': outcome['expired']})
                st.caption(tr('Fetched: {v0} · Cached: {v1} · Window reference date (UTC): {v2}', v0=snapshot['fetched_at'], v1=snapshot['cached_at'], v2=snapshot['as_of']))
                if outcome.get('error'):
                    st.error(translate_error(outcome['error']))
                if outcome.get('message'):
                    st.info(translate_error(outcome['message']))
                for issue in score.issues:
                    st.error(translate_error(issue))
                for issue in role['data_issues']:
                    st.warning(translate_error(issue))
                st.json(snapshot, expanded=False)
                st.caption(tr('Original queries, source URLs, fetch timestamps and count metadata. Cached snapshots retain their original windows and timestamps.'))
    st.caption(tr('The other seven occupations have no approved query mapping and are not queried.'))


def render_audit(st: Any) -> None:
    """Render official source evidence only; never read simulation state or calculate ranks."""
    official = load_onet()
    st.info(tr('O*NET® 31.0 data audit · Official occupational requirements only. Not a future employment-demand forecast. No simulation data is loaded.'))
    st.caption(tr('Official occupation title (English); source descriptions and identifiers are retained verbatim.'))
    st.write(official['license']['attribution'])
    st.markdown(tr('[O*NET® 31.0 Database](https://www.onetcenter.org/database.html) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)'))
    st.caption(display_text(official['license']['modifications']))
    st.caption(tr('Release: {v0} · Official access date: {v1}', v0=official['released'], v1=official['accessed_on']))
    st.write(tr('This mode can inspect normalized importance, requirement levels and occupational RIASEC vectors. Skill coverage, knowledge coverage, interest similarity and personal fit need user responses, so they are not calculated here. No scenario totals or rankings are produced. Conversion to 0–1 is not measurement-validity calibration.'))
    with st.expander(tr('Technical details'), expanded=False):
        st.markdown(tr('#### Source files, transformations & quality policy'))
        st.json(official['sources'], expanded=False)
        st.json(official['transformations'], expanded=False)
    render_live_trends(st, official)
    audits = [audit_role(role) for role in official['roles']]
    st.subheader(tr('Ten occupations · source component availability'))
    st.caption(tr('Listed by official occupation code, not suitability or score.'))
    st.table(table_text([{'Code': row['code'], 'Official title': row['title'],
               'Usable skill pairs': f"{row['components']['skills']['usable']}/11",
               'Usable knowledge pairs': f"{row['components']['knowledge']['usable']}/7",
               'Usable RIASEC dimensions': f"{row['components']['riasec']['usable']}/6"}
              for row in audits]))
    for role, audit in zip(official['roles'], audits):
        with st.expander(tr('{v0} · {v1}', v0=role['code'], v1=role['title'])):
            st.markdown(tr('[Official occupation identity]({v0})', v0=role['identity_source_url']))
            st.markdown(tr('#### Available source components'))
            for group in ('skills', 'knowledge', 'riasec'):
                component = audit['components'][group]
                st.write(tr('{v0}: {v1}/{v2} usable · {v3}', v0=display_text(group.title()), v1=component['usable'], v2=component['total'], v3=display_text(component['status'])))
            if audit['blockers']:
                st.warning(tr('Some ratings have missing, low-precision, not-applicable or unconfirmed quality information. Affected components remain unavailable.'))
            else:
                st.info(tr('No source blockers recorded. Personal matching would still require a user profile.'))
            st.caption(tr('This view audits occupational data; it does not calculate your personal match.'))
            with st.expander(tr('Technical details'), expanded=False):
                st.write(tr('Occupational RIASEC vector (R/I/A/S/E/C):'), audit['riasec_vector'])
                st.json(audit['personal_component_status'], expanded=False)
                st.markdown(tr('#### Quality flags & blocking reasons'))
                for issue in audit['blockers']:
                    st.warning(translate_error(issue))
                st.caption(tr('Suppress=Y: low precision; Not Relevant=Y: not applicable; unknown: quality not established. Missing records remain unavailable. No values are filled or bypassed.'))
                for group, label in (('skills', 'Skills'), ('knowledge', 'Knowledge'), ('riasec', 'RIASEC')):
                    st.markdown(tr('#### {v0} · raw values, scales & conversions', v0=display_text(label)))
                    st.dataframe(table_text(audit['rows'][group]), hide_index=True)


if __name__ == '__main__':
    main()
