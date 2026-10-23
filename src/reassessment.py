"""Session snapshots and deterministic before/after explanations; no score calculation."""
from src.i18n import career_name, tr, display_text, table_text, translate_error, translated_options
from copy import deepcopy
from typing import Any


def store_assessment(state: Any, profile: dict, answers: dict, rows: list[dict],
                     roles: dict, trends: dict) -> dict:
    """Freeze the last confirmed run before replacing it with a new result snapshot."""
    current = state.get('pathway_assessment')
    if current is not None:
        state['pathway_previous'] = deepcopy(current)
    snapshot = deepcopy({'profile': profile, 'answers': answers, 'rows': rows,
                         'roles': roles, 'trends': trends, 'plans': {},
                         'selected_role': current.get('selected_role') if current else None,
                         'selected_hours': current.get('selected_hours') if current else None})
    if current and current['answers'].get('Weekly learning time') != answers.get('Weekly learning time'):
        snapshot['selected_hours'] = None
    state['pathway_assessment'] = snapshot
    return snapshot


def begin_reassessment(state: Any) -> None:
    """Prefill the last confirmed answers while retaining the frozen result and plans."""
    current = state['pathway_assessment']
    state['pathway_draft'] = deepcopy(current['answers'])
    for name in current['answers']:
        state.pop('pathway_' + name, None)
    state.pop('pathway_confirmed', None)
    state['pathway_step'] = 1


def changed_answers(before: dict, after: dict) -> list[dict]:
    """Return stable raw answer changes; absent values stay absent, never become zero."""
    return [{'field': key, 'before': before.get(key), 'after': after.get(key)}
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def compare_results(before: list[dict], after: list[dict]) -> list[dict]:
    """Compare every occupation, preserving unavailable values and exact numeric deltas."""
    old = {row['code']: row for row in before}
    comparisons = []
    for row in after:
        previous = old[row['code']]
        measures = {}
        for name, a, b in [
            ('Skills coverage', previous['skills']['score'].value, row['skills']['score'].value),
            ('Knowledge coverage', previous['knowledge']['score'].value, row['knowledge']['score'].value),
            ('Capability', previous['S_capability'].value, row['S_capability'].value),
            ('Interest similarity', previous['I'].value, row['I'].value),
            ('Personal fit', previous['P'].value, row['P'].value),
            ('Trend signal', previous['trend']['score'].value, row['trend']['score'].value),
            *[(scenario.title() + ' ' + kind, previous[scenario + '_rank'] if kind == 'rank'
               else previous[scenario].value, row[scenario + '_rank'] if kind == 'rank'
               else row[scenario].value) for scenario in ('moderate', 'fast') for kind in ('rank', 'score')],
        ]:
            measures[name] = {'before': a, 'after': b, 'delta': None if a is None or b is None else b-a,
                              'status': 'Unavailable' if a is None or b is None else 'Unchanged' if a == b else 'Changed'}
        comparisons.append({'code': row['code'], 'title': row['title'], 'measures': measures})
    return comparisons


def task_changes(before: dict, after: dict) -> dict[str, list[dict]]:
    """Compare task identities and full prescriptions, including gap and time adjustments."""
    old = {task['id']: task for task in before['tasks']}
    new = {task['id']: task for task in after['tasks']}
    return {'added': [new[key] for key in sorted(new.keys() - old.keys())],
            'removed': [old[key] for key in sorted(old.keys() - new.keys())],
            'adjusted': [new[key] for key in sorted(old.keys() & new.keys()) if old[key] != new[key]]}


def render_comparison(st: Any, previous: dict | None, current: dict, labels: dict) -> None:
    """Explain answer changes and all score components without model-generated claims."""
    if previous is None:
        st.info(tr('First assessment: no previous result to compare yet.'))
        return
    st.subheader(tr('What changed since your last assessment?'))
    st.caption(tr('Prototype simulation. Changes are new minus previous; a negative rank difference means moving higher. Unavailable scores remain unavailable, never zero. Trend inputs are fixed synthetic snapshots, not evidence of labour-market change.'))
    changes = changed_answers(previous['answers'], current['answers'])
    if not changes:
        st.info(tr('No questionnaire answers changed. Identical inputs and snapshots produce identical results.'))
    for change in changes:
        key = change['field']
        if key.startswith('skill_'):
            effect = 'Skills coverage → capability → personal fit; coverage is capped, so a change may have no score effect.'
        elif key.startswith('knowledge_'):
            effect = 'Knowledge coverage → capability → personal fit; coverage is capped.'
        elif key in ('R1', 'R2', 'I1', 'I2', 'A1', 'A2', 'S1', 'S2', 'E1', 'E2', 'C1', 'C2'):
            effect = 'RIASEC dimension → interest similarity → personal fit.'
        else:
            effect = 'Not scored. Weekly learning time may change the plan; other preferences remain contextual.'
        def answer(value):
            if key == 'Optional career goal':
                return value
            if isinstance(value, list):
                return ', '.join(translated_options()(item) for item in value)
            return translated_options()(value) if isinstance(value, str) else value
        st.write(tr('{v0}: {v1} → {v2}. {v3}', v0=display_text(labels.get(key, key)), v1=answer(change['before']), v2=answer(change['after']), v3=display_text(effect)))
    for result in compare_results(previous['rows'], current['rows']):
        with st.expander(career_name(result['code'], result['title']) + tr(' · Before / after')):
            role = next(role for role in current['roles']['roles'] if role['code'] == result['code'])
            used = [display_text(labels.get(change['field'], change['field'])) for change in changes
                    if change['field'] in role['skills'] or change['field'] in role['knowledge']]
            st.caption(tr('Changed ability inputs used by this role: ') + (', '.join(used) or tr('None')) + tr('. All six interest dimensions are used. Other ability answers have no requirement in this fixture.'))
            st.table(table_text([{'Measure': name, 'Previous': item['before'] if item['before'] is not None else 'Unavailable',
                       'Current': item['after'] if item['after'] is not None else 'Unavailable',
                       'Change': item['delta'] if item['delta'] is not None else 'Unavailable',
                       'Status': item['status']} for name, item in result['measures'].items()]))
