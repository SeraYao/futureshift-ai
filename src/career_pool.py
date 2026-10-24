"""Quality-gated official careers; one scoring engine and separate evidence cohorts."""
from copy import deepcopy
from src.scoring import rank_roles
from src.i18n import tr, career_name, table_text, display_text, localized_selectbox, translated_options
from src.official_labor_evidence import (
    BLS_TABLE_URL, CAREERS as LABOR_CAREERS, exact_comparison, load_snapshot, refresh_snapshot,
)
from src.sdg import render_sdg_result_card

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
            # Keep canonical source labels in assessment state; translate only when rendered.
            'omitted': [source[g][key]['name'] for g in ('skills', 'knowledge')
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
        st.session_state['archived_demo_assessment'] = deepcopy(current)
        if 'learning_progress' in st.session_state:
            st.session_state['archived_demo_progress'] = deepcopy(st.session_state['learning_progress'])
        st.session_state.pop('pathway_assessment', None)
        st.session_state.pop('pathway_previous', None)
        for key in list(st.session_state):
            if key.startswith('learning_'):
                del st.session_state[key]
        st.session_state['demo_state_archived_notice'] = True
        current = None
    if st.session_state.pop('demo_state_archived_notice', False):
        st.info(tr('A previous in-pathway demo result was archived. The official workflow now uses only the official career catalog.'))
    if current is None or current['profile'] != profile or current['answers'] != draft:
        current = store_assessment(st.session_state, profile, draft, rows, dataset, {'topics': {}})
    st.caption(tr('Official O*NET 31.0 requirements. Cross-domain order uses personal fit only: 70% capability + 30% interest; capability is 75% skills + 25% knowledge.'))
    st.caption(tr('The fixed local recommendation pool contains six quality-eligible occupations from the bundled O*NET 31.0 snapshot. It is not the full job market and does not crawl for new careers.'))
    st.warning(tr('Limited questionnaire coverage: 11 skills, 7 knowledge areas and RIASEC. Unasked abilities, credentials, experience requirements and other knowledge are not scored or treated as zero. These are exploration suggestions, not qualification assessments.'))
    st.caption(tr('Official expert knowledge ratings may omit optional precision statistics. Blank flags are preserved as unavailable precision, never relabelled as N; explicit suppression and relevance blocks remain enforced.'))
    st.warning(tr('Some official matches use partial questionnaire coverage. Coverage is shown per career; scores with different omitted dimensions are exploratory and not fully comparable. Not Relevant areas are excluded from that career denominator, never treated as zero.'))
    coverage_rows = []
    for row in eligible:
        omitted = row['assessment_coverage']['omitted']
        omitted_note = (' · ' + tr('Excluded from coverage: {v0}',
                                   v0=', '.join(display_text(key) for key in omitted))
                        if omitted else '')
        coverage_rows.append({
            'Career': career_name(row['code'], row['title']),
            'Questionnaire coverage': tr('{v0} skills · {v1} knowledge · {v2} interests{v3}',
                                         v0=row['assessment_coverage']['skills'],
                                         v1=row['assessment_coverage']['knowledge'],
                                         v2=row['assessment_coverage']['interests'], v3=omitted_note),
            'Personal fit': row['P'].value, 'Rank': row['personal_rank'],
        })
    st.table(table_text(coverage_rows))
    for row in eligible:
        render_sdg_result_card(st, row['code'], row['title'])
    render_official_labor_evidence(st, eligible, dataset)
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

    from src.sdg import render_local_sdg
    render_local_sdg(st, eligible, roles, labels, current)


def render_official_labor_evidence(st, rows, dataset):
    """Display one exact-match BLS Result and a folded weight-sensitivity check."""
    st.subheader(tr('U.S. employment projections'))
    st.caption(tr('Career directory, profile matching, BLS evidence and SDG links'))
    st.caption(tr('This evidence does not track AI capability progress. AI exposure is separate from replacement risk and is not included in these calculations.'))
    if st.button(tr('Refresh official employment evidence'), key='refresh_official_employment_evidence'):
        try:
            with st.spinner(tr('Fetching and validating official sources…')):
                refresh_snapshot()
            st.session_state.pop('labor_evidence_refresh_error', None)
        except Exception as exc:
            # Keep the last verified on-disk snapshot and show only a safe error class.
            status = getattr(exc, 'code', None)
            st.session_state['labor_evidence_refresh_error'] = f'HTTP {status}' if status else type(exc).__name__
    if st.session_state.get('labor_evidence_refresh_error'):
        st.warning(tr('Refresh failed ({v0}); the previous valid snapshot is still shown.',
                      v0=st.session_state['labor_evidence_refresh_error']))
    try:
        snapshot = load_snapshot()
    except (OSError, ValueError, TypeError, KeyError):
        st.warning(tr('No valid employment evidence snapshot is available. Personal-fit results and plans are unchanged.'))
        return
    if snapshot.get('data_status') == 'controlled_test_fixture':
        st.warning(tr('Controlled test data: not an official BLS snapshot.'))

    st.caption(tr('BLS release: {v0} · Projection period: {v1} · Region: {v2} · Snapshot retrieved: {v3}',
                  v0=snapshot['release_date'], v1=snapshot['period'], v2=snapshot['geography'],
                  v3=snapshot['retrieved_at']))
    st.markdown(tr('[BLS occupational projections](https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm) · [O*NET-SOC 2019 to 2018 SOC crosswalk](https://www.onetcenter.org/taxonomy/2019/soc.html)'))
    comparison = exact_comparison(rows, snapshot)
    titles = {role['code']: role['title'] for role in dataset['roles']}
    table = []
    for item in comparison:
        result = item['result']
        table.append({
            'Career': career_name(item['code'], titles[item['code']]),
            'Personal fit P (0–100)': round(item['personal_fit'], 2),
            'BLS projected employment change (%)': item['projection_percent'],
            'Normalized BLS evidence (0–100)': round(item['normalized_projection'], 2),
            'Personal contribution (80%)': round(result['personal_contribution'], 2),
            'BLS contribution (20%)': round(result['projection_contribution'], 2),
            'Result': round(result['combined'], 2),
            'Result rank': result['rank'],
        })
    st.markdown('#### ' + tr('Result'))
    st.caption(tr('Result formula: 80% × personal fit + 20% × normalized BLS employment-projection evidence. The 20% weight is an unvalidated product assumption, not an empirically calibrated weight or a probability. This three-career cohort is not mixed with the other careers, which retain personal-fit rankings only.'))
    st.table(table_text(table))
    st.caption(tr('Normalization: 100 × (x − minimum) ÷ (maximum − minimum), calculated only across these three exact SOC matches. If all values tie, each normalized value is 50. Contributions shown above are 80% × P and 20% × normalized BLS evidence.'))

    with st.expander(tr('Assumption variation test')):
        st.caption(tr('This test raises the external-evidence weight to 40% (60% personal fit / 40% normalized BLS evidence) to check ranking sensitivity. It is not a second future scenario or forecast, and it does not replace the Result above.'))
        result_ranks = {item['code']: item['result']['rank'] for item in comparison}
        sensitivity_ranks = {item['code']: item['sensitivity']['rank'] for item in comparison}
        if result_ranks == sensitivity_ranks:
            st.info(tr('Rankings are stable within the current assumption range.'))
        else:
            st.caption(tr('A positive rank movement means the career moved up under the 40% sensitivity test.'))
            sensitivity_rows = []
            for item in comparison:
                sensitivity_rows.append({
                    'Career': career_name(item['code'], titles[item['code']]),
                    'Result rank (20%)': item['result']['rank'],
                    'Rank at 40% evidence weight': item['sensitivity']['rank'],
                    'Rank movement': item['sensitivity']['rank_change'],
                })
            st.table(table_text(sensitivity_rows))

    aggregate_codes = [code for code, career in LABOR_CAREERS.items() if career['mapping'] != 'exact']
    st.info(tr('Career-level BLS evidence is unavailable for: {careers}. Any aggregate rows below are context only and do not enter the comparison.',
               careers=', '.join(career_name(code, LABOR_CAREERS[code]['title']) for code in aggregate_codes)))

    for item in comparison:
        entry = snapshot['careers'][item['code']]
        projection = entry['projection']
        with st.expander(career_name(item['code'], titles[item['code']]) + ' · ' + tr('BLS source evidence')):
            st.write(tr('BLS occupation row: {title} ({code})',
                        title=projection['title'], code=projection['soc_code']))
            st.write(tr('Employment in {year}: {value} thousand',
                        year=snapshot['base_year'], value=projection['employment_start_thousands']))
            st.write(tr('Employment projected in {year}: {value} thousand',
                        year=snapshot['target_year'], value=projection['employment_target_thousands']))
            st.write(tr('Projected employment change: {value}%',
                        value=projection['employment_change_percent']))
            st.write(tr('Annual openings, {period}: {value} thousand',
                        period=snapshot['period'], value=projection['annual_openings_thousands']))
            st.markdown(f"[BLS source]({BLS_TABLE_URL}) · [O*NET-SOC crosswalk]({snapshot['crosswalk']['source_url']})")

    for code, career in LABOR_CAREERS.items():
        if career['mapping'] == 'exact':
            continue
        entry = snapshot['careers'][code]
        projection = entry['projection']
        with st.expander(tr('Aggregate reference only: {career}', career=career_name(code, career['title']))):
            st.warning(tr('This SOC row covers a broader “All Other” occupation group. It is not a career-level estimate and is excluded from the sensitivity calculation.'))
            st.write(tr('Mapped SOC: {code} · {title}', code=entry['soc_code'], title=entry['soc_title']))
            st.write(tr('BLS projected employment change, {period}: {value}%',
                        period=snapshot['period'], value=projection['employment_change_percent']))
            st.markdown(f"[BLS source]({BLS_TABLE_URL}) · [O*NET-SOC crosswalk]({snapshot['crosswalk']['source_url']})")

    st.markdown('#### ' + tr('Choose from this Result'))
    codes = [item['code'] for item in comparison]
    selected = localized_selectbox(
        st, tr('Career from the comparison'), codes,
        index=codes.index(st.session_state.get('learning_role'))
        if st.session_state.get('learning_role') in codes else 0,
        format_func=translated_options(lambda code: career_name(code, titles[code])),
        key='labor_scenario_career')
    if st.button(tr('Use selected career in my learning plan'), key='use_labor_scenario_career'):
        # The existing plan widget consumes this canonical role ID on the rerun.
        st.session_state['learning_role'] = selected
        st.rerun()
