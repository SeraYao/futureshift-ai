"""Deterministic four-week practice suggestions from available match gaps only."""
from src.i18n import localized_selectbox, career_name, tr, display_text, translated_options, translate_error
from copy import deepcopy
import hashlib
import json
from math import isfinite
from typing import Any

from src.reassessment import task_changes

# Authored practice prompts, not courses, verified resources or occupational evidence.
PRACTICE = {
    'skill_01': ('Compare two explanations for a small fictional data result; identify assumptions and counterexamples.',
                 'An assumption checklist and a justified comparison.'),
    'skill_03': ('Solve small ratio, percentage and summary-statistic problems using invented numbers; show each step.',
                 'Worked calculations with checked answers.'),
    'skill_04': ('Write a small program that summarizes an invented numeric list; test empty and unusual inputs.',
                 'Source code, example inputs and test outputs.'),
    'knowledge_01': ('Sketch how input, processing, storage and output interact in a small computer-based workflow.',
                     'An annotated system sketch and an explanation of each component.'),
    'knowledge_02': ('Explain mean, spread and probability using a small invented numeric example; check your reasoning.',
                     'A concept note with worked examples and corrections.'),
}
PHASES = ('Explore and establish a baseline', 'Practice and check',
          'Apply in a small example', 'Review and revise')


def build_plan(row: dict, role: dict, weekly_hours: int) -> dict:
    """Select positive, quality-usable gaps by severity and budget without changing scores."""
    if type(weekly_hours) is not int or weekly_hours not in (3, 5, 8, 10):
        raise ValueError('Weekly hours must be 3, 5, 8 or 10 (10+ capped at 10)')
    if row['code'] != role['code']:
        raise ValueError('Match and occupation must refer to the same role')
    candidates, excluded = [], []
    for group in ('skills', 'knowledge'):
        component = row[group]
        if component['score'].value is None or component['score'].issues:
            excluded.append(f'{group.title()}: unavailable component; ' + '; '.join(component['score'].issues))
            continue
        for gap in component['gaps']:
            key = gap['id']
            requirement = role[group].get(key)
            if requirement is None or requirement.get('issues') or any(
                    rating.get('issues') for rating in requirement.get('sources', {}).values()):
                excluded.append(f'{key}: missing or quality-blocked requirement')
                continue
            if not gap.get('included') or any(
                    not isinstance(gap.get(field), (float, int)) or isinstance(gap.get(field), bool)
                    or not isfinite(gap[field]) for field in ('gap', 'user', 'required', 'importance')):
                excluded.append(f'{key}: gap is not computable')
                continue
            if gap['gap'] <= 0:
                continue
            if key not in PRACTICE:
                excluded.append(f'{key}: no authored practice template; not substituted')
                continue
            candidates.append({'group': group, **gap})
    candidates.sort(key=lambda gap: (-gap['gap'], gap['id']))
    selected = candidates[:max(1, weekly_hours // 2)]
    tasks = []
    for week, phase in enumerate(PHASES, 1):
        for index, gap in enumerate(selected):
            minutes = weekly_hours * 60 // len(selected) + int(index < weekly_hours * 60 % len(selected))
            action, evidence = PRACTICE[gap['id']]
            tasks.append({'id': f"{week}:{gap['group']}:{gap['id']}", 'week': week,
                          'area': gap['id'], 'group': gap['group'], 'minutes': minutes,
                          'phase': phase, 'action': action,
                          'practice_rounds': max(1, minutes // 30), 'evidence': evidence,
                          'gap': {key: gap[key] for key in ('id', 'user', 'required', 'importance', 'gap')}})
    payload = {'version': 'practice-v1', 'role_code': role['code'], 'weekly_hours': weekly_hours,
               'tasks': tasks, 'deferred': [gap['id'] for gap in candidates[len(selected):]],
               'excluded': excluded}
    payload['id'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return payload


def remember_task(state: Any, plan_id: str, task_id: str, widget_key: str) -> None:
    """Keep progress outside widget state so navigation does not erase it within a session."""
    state['learning_progress'].setdefault(plan_id, {})[task_id] = state[widget_key]


def render_learning_plan(st: Any, rows: list[dict], roles: dict, labels: dict,
                         preferred_time: str | None = None, assessment: dict | None = None,
                         previous: dict | None = None) -> None:
    """Offer occupation selection, a budgeted plan and session-only completion checks."""
    st.subheader(tr('Your four-week practice plan'))
    st.warning(tr('Prototype suggestion — no employment outcome is guaranteed. Occupational gaps here are synthetic.'))
    st.info(tr('Verified learning resources are not connected yet. These are authored practice exercises, not course recommendations. Completion does not change your matching scores or prove skill mastery.'))
    codes = [row['code'] for row in rows]
    if assessment is not None and 'learning_role' not in st.session_state:
        st.session_state['learning_role'] = assessment.get('selected_role')
    names = {code: career_name(code, roles[code]['title']) for code in codes}
    code = localized_selectbox(st, tr('Choose a career to plan for'), codes, index=None,
                        placeholder=tr('Choose a career'),
                        format_func=translated_options(lambda value: names[value]), key='learning_role')
    if code is None:
        st.caption(tr('Select one of your match results to build a plan.'))
        return
    options = (3, 5, 8, 10)
    initial = {'3 hours': 3, '5 hours': 5, '8 hours': 8, '10+ hours': 10}.get(preferred_time, 3)
    if assessment is not None and 'learning_hours' not in st.session_state:
        st.session_state['learning_hours'] = assessment.get('selected_hours') or initial
    hours = localized_selectbox(st, tr('Weekly practice time'), options, index=options.index(initial),
                         format_func=translated_options(lambda value: '10+ hours (planned as 10)' if value == 10 else f'{value} hours'),
                         key='learning_hours')
    st.caption(tr('Four weeks only. Budget, language and SDG resource filtering are not implemented. Time estimates are scheduling assumptions, not measured completion times.'))
    row = next(row for row in rows if row['code'] == code)
    plan = build_plan(row, roles[code], hours)
    if assessment is not None:
        assessment['selected_role'] = code
        assessment['selected_hours'] = hours
        assessment['plans'][code] = deepcopy({'plan': plan, 'completion':
            st.session_state.get('learning_progress', {}).get(plan['id'], {})})
    old_plan = previous.get('plans', {}).get(code) if previous else None
    if old_plan is not None:
        changes = task_changes(old_plan['plan'], plan)
        st.markdown(tr('#### Plan changes since the previous assessment'))
        st.caption(tr('Weekly hours: {v0} → {v1}. Adjusted means the gap, time allocation or exercise prescription changed. New plan progress is separate; completing tasks does not prove ability improvement.', v0=old_plan['plan']['weekly_hours'], v1=hours))
        for kind, tasks in changes.items():
            st.write(tr('{v0}: {v1} tasks', v0=display_text(kind.title()), v1=len(tasks)))
            for task in tasks:
                st.caption(tr('Week {v0} · {v1}', v0=task['week'], v1=display_text(labels.get(task['area'], task['area']))))
        if not any(changes.values()):
            st.info(tr('Plan tasks unchanged.'))
    elif previous is not None:
        st.caption(tr('No previous plan was selected for this occupation; this is its first plan snapshot.'))
    st.caption(tr('Rule: exclude unavailable components and blocked items; order positive weighted gaps by severity then stable item ID. Focus on up to floor(weekly hours / 2) areas. Divide each week equally between them; progress from exploration to practice, application and review. Each practice round is a suggested 30-minute block; use remaining time to record evidence.'))
    if not plan['tasks']:
        st.info(tr('A plan cannot be generated: no usable positive skills or knowledge gaps with authored exercises. This may mean coverage meets this limited synthetic sample, or required data is unavailable. No additional tasks have been invented.'))
    for reason in plan['excluded']:
        st.caption(tr('Excluded: ') + translate_error(reason))
    if not plan['tasks']:
        return
    if plan['deferred']:
        st.caption(tr('Not covered within this budget: ') + ', '.join((display_text(labels.get(key, key)) for key in plan['deferred'])))
    st.caption(tr('Progress is held only in this Streamlit session. Refreshing or closing the page may lose it; download your plan to keep a local copy and restore it later. There is no cloud storage. A changed gap or time budget creates a separate plan.'))
    st.session_state.setdefault('learning_progress', {})
    saved = st.session_state.learning_progress.setdefault(plan['id'], {})
    completed = sum(bool(saved.get(task['id'])) for task in plan['tasks'])
    st.progress(completed / len(plan['tasks']), text=tr('{v0} / {v1} tasks completed', v0=completed, v1=len(plan['tasks'])))
    if assessment is not None:
        from src.plan_transfer import export_plan, readable_plan
        st.download_button(tr('Download my plan'), data=export_plan(assessment, plan, saved),
                           file_name='futureshift-plan.json', mime='application/json', key='download_my_plan')
        st.caption(tr('The file contains scored answers, this plan and task progress. It excludes your name, contact details, free-text goal and GitHub responses. Keep it locally; download again after progress changes.'))
        st.download_button(tr('Download readable plan'), data=readable_plan(assessment, plan, saved, labels),
                           file_name=f"futureshift-plan-{st.session_state.get('ui_language', 'en')}.md",
                           mime='text/markdown', key='download_readable_plan')
        st.caption(tr('The readable plan uses your interface language. JSON keeps stable IDs and original text for validated restore. Neither download changes your profile or progress.'))
    for week, phase in enumerate(PHASES, 1):
        with st.expander(tr('Week {v0} · {v1}', v0=week, v1=display_text(phase)), expanded=week == 1):
            for task in (task for task in plan['tasks'] if task['week'] == week):
                st.markdown(tr('**{v0} · {v1} · {v2} minutes**', v0=display_text(labels.get(task['area'], task['area'])), v1=display_text(task['group']), v2=task['minutes']))
                st.write(tr('Action: {v0} Complete {v1} practice rounds. This week: {v2}; retain earlier evidence for comparison.', v0=display_text(task['action']), v1=task['practice_rounds'], v2=display_text(task['phase'])))
                st.write(tr('Completion evidence: ') + display_text(task['evidence']) + tr(' Keep a dated record of attempts, checks and revisions.'))
                gap = task['gap']
                st.caption(tr('Career gap · {v0}: your normalized level {v1:.2f}, synthetic requirement {v2:.2f}, importance {v3:.2f}, weighted gap {v4:.3f}.', v0=names[code], v1=gap['user'], v2=gap['required'], v3=gap['importance'], v4=gap['gap']))
                key = 'learning_check_' + plan['id'] + '_' + task['id']
                if key not in st.session_state:
                    st.session_state[key] = saved.get(task['id'], False)
                st.checkbox(tr('Completed · ') + display_text(labels.get(task['area'], task['area'])), key=key,
                            on_change=remember_task, args=(st.session_state, plan['id'], task['id'], key))
