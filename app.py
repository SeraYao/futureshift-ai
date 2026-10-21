"""Local synthetic-data Streamlit demo. Run: python3 -m streamlit run app.py."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from src.scoring import (
    FAST_LAMBDA, MODERATE_LAMBDA, SCORING_VERSION, Score, rank_roles,
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
    st.markdown(f'#### {heading}')
    for issue in breakdown['score'].issues:
        st.warning(issue)
    if not breakdown['gaps']:
        st.info('No valid items available. Missing data is not treated as zero.')
        return
    st.table([{
        'Item': LABELS.get(item['id'], item['id']),
        'Your level (0–1)': item['user'],
        'Synthetic requirement': item['required'],
        'Importance': item['importance'],
        'Coverage': item['coverage'],
        'Weighted gap': item['gap'],
    } for item in breakdown['gaps']])
    st.caption('Sorted by weighted gap, then stable item ID. Coverage is capped at 100%. '
               'A zero gap means no gap within this limited synthetic assessment.')


def render_topic(st: Any, topic: dict) -> None:
    """Present all stored provenance, explicitly distinguishing fixtures from live data."""
    snapshot = topic['snapshot']
    st.markdown(f"**{topic['id']}**")
    st.write(f"Topic score: {display_score(topic['score'])} / 100 · Weight: {topic['weight']}")
    st.write('Synthetic repository counts:', {
        'Recent 90 days': snapshot.get('recent'),
        'Previous 90 days': snapshot.get('previous'),
    })
    st.write('Recent window (end exclusive):', snapshot.get('recent_window', 'Missing'))
    st.write('Previous window (end exclusive):', snapshot.get('previous_window', 'Missing'))
    st.text('Query: ' + str(snapshot.get('query', 'Missing')))
    st.text('Snapshot timestamp: ' + str(snapshot.get('queried_at', 'Missing')))
    st.text('Cache timestamp: ' + str(snapshot.get('cached_at', 'Missing')))
    st.write('Stored metadata:', {
        'data_status': snapshot.get('data_status', 'Missing'),
        'cached': snapshot.get('cached', 'Unknown'),
        'expired': snapshot.get('expired', 'Unknown'),
    })
    st.caption('Cache / expiry flags above are fixture metadata, not a live freshness check. '
               'No real-data expiry policy is configured.')
    st.write('Source:', snapshot.get('source_note', 'Missing source information'))
    if snapshot.get('source_url'):
        st.markdown(f"[Stored source URL]({snapshot['source_url']})")
    else:
        st.caption('Source URL: none — synthetic fixture; no GitHub request performed.')
    for issue in topic['score'].issues:
        st.warning(issue)


def render_role(st: Any, row: dict, role: dict) -> None:
    """Explain the engine output using templates and its exact calculation trace."""
    st.caption(f"O*NET occupation identity: {row['code']} · Synthetic requirements and trends")
    cols = st.columns(3)
    cols[0].metric('Skills coverage', display_score(row['skills']['score']))
    cols[1].metric('Knowledge coverage', display_score(row['knowledge']['score']))
    cols[2].metric('Interest similarity', display_score(row['I']))
    st.write(f"Capability: **{display_score(row['S_capability'])}** · "
             f"Personal fit: **{display_score(row['P'])}** · "
             f"Technical activity: **{display_score(row['trend']['score'])}**")
    if row['moderate'].value is not None:
        p, t = row['P'].value, row['trend']['score'].value
        direction = 'raises' if t > p else 'lowers' if t < p else 'leaves unchanged'
        st.write(f"Your skill and knowledge coverage, together with your RIASEC similarity, "
                 f"produce a personal fit of {p:.2f}. The synthetic technical activity score "
                 f"is {t:.2f}. Giving that signal more weight {direction} this role’s score "
                 f"in the fast scenario.")
        st.write(f"Moderate: **{display_score(row['moderate'])}** (rank {row['moderate_rank']}) · "
                 f"Fast: **{display_score(row['fast'])}** (rank {row['fast_rank']})")
        st.caption(f"Scenario sensitivity · Fast − Moderate: {row['score_delta']:+.2f} points · "
                   f"Rank movement: {row['rank_delta']:+d} (positive means higher in Fast).")
    else:
        for issue in dict.fromkeys(row['moderate'].issues):
            st.warning('Cannot rank this role: ' + issue)
    render_breakdown(st, 'Skills gaps', row['skills'])
    render_breakdown(st, 'Knowledge gaps', row['knowledge'])
    st.markdown('#### Interest profile')
    st.table([{'Dimension': name, 'Your confirmed interest': user,
               'Synthetic role interest': target}
              for name, user, target in zip(RIASEC, st.session_state.confirmed_profile['riasec'], role['riasec'])])
    st.markdown('#### Trend evidence · synthetic')
    for topic in row['trend']['topics']:
        render_topic(st, topic)
    st.markdown('#### SDG contribution')
    st.info('待验证 · Pending validation. No reliable role / skill → SDG target mapping '
            'is present in these fixtures. SDG is not included in the score.')
    st.markdown('#### Sources & calculation trace')
    st.markdown(f"[Official occupation identity]({role['identity_source_url']})")
    st.caption('This link identifies the real title and code only. Requirements, importance, '
               'RIASEC values and topic mappings shown here are synthetic, not O*NET ratings.')
    st.json(asdict(row['S_capability']))
    st.json(json.dumps(row, default=asdict), expanded=False)


def main() -> None:
    """Run the local Streamlit interface, importing Streamlit only at launch."""
    import streamlit as st

    st.set_page_config(page_title='FutureShift AI', page_icon='↗', layout='wide')
    st.markdown('''<style>
    .stApp {background: linear-gradient(145deg, #f2f6fb, #fafbff 65%); color: #14283f;}
    .block-container {max-width: 1240px; padding-top: 2.8rem;}
    h1, h2, h3 {letter-spacing: -.035em; color: #14283f;}
    [data-testid="stMetric"] {background: #fff; border: 1px solid #dce5ef;
      border-radius: 14px; padding: 16px;}
    [data-testid="stExpander"] {background: #fff; border-radius: 12px;}
    [data-testid="stForm"] {background: #fff; border-radius: 16px;}
    .eyebrow {color: #187c76; font-size: .8rem; font-weight: 700;
      letter-spacing: .14em; text-transform: uppercase;}
    </style>''', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">Students & Recent Graduates · Career exploration</div>', unsafe_allow_html=True)
    st.title('FutureShift AI')
    st.markdown('### Navigate change. Shape your future.')
    st.write('Explore how your capabilities and interests connect to different career pathways.')
    st.warning('演示数据为合成数据，不代表真实劳动力市场预测')
    st.caption('SYNTHETIC DEMO · All requirements, interests and repository counts are test values. '
               'No live data, model calls or employment predictions.')
    try:
        original, role_file, trend_file = load_demo()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f'Unable to load the local synthetic fixtures: {exc}')
        st.stop()
    roles, trends = role_file['roles'], trend_file['topics']
    with st.sidebar:
        st.markdown('## Explore your options')
        st.write('01 · Edit your demo profile')
        st.write('02 · Confirm and calculate')
        st.write('03 · Compare possible futures')
        st.divider()
        st.caption('Local prototype · No account needed. Edits stay in this browser session; '
                   'the JSON fixtures are never overwritten.')
        st.caption(f'Scoring: {SCORING_VERSION}')
        st.caption(f'Data snapshot: {fingerprint((role_file, trend_file))}')
    st.subheader('01 / Your demo profile')
    st.caption('Only the fields present in the local demo are shown: three skills, two knowledge '
               'areas and six normalized interest dimensions. This is a limited assessment.')
    with st.form('profile_editor'):
        columns = st.columns(3)
        edits: dict[str, dict] = {'skills': {}, 'knowledge': {}}
        for column, group, title in zip(columns[:2], ('skills', 'knowledge'), ('Skills', 'Knowledge')):
            with column:
                st.markdown(f'#### {title}')
                for key, value in sorted(original[group].items()):
                    edits[group][key] = st.select_slider(
                        LABELS.get(key, key), options=list(range(5)), value=value,
                        format_func=lambda n: f'{n} · {LEVELS[n]}', key=f'edit_{key}')
                    st.caption(f'Normalized value = selected level / 4 · {key}')
        with columns[2]:
            st.markdown('#### Interests · RIASEC')
            st.caption('Edit the already-normalized demo vector (0–1). '
                       'These controls are not a validated interest questionnaire.')
            interests = [st.slider(name, 0.0, 1.0, float(value), 0.05, key=f'interest_{i}')
                         for i, (name, value) in enumerate(zip(RIASEC, original['riasec']))]
        st.caption('Review your selections above. Results update only when you confirm and submit.')
        confirmed = st.checkbox('I confirm this synthetic profile for matching.', key='confirm_profile')
        submitted = st.form_submit_button('Confirm profile & calculate matches', type='primary')
    if submitted:
        if confirmed:
            st.session_state.confirmed_profile = profile_from_edits(
                original, edits['skills'], edits['knowledge'], interests)
        else:
            st.warning('Confirm the profile before calculating. Any previous results remain unchanged.')
    if 'confirmed_profile' not in st.session_state:
        st.info('Choose your levels, confirm the profile and submit to explore both scenarios.')
        return
    profile = st.session_state.confirmed_profile
    st.caption(f'Results use confirmed profile {fingerprint(profile)}. Unsubmitted edits do not '
               'change these results. Reconfirm and submit to update.')
    with st.expander('Review the confirmed scoring inputs'):
        st.json(profile)
    rows = rank_roles(profile, roles, trends)
    eligible = [row for row in rows if row['moderate_rank'] is not None]
    st.subheader('02 / Two scenarios. More perspective.')
    st.write('Both scenarios use the same confirmed profile and synthetic data. Only the trend '
             'weight changes. Scores describe prototype fit, not career outlook probabilities.')
    if len(eligible) < 5:
        st.info(f'{len(eligible)} of {len(roles)} demo roles can be ranked; showing all available '
                'results rather than inventing five recommendations.')
    for column, scenario, label, weight in zip(st.columns(2), ('moderate', 'fast'),
            ('Moderate', 'Fast disruption'), (MODERATE_LAMBDA, FAST_LAMBDA)):
        with column:
            st.markdown(f'### {label}')
            st.caption(f'{1-weight:.0%} personal fit + {weight:.0%} technical activity')
            selected = sorted(eligible, key=lambda r: r[scenario + '_rank'])[:5]
            for row in selected:
                st.markdown(f"**{row[scenario + '_rank']:02d} · {row['title']}**")
                st.progress(row[scenario].value / 100,
                            text=f"{row[scenario].value:.2f} / 100 · {row['code']}")
    st.subheader('03 / Understand each match')
    shown = {r['code'] for scenario in ('moderate', 'fast')
             for r in sorted(eligible, key=lambda r: r[scenario + '_rank'])[:5]}
    roles_by_code = {role['code']: role for role in roles}
    for row in rows:
        if row['code'] in shown or row['moderate_rank'] is None:
            suffix = 'View details' if row['moderate_rank'] is not None else 'Unavailable · view reasons'
            with st.expander(f"{row['title']} · {suffix}"):
                render_role(st, row, roles_by_code[row['code']])
    with st.expander('How scoring works & what remains uncertain'):
        st.code('S_capability = 0.75 × S_skills + 0.25 × K_knowledge\n'
                'P = 0.70 × S_capability + 0.30 × I\n'
                'T_k = 50 + 50 × clip(log2((Recent + 20)/(Previous + 20)), -1, 1)\n'
                'T = weighted average of mapped topic scores\n'
                'Match = (1 − lambda) × P + lambda × T\n'
                'Moderate: lambda = 0.15 | Fast disruption: lambda = 0.35')
        st.write('These weights and smoothing parameter 20 are unvalidated prototype assumptions. '
                 'Technical activity is not job demand, wages or employment growth. '
                 'Self-ratings and occupational requirements are different measurement systems; '
                 'normalization does not validate their equivalence. Scenario sensitivity is not '
                 'statistical confidence. Missing inputs block complete ranking; no values are imputed.')
        st.write('Only local demo_profile.json, demo_roles.json and demo_trends.json are read. '
                 'No trend refresh or real-data ingestion is implemented. Career choices remain yours.')


if __name__ == '__main__':
    main()
