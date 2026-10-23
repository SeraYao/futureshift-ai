"""Deterministic four-week practice suggestions from available match gaps only."""
from src.i18n import localized_selectbox, career_name, tr, display_text, translated_options, translate_error
from copy import deepcopy
import hashlib
import json
from math import isfinite
from typing import Any
from pathlib import Path

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
    'skill_02': ('Break a fictional work problem into constraints, options and a justified solution.', 'A problem statement, options table and reasoned choice.'),
    'skill_05': ('Investigate a small environmental or scientific case and distinguish observations from claims.', 'A short evidence table with source and uncertainty notes.'),
    'skill_06': ('Map a fictional process, identify inputs, outputs, dependencies and one failure point.', 'A system map with an annotated dependency and risk.'),
    'skill_07': ('Compare two ways to allocate limited fictional time or resources using explicit criteria.', 'A small decision model, assumptions and recommendation.'),
    'skill_08': ('Sketch a low-fidelity design for a stated user need and test it against three constraints.', 'A design sketch and constraint checklist.'),
    'skill_09': ('Compare evidence for two choices and record uncertainty before selecting one.', 'A decision log with evidence, trade-offs and caveats.'),
    'skill_10': ('Write a concise evidence-based explanation for a non-specialist reader.', 'A revised short report with claims linked to evidence.'),
    'skill_11': ('Prepare and deliver a short explanation of a fictional analysis, then revise from feedback.', 'A timed outline, delivery notes and one revision.'),
    'knowledge_03': ('Explain the engineering principles behind a simple fictional environmental system.', 'A labelled system diagram and principle-to-effect explanation.'),
    'knowledge_04': ('Use a simple physics relationship to explain a fictional measurement or system.', 'A worked example with units and a reasonableness check.'),
    'knowledge_05': ('Describe a chemistry process using reactants, products and a simple material balance.', 'A balanced process sketch and assumptions.'),
    'knowledge_06': ('Summarize one biological system and explain how a changed condition may affect it.', 'A concept map with evidence and limits.'),
    'knowledge_07': ('Model a small fictional organizational decision, including resources and stakeholders.', 'A process/decision map with a short management note.'),
}
PHASES = ('Explore and establish a baseline', 'Practice and check',
          'Apply in a small example', 'Review and revise')
STAGE_INSTRUCTIONS = {
    1: 'Use the linked resource to identify key concepts, then make a baseline artifact for {area}.',
    2: 'Work through a small, fictional {area} case. Show the steps and check one assumption.',
    3: 'Apply {area} to a new, small scenario and explain why the approach fits its constraints.',
    4: 'Review your earlier {area} artifact, correct one weakness and record what still needs study.',
}

RESOURCE_FILE = Path(__file__).resolve().parent.parent / 'data/learning_resources.json'
_RESOURCE_DATA = json.loads(RESOURCE_FILE.read_text(encoding='utf-8'))
LEARNING_RESOURCES = {resource['id']: resource for resource in _RESOURCE_DATA['resources']}
RESOURCE_BY_SKILL = {
    'skill_01': 'mit-ocw-15-053', 'skill_02': 'mit-ocw-15-053',
    'skill_03': 'mit-ocw-15-053', 'skill_04': 'ms-learn-python-data',
    'skill_05': 'openlearn-climate-sustainability',
    'skill_07': 'mit-ocw-15-053', 'skill_09': 'mit-ocw-15-053',
    'skill_10': 'purdue-owl-writing',
    'knowledge_02': 'mit-ocw-15-053', 'knowledge_03': 'epa-water-learning',
    'knowledge_04': 'openstax-physics', 'knowledge_05': 'openstax-chemistry',
    'knowledge_06': 'openstax-biology', 'knowledge_07': 'mit-ocw-15-053',
}


def resource_for(skill_id: str, role_code: str | None = None) -> dict | None:
    """Return a copied source record for a stable questionnaire ID."""
    resource_id = resource_id_for(role_code or '', skill_id)
    return deepcopy(LEARNING_RESOURCES[resource_id]) if resource_id else None


def resource_id_for(role_code: str, skill_id: str) -> str | None:
    """Use a narrowly role-specific security resource where the broad item fits."""
    if role_code == '15-1212.00' and skill_id in ('skill_02', 'knowledge_01'):
        return 'ms-learn-cybersecurity-basics'
    environmental = {'13-1199.05', '17-2081.00', '17-2199.03'}
    engineering = {'17-2081.00', '17-2199.03', '17-2199.08'}
    if skill_id == 'skill_05' and role_code not in environmental:
        return None
    if skill_id == 'knowledge_03' and role_code not in {'13-1199.05', '17-2081.00'}:
        return None
    if skill_id == 'knowledge_04' and role_code not in engineering:
        return None
    if skill_id == 'knowledge_05' and role_code not in {'13-1199.05', '17-2081.00', '17-2199.03'}:
        return None
    return RESOURCE_BY_SKILL.get(skill_id)


def resources_for_plan(plan: dict) -> list[dict]:
    """Deduplicate resource references for readable exports and plan displays."""
    found = {task['resource_id'] for task in plan['tasks'] if task.get('resource_id')}
    return [deepcopy(LEARNING_RESOURCES[key]) for key in sorted(found)]


def build_legacy_plan(row: dict, role: dict, weekly_hours: int) -> dict:
    """Rebuild a saved practice-v1 plan for offline validation and progress migration."""
    old_practice = {
        'skill_01': ('Compare two explanations for a small fictional data result; identify assumptions and counterexamples.', 'An assumption checklist and a justified comparison.'),
        'skill_03': ('Solve small ratio, percentage and summary-statistic problems using invented numbers; show each step.', 'Worked calculations with checked answers.'),
        'skill_04': ('Write a small program that summarizes an invented numeric list; test empty and unusual inputs.', 'Source code, example inputs and test outputs.'),
        'knowledge_01': ('Sketch how input, processing, storage and output interact in a small computer-based workflow.', 'An annotated system sketch and an explanation of each component.'),
        'knowledge_02': ('Explain mean, spread and probability using a small invented numeric example; check your reasoning.', 'A concept note with worked examples and corrections.'),
    }
    candidates, excluded = [], []
    for group in ('skills', 'knowledge'):
        component = row[group]
        if component['score'].value is None or component['score'].issues:
            excluded.append(f'{group.title()}: unavailable component; ' + '; '.join(component['score'].issues))
            continue
        for gap in component['gaps']:
            item = role[group].get(gap['id'])
            if item is None or item.get('issues') or any(x.get('issues') for x in item.get('sources', {}).values()):
                if item is not None and (item.get('issues') or any(x.get('issues') for x in item.get('sources', {}).values())):
                    excluded.append(f"{gap['id']}: missing or quality-blocked requirement")
                continue
            if not gap.get('included'):
                continue
            if gap['gap'] <= 0:
                continue
            if gap['id'] not in old_practice:
                excluded.append(f"{gap['id']}: no authored practice template; not substituted")
                continue
            candidates.append({'group': group, **gap})
    candidates.sort(key=lambda gap: (-gap['gap'], gap['id']))
    selected = candidates[:max(1, weekly_hours // 2)]
    tasks = []
    for week, phase in enumerate(PHASES, 1):
        for index, gap in enumerate(selected):
            minutes = weekly_hours * 60 // len(selected) + int(index < weekly_hours * 60 % len(selected))
            action, evidence = old_practice[gap['id']]
            tasks.append({'id': f"{week}:{gap['group']}:{gap['id']}", 'week': week,
                          'area': gap['id'], 'group': gap['group'], 'minutes': minutes,
                          'phase': phase, 'action': action, 'practice_rounds': max(1, minutes // 30),
                          'evidence': evidence, 'gap': {key: gap[key] for key in ('id', 'user', 'required', 'importance', 'gap')}})
    payload = {'version': 'practice-v1', 'role_code': role['code'], 'weekly_hours': weekly_hours,
               'tasks': tasks, 'deferred': [gap['id'] for gap in candidates[len(selected):]], 'excluded': excluded}
    payload['id'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return payload


def build_plan(row: dict, role: dict, weekly_hours: int,
               preferred_language: str | None = None) -> dict:
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
            candidates.append({'group': group, 'resource_id': resource_id_for(role['code'], key), **gap})
    candidates.sort(key=lambda gap: (-gap['gap'], gap['id']))
    selected = candidates[:max(1, weekly_hours // 2)]
    tasks = []
    for week, phase in enumerate(PHASES, 1):
        for index, gap in enumerate(selected):
            minutes = weekly_hours * 60 // len(selected) + int(index < weekly_hours * 60 % len(selected))
            action, evidence = PRACTICE[gap['id']]
            stage_action = STAGE_INSTRUCTIONS[week].format(area=gap['id'])
            resource_minutes = min(minutes // 3, 60) if gap['resource_id'] else 0
            tasks.append({'id': f"{week}:{gap['group']}:{gap['id']}", 'week': week,
                          'area': gap['id'], 'group': gap['group'], 'minutes': minutes,
                          'resource_study_minutes': resource_minutes,
                          'project_minutes': minutes - resource_minutes,
                          'phase': phase, 'action': action, 'step': stage_action, 'step_id': week,
                          'practice_rounds': max(1, minutes // 30), 'evidence': evidence,
                          'resource_id': gap['resource_id'],
                          'gap': {key: gap[key] for key in ('id', 'user', 'required', 'importance', 'gap')}})
    payload = {'version': 'practice-v2', 'role_code': role['code'], 'weekly_hours': weekly_hours,
               'tasks': tasks, 'deferred': [gap['id'] for gap in candidates[len(selected):]],
               'unresourced': sorted({gap['id'] for gap in selected if not gap['resource_id']}),
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
    st.warning(tr('Official-derived questionnaire gaps; practice exercises are authored suggestions, not verified courses or qualification evidence.') if assessment and assessment['roles'].get('data_status') == 'official_derived' else tr('Prototype suggestion — no employment outcome is guaranteed. Occupational gaps here are synthetic.'))
    st.caption(tr('Learning resources are matched to stable skill IDs. Language describes the source material, not this interface. Completion does not raise match scores or prove skill mastery.'))
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
    st.caption(tr('Four-week plan covers selected gap practice, not complete occupational readiness. Weekly hours are a time budget, not a completion-time promise. Course duration is shown separately from this plan’s time allocation.'))
    row = next(row for row in rows if row['code'] == code)
    preferred_language = (assessment or {}).get('answers', {}).get('Preferred learning language', 'English')
    plan = build_plan(row, roles[code], hours, preferred_language)
    # Keep completion for unchanged task IDs when a saved v1 plan is upgraded to
    # the resource-aware plan. A different time budget still creates a fresh plan.
    if assessment is not None:
        old_entry = assessment.get('plans', {}).get(code)
        old_plan = old_entry.get('plan') if old_entry else None
        if old_plan and old_plan.get('weekly_hours') == hours:
            progress = st.session_state.setdefault('learning_progress', {})
            old_completion = old_entry.get('completion', progress.get(old_plan.get('id'), {}))
            matching_ids = {task['id'] for task in plan['tasks']}
            carried = {key: value for key, value in old_completion.items()
                       if key in matching_ids and value is True}
            if carried:
                progress.setdefault(plan['id'], {}).update(carried)
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
    st.caption(tr('Rule: exclude unavailable components and blocked items; order positive weighted gaps by severity then stable item ID. Focus on up to floor(weekly hours / 2) areas. Divide the weekly time budget between them; use four distinct stages: baseline, practice, application and review. These tasks do not change matching scores.'))
    if not plan['tasks']:
        st.info(tr('A plan cannot be generated: no usable positive skills or knowledge gaps with authored exercises. This may mean coverage meets this limited synthetic sample, or required data is unavailable. No additional tasks have been invented.'))
    for reason in plan['excluded']:
        st.caption(tr('Excluded: ') + translate_error(reason))
    if not plan['tasks']:
        return
    if plan['deferred']:
        st.caption(tr('Not covered within this budget: ') + ', '.join((display_text(labels.get(key, key)) for key in plan['deferred'])))
    if plan['unresourced']:
        st.info(tr('Some selected gaps have no suitable verified resource in this catalog. The authored practice task remains available; no course is implied.'))
    preferred_code = {'English': 'en', 'Bahasa Malaysia': 'ms', 'Chinese': 'zh'}.get(preferred_language, 'en')
    plan_resources = resources_for_plan(plan)
    if plan_resources and any(preferred_code not in item['teaching_languages'] for item in plan_resources):
        st.info(tr('No matched resources were verified in {language}; showing verified English resources as a fallback.', language=display_text(preferred_language)))
    for resource in plan_resources:
        with st.expander(tr('Learning resource · {name}', name=resource['name'])):
            st.markdown(f"[{resource['name']}]({resource['url']})")
            st.caption(tr('Provider: {provider} · Teaching language: {languages}', provider=resource['provider'], languages=', '.join(resource['teaching_languages'])))
            st.write(tr('Prerequisites: {text}', text=display_text(resource['prerequisites'])))
            st.write(tr('Cost: {text}', text=display_text(resource['cost'])))
            st.write(tr('Official duration: {text}', text=display_text(resource['duration_basis'])))
            st.caption(tr('Resource ID: {id} · Verified: {date} · Mapped skills: {skills}', id=resource['id'], date=resource['verified_on'], skills=', '.join(display_text(labels.get(key, key)) for key in resource['skill_ids'])))
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
                st.write(tr('Learn: {v0}', v0=display_text(task['action'])))
                if task.get('resource_id'):
                    resource = LEARNING_RESOURCES[task['resource_id']]
                    st.markdown(tr('Resource: [{name}]({url}) · {provider}', name=resource['name'], url=resource['url'], provider=resource['provider']))
                else:
                    st.caption(tr('No suitable verified resource is currently mapped to this skill; use the authored task and note this resource gap.'))
                st.write(tr('This week: {step}', step=tr(STAGE_INSTRUCTIONS[task['step_id']], area=display_text(labels.get(task['area'], task['area'])))))
                st.caption(tr('This week’s estimated allocation: {source} min source study + {practice} min project practice = {total} min from your weekly budget. These are project estimates, separate from the provider’s total course duration.', source=task['resource_study_minutes'], practice=task['project_minutes'], total=task['minutes']))
                st.write(tr('Action: {v0} Complete {v1} practice rounds. This week: {v2}; retain earlier evidence for comparison.', v0=display_text(task['action']), v1=task['practice_rounds'], v2=display_text(task['phase'])))
                st.write(tr('Completion evidence: ') + display_text(task['evidence']) + tr(' Keep a dated record of attempts, checks and revisions.'))
                gap = task['gap']
                st.caption(tr('Career gap · {v0}: your normalized level {v1:.2f}, requirement {v2:.2f}, importance {v3:.2f}, weighted gap {v4:.3f}.', v0=names[code], v1=gap['user'], v2=gap['required'], v3=gap['importance'], v4=gap['gap']))
                key = 'learning_check_' + plan['id'] + '_' + task['id']
                if key not in st.session_state:
                    st.session_state[key] = saved.get(task['id'], False)
                st.checkbox(tr('Completed · ') + display_text(labels.get(task['area'], task['area'])), key=key,
                            on_change=remember_task, args=(st.session_state, plan['id'], task['id'], key))
