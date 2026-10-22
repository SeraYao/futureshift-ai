"""Versioned local plan transfer: allowlisted export and validate-before-confirm restore."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable

from src.scoring import SCORING_VERSION, rank_roles

VERSION = 'futureshift-plan-v1'
NOTICE = ('Prototype plan. Synthetic occupational requirements and trend signals are not employment predictions. '
          'Practice completion does not prove skill mastery or guarantee employment.')
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
                'notice': NOTICE, 'profile': confirmed_profile(answers), 'answers': answers,
                'career': {'code': role['code'], 'title': role['title']}, 'duration_weeks': 4,
                'weekly_hours': plan['weekly_hours'], 'plan': deepcopy(plan),
                'completion': {task['id']: bool(completion.get(task['id'], False)) for task in plan['tasks']},
                'last_assessment': {'scoring_version': SCORING_VERSION,
                    'source_fingerprint': source_fingerprint(assessment['roles'], assessment['trends']),
                    'data_status': 'synthetic_requirements_and_trends',
                    'results': assessment_summary(assessment['rows'])}}
    return json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)


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
        _, roles, trends = load_demo()
        code = document['career']['code']
        role = next((role for role in roles['roles'] if role['code'] == code), None)
        if role is None:
            raise ValueError('Occupation is not in the current prototype catalog')
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
    state['pathway_step'] = 7
    state['learning_role'] = plan['role_code']
    state['learning_hours'] = plan['weekly_hours']
    state['learning_progress'] = {plan['id']: deepcopy(prepared['completion'])}
    state['pathway_restored'] = True


def render_restore(st: Any, load_demo: Callable, labels: dict | None = None) -> None:
    """Validate an upload, show a readable preview, then ask for restore confirmation."""
    with st.expander('Restore a saved plan', expanded=False):
        st.caption('Upload your local FutureShift JSON file. Nothing changes until you confirm. '
                   'Free text, background details and live GitHub evidence are not restored.')
        uploaded = st.file_uploader('Restore a saved plan', type=['json'], key='restore_plan_upload')
        if uploaded is None:
            return
        try:
            prepared = validate_saved_plan(uploaded.getvalue(), load_demo)
        except ValueError as exc:
            st.error('Cannot restore this file: ' + str(exc))
            return
        document = prepared['document']
        st.write(f"Career: {document['career']['title']} · 4 weeks · {document['weekly_hours']} hours/week")
        st.write(f"Completed tasks: {sum(prepared['completion'].values())} / {len(prepared['completion'])}")
        st.caption(document['notice'])
        with st.expander('Review restored scoring answers', expanded=False):
            from src.pathway import INTERESTS
            names = {**dict(INTERESTS), **(labels or {}), 'data_status': 'Profile data status'}
            st.table([{'Question': names.get(key, key), 'Answer': value}
                      for key, value in document['answers'].items()])
        if st.button('Confirm restore and open my plan', key='restore_plan_confirm'):
            restore_saved_plan(st.session_state, prepared)
            st.rerun()
