"""Quality-gated official careers; one scoring engine and separate evidence cohorts."""
from copy import deepcopy
from src.scoring import rank_roles
from src.i18n import tr, career_name, table_text, display_text

CATALOG_VERSION = 'official-cross-domain-v1'


def quality_issues(role):
    # O*NET Not Relevant=Y means the occupation is outside the scope of that
    # element. Omit only that dimension from this role's denominator; never use
    # its LV value (which can also be suppressed). The UI reports this partial
    # coverage explicitly. All other missing/unknown/suppressed values block.
    omitted = _not_relevant_dimensions(role)
    issues = [issue for issue in role.get('data_issues', [])
              if not any(issue.startswith(key + ' ') or issue.startswith(key + ':')
                         for key in omitted)]
    for group in ('skills', 'knowledge'):
        if not role.get(group):
            issues.append(group + ': empty requirements')
        for key, item in role.get(group, {}).items():
            if key in omitted:
                continue
            issues.extend(key + ': ' + issue for issue in item.get('issues', []))
            for rating in item.get('sources', {}).values():
                issues.extend(key + ': ' + issue for issue in rating.get('issues', []))
    return list(dict.fromkeys(issues))


def _not_relevant_dimensions(role):
    omitted = set()
    for group in ('skills', 'knowledge'):
        for key, item in role.get(group, {}).items():
            lv = item.get('sources', {}).get('LV', {})
            rows = lv.get('source_rows', [])
            if (len(rows) == 1 and rows[0].get('raw', {}).get('Not Relevant') == 'Y'):
                omitted.add(key)
    return omitted


def official_ranking(profile, dataset):
    # Score only O*NET-applicable dimensions. An explicit Not Relevant flag is
    # recorded as omitted coverage, never converted to a zero requirement.
    scoring_roles = deepcopy(dataset['roles'])
    roles = {r['code']: r for r in dataset['roles']}
    for role in scoring_roles:
        omitted = _not_relevant_dimensions(role)
        for group in ('skills', 'knowledge'):
            for key in omitted:
                role[group].pop(key, None)
    rows = rank_roles(profile, scoring_roles, {})
    for row in rows:
        source = roles[row['code']]
        row['assessment_coverage'] = {
            'skills': f"{len(source['skills']) - len(_not_relevant_dimensions(source) & set(source['skills']))}/{len(source['skills'])}",
            'knowledge': f"{len(source['knowledge']) - len(_not_relevant_dimensions(source) & set(source['knowledge']))}/{len(source['knowledge'])}",
            'interests': f"{len(source.get('riasec', []))}/6",
            'omitted': [display_text(source[g][key]['name']) for g in ('skills', 'knowledge')
                        for key in sorted(_not_relevant_dimensions(source) & set(source.get(g, {})))],
        }
    eligible = [r for r in rows if r['P'].value is not None and not quality_issues(roles[r['code']])]
    for i, row in enumerate(sorted(eligible, key=lambda r: (-r['P'].value, r['code'])), 1):
        row['personal_rank'] = i
    for row in rows:
        row.setdefault('personal_rank', None)
    return sorted(rows, key=lambda r: (r['personal_rank'] is None, r['personal_rank'] or 0, r['code']))


def render_official(st, profile, draft, dataset, labels, render_role, client_factory=None):
    from src.reassessment import store_assessment, begin_reassessment
    from src.learning_plan import render_learning_plan
    rows = official_ranking(profile, dataset)
    eligible = [r for r in rows if r['personal_rank'] is not None]
    current = st.session_state.get('pathway_assessment')
    if current and current['roles'].get('data_status') != 'official_derived':
        st.info(tr('Your previous demo career and plan are retained. Confirm before starting official career matching; your profile is unchanged.'))
        if not st.button(tr('Confirm official career matching'), key='confirm_official_catalog'):
            return
        st.session_state['archived_demo_assessment'] = deepcopy(current)
        st.session_state.pop('pathway_assessment', None)
        st.session_state.pop('pathway_previous', None)
        for key in list(st.session_state):
            if key.startswith(('learning_role', 'learning_hours')):
                del st.session_state[key]
        current = None
    if current is None or current['profile'] != profile or current['answers'] != draft:
        current = store_assessment(st.session_state, profile, draft, rows, dataset, {'topics': {}})
    st.caption(tr('Official O*NET 31.0 requirements. Cross-domain order uses personal fit only: 70% capability + 30% interest; capability is 75% skills + 25% knowledge.'))
    st.warning(tr('Limited questionnaire coverage: 11 skills, 7 knowledge areas and RIASEC. Unasked abilities, credentials, experience requirements and other knowledge are not scored or treated as zero. These are exploration suggestions, not qualification assessments.'))
    st.caption(tr('Official expert knowledge ratings may omit optional precision statistics. Blank flags are preserved as unavailable precision, never relabelled as N; explicit suppression and relevance blocks remain enforced.'))
    st.warning(tr('Some official matches use partial questionnaire coverage. Coverage is shown per career; scores with different omitted dimensions are exploratory and not fully comparable. Not Relevant areas are excluded from that career denominator, never treated as zero.'))
    st.table(table_text([{'Career': career_name(r['code'], r['title']), 'Questionnaire coverage':
                          tr('{v0} skills · {v1} knowledge · {v2} interests{v3}',
                             v0=r['assessment_coverage']['skills'], v1=r['assessment_coverage']['knowledge'],
                             v2=r['assessment_coverage']['interests'],
                             v3=(' · excludes ' + ', '.join(r['assessment_coverage']['omitted']))
                             if r['assessment_coverage']['omitted'] else ''),
                          'Personal fit': r['P'].value, 'Rank': r['personal_rank']} for r in eligible]))
    st.info(tr('No comparable labour-demand evidence is available across these careers. Trend and scenario scores are unavailable, not zero or decline. GitHub activity is not used to rank these domains.'))
    roles = {r['code']: r for r in dataset['roles']}
    for row in eligible:
        with st.expander(career_name(row['code'], row['title']) + tr(' · Why this match?')):
            render_role(st, row, roles[row['code']], profile=profile)
    with st.expander(tr('Excluded official careers and data-quality reasons')):
        for row in rows:
            if row['personal_rank'] is None:
                st.write(career_name(row['code'], row['title']) + ' · ' + row['code'])
                for reason in quality_issues(roles[row['code']]):
                    st.caption(reason)
    if st.button(tr('Update my profile and reassess'), key='pathway_reassess'):
        begin_reassessment(st.session_state)
        st.rerun()
    render_learning_plan(st, eligible, roles, labels, draft.get('Weekly learning time'), current,
                         st.session_state.get('pathway_previous'))

    from src.sdg import render_dynamic_sdg
    render_dynamic_sdg(st, eligible, roles, labels, current)
