"""Versioned local plan transfer: allowlisted export and validate-before-confirm restore."""
from src.i18n import career_name, tr, display_text, display_value, table_text, translate_error
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from src.scoring import SCORING_VERSION, rank_roles

VERSION = 'futureshift-plan-v1'
NOTICE = ('Prototype plan. Synthetic occupational requirements and trend signals are not employment predictions. '
          'Practice completion does not prove skill mastery or guarantee employment.')
OFFICIAL_NOTICE = 'Official-derived plan. Limited questionnaire coverage, no labour-demand prediction. Practice completion does not prove qualification or guarantee employment.'
MAX_BYTES = 256_000


def source_fingerprint(roles: dict, trends: dict) -> str:
    """Identify local synthetic fixtures without exporting their data or API caches."""
    return hashlib.sha256(json.dumps([roles, trends], sort_keys=True).encode()).hexdigest()


def assessment_summary(rows: list[dict]) -> list[dict]:
    """Keep only the last confirmed scenario ranks/scores and essential component values."""
    return [{'code': row['code'], 'moderate_rank': row['moderate_rank'], 'fast_rank': row['fast_rank'],
             **{key: row[key].value for key in ('moderate', 'fast', 'P', 'S_capability')},
             'T': row['trend']['score'].value} for row in rows]


def export_plan(assessment: dict, plan: dict, completion: dict,
                exported_at: str | None = None) -> str:
    """Export scored answers and a reproducible plan, excluding open text and raw evidence."""
    from src.pathway import SKILLS, KNOWLEDGE, INTERESTS, confirmed_profile
    keys = (*SKILLS, *KNOWLEDGE, *(key for key, _ in INTERESTS))
    answers = {key: assessment['answers'][key] for key in keys}
    if assessment['profile']['data_status'] == 'synthetic':
        answers['data_status'] = 'synthetic'
    role = next(role for role in assessment['roles']['roles'] if role['code'] == plan['role_code'])
    document = {'format_version': VERSION, 'exported_at': exported_at or datetime.now(timezone.utc).isoformat(),
                'notice': OFFICIAL_NOTICE if role.get('data_status') == 'official_derived' else NOTICE, 'profile': confirmed_profile(answers), 'answers': answers,
                'career': {'code': role['code'], 'title': role['title']}, 'duration_weeks': 4,
                'weekly_hours': plan['weekly_hours'], 'plan': deepcopy(plan),
                'completion': {task['id']: bool(completion.get(task['id'], False)) for task in plan['tasks']},
                'last_assessment': {'scoring_version': SCORING_VERSION,
                    'source_fingerprint': source_fingerprint(assessment['roles'], assessment['trends']),
                    'data_status': 'official_requirements_personal_fit' if role.get('data_status') == 'official_derived' else 'synthetic_requirements_and_trends',
                    'results': assessment_summary(assessment['rows'])}}
    return json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)


def readable_plan(assessment: dict, plan: dict, completion: dict, labels: dict) -> str:
    """Localized, human-readable companion; portable JSON and all IDs stay unchanged."""
    role = next(role for role in assessment['roles']['roles'] if role['code'] == plan['role_code'])
    lines = ['# ' + tr('Readable learning plan'), '',
             '## ' + career_name(role['code'], role['title']),
             tr('Official source title: {title}', title=role['title']),
             tr('Career ID: {code} · Plan ID: {plan}', code=role['code'], plan=plan['id']),
             role['identity_source_url'], '', tr(OFFICIAL_NOTICE if role.get('data_status') == 'official_derived' else NOTICE),
             tr('Four weeks · {hours} hours per week', hours=plan['weekly_hours']), '',
             tr('Verified learning resources are not connected yet. These are authored practice exercises, not course recommendations. Completion does not change your matching scores or prove skill mastery.'), '',
             tr('Moderate = 85% personal fit + 15% trend; Fast = 65% personal fit + 35% trend. These are unvalidated sensitivity assumptions, not probabilities or employment forecasts.')]
    source = assessment.get('recommendation_source', 'Official cross-domain careers' if role.get('data_status') == 'official_derived' else 'Synthetic demo')
    lines += ['', tr('Ranking basis: {source}', source=display_text(source))]
    row = next(row for row in assessment.get('recommendation_rows', assessment['rows']) if row['code'] == role['code'])
    for name, score in (('Personal fit', row['P']), ('Trend signal', row['trend']['score']),
                        ('Moderate score', row['moderate']), ('Fast score', row['fast'])):
        lines.append(f"- {display_text(name)}: {score.value:.2f}" if score.value is not None else
                     f"- {display_text(name)}: {display_value('Unavailable')}")
    snapshot = assessment.get('recommendation_snapshots', {}).get(role['code'])
    if snapshot:
        lines.append(tr('Fetched (UTC): {date}', date=snapshot['fetched_at']))
        lines.append(tr('Saved snapshot, not a live observation. Repository counts are technical activity, not hiring demand.'))
        for topic, record in snapshot['topics'].items():
            for window in ('recent', 'previous'):
                lines.append(record['results'][window]['source_url'])
    for week in range(1, 5):
        tasks = [task for task in plan['tasks'] if task['week'] == week]
        if not tasks:
            continue
        lines += ['', '## ' + tr('Week {v0} · {v1}', v0=week, v1=display_text(tasks[0]['phase']))]
        for task in tasks:
            checked = 'x' if completion.get(task['id']) else ' '
            lines += [f"- [{checked}] " + tr('**{v0} · {v1} · {v2} minutes**',
                        v0=display_text(labels[task['area']]), v1=display_text(task['group']), v2=task['minutes']),
                      tr('Task ID: {task} · Area ID: {area}', task=task['id'], area=task['area']),
                      tr('Action: {v0} Complete {v1} practice rounds. This week: {v2}; retain earlier evidence for comparison.',
                         v0=display_text(task['action']), v1=task['practice_rounds'], v2=display_text(task['phase'])),
                      tr('Completion evidence: ') + display_text(task['evidence'])]
    return '\n\n'.join(lines) + '\n'


def _same_types_and_values(actual: Any, expected: Any) -> bool:
    """Reject extra fields and bool-as-integer tricks as well as altered task contents."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_same_types_and_values(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_same_types_and_values(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _unique_fields(pairs: list[tuple]) -> dict:
    """Reject ambiguous duplicate JSON fields before checking the schema."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def validate_saved_plan(raw: bytes, load_demo: Callable) -> dict:
    """Validate everything offline and rebuild scores/tasks before changing any session state."""
    from src.pathway import confirmed_profile
    from src.learning_plan import build_plan
    try:
        if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
            raise ValueError('Expected a JSON file no larger than 256 KB')
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_fields)
        if not isinstance(document, dict) or document.get('format_version') != VERSION:
            raise ValueError('Unsupported plan format version')
        timestamp = document['exported_at']
        if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp).tzinfo is None:
            raise ValueError('Export time must include a timezone')
        if not isinstance(document['answers'], dict):
            raise ValueError('Scored answers must be a JSON object')
        profile = confirmed_profile(document['answers'])
        if document.get('last_assessment', {}).get('data_status') == 'official_requirements_personal_fit':
            roles = json.loads((Path(__file__).resolve().parent.parent / 'data/onet_roles.json').read_text())
            trends = {'topics': {}}
        else:
            _, roles, trends = load_demo()
        code = document['career']['code']
        role = next((role for role in roles['roles'] if role['code'] == code), None)
        if role is None:
            raise ValueError('Occupation is not in the current prototype catalog')
        if roles.get('data_status') == 'official_derived':
            from src.career_pool import official_ranking
            rows = official_ranking(profile, roles)
        else:
            rows = rank_roles(profile, roles['roles'], trends['topics'])
        row = next(row for row in rows if row['code'] == code)
        plan = build_plan(row, role, document['weekly_hours'])
        if not plan['tasks']:
            raise ValueError('This profile has no usable plan tasks')
        completion = document['completion']
        if not isinstance(completion, dict) or any(type(v) is not bool for v in completion.values()):
            raise ValueError('Task completion states must be boolean')
        assessment = {'profile': profile, 'answers': document['answers'], 'roles': roles, 'trends': trends, 'rows': rows}
        expected = json.loads(export_plan(assessment, plan, completion, timestamp))
        if not _same_types_and_values(document, expected):
            raise ValueError('Missing, unexpected or invalid fields, or incompatible scoring/data/plan version')
        return deepcopy({'document': document, 'assessment': assessment, 'plan': plan, 'completion': completion})
    except (KeyError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError('Invalid plan file: missing required fields or incorrect field types') from exc


def restore_saved_plan(state: Any, prepared: dict) -> None:
    """Apply an already validated transfer only after the user explicitly confirms."""
    from src.reassessment import store_assessment
    assessment = deepcopy(prepared['assessment'])
    plan = deepcopy(prepared['plan'])
    # Retain any existing personal workspace for an explicit return to the intake.
    from src.pathway import switch_profile_workspace
    switch_profile_workspace(state, 'manual')
    state['saved_before_restore'] = deepcopy({key: state[key] for key in state
                                             if key.startswith(('pathway_', 'learning_'))})
    for key in list(state):
        if key.startswith(('pathway_', 'learning_')):
            del state[key]
    answers = deepcopy(assessment['answers'])
    answers['Weekly learning time'] = f"{plan['weekly_hours']} hours" if plan['weekly_hours'] != 10 else '10+ hours'
    current = store_assessment(state, assessment['profile'], answers, assessment['rows'],
                               assessment['roles'], assessment['trends'])
    current.update(selected_role=plan['role_code'], selected_hours=plan['weekly_hours'])
    current['plans'][plan['role_code']] = {'plan': plan, 'completion': deepcopy(prepared['completion'])}
    state['pathway_draft'] = answers
    state['pathway_confirmed'] = deepcopy(assessment['profile'])
    state['career_catalog_mode'] = 'Official cross-domain careers' if assessment['roles'].get('data_status') == 'official_derived' else 'Synthetic demo'
    state['pathway_step'] = 7
    state['learning_role'] = plan['role_code']
    state['learning_hours'] = plan['weekly_hours']
    state['learning_progress'] = {plan['id']: deepcopy(prepared['completion'])}
    state['pathway_restored'] = True


def render_restore(st: Any, load_demo: Callable, labels: dict | None = None, *, expanded: bool = False) -> None:
    """Validate an upload, show a readable preview, then ask for restore confirmation."""
    with st.expander(tr('Restore a saved plan'), expanded=expanded):
        st.caption(tr('Upload your local FutureShift JSON file. Nothing changes until you confirm. Free text, background details and live GitHub evidence are not restored.'))
        uploaded = st.file_uploader(tr('Restore a saved plan'), type=['json'], key='restore_plan_upload')
        if uploaded is None:
            return
        try:
            prepared = validate_saved_plan(uploaded.getvalue(), load_demo)
        except ValueError as exc:
            st.error(translate_error(tr('Cannot restore this file: ') + str(exc)))
            return
        document = prepared['document']
        st.write(tr('Career: {v0} · 4 weeks · {v1} hours/week', v0=career_name(document['career']['code'], document['career']['title']), v1=document['weekly_hours']))
        st.write(tr('Completed tasks: {v0} / {v1}', v0=sum(prepared['completion'].values()), v1=len(prepared['completion'])))
        st.caption(display_text(document['notice']))
        with st.expander(tr('Review restored scoring answers'), expanded=False):
            from src.pathway import INTERESTS
            names = {**dict(INTERESTS), **(labels or {}), 'data_status': 'Profile data status'}
            st.table(table_text([{'Question': names.get(key, key), 'Answer': value}
                      for key, value in document['answers'].items()]))
        if st.button(tr('Confirm restore and open my plan'), key='restore_plan_confirm'):
            restore_saved_plan(st.session_state, prepared)
            st.rerun()
