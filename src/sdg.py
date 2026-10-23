"""Offline, locally reviewed SDG associations kept outside career scoring."""
from html import escape
import json
from pathlib import Path
from typing import Any

from src.i18n import tr, career_name, current_language, display_text

CATALOG = json.loads((Path(__file__).resolve().parent.parent / 'data' / 'sdg_mappings.json')
                     .read_text(encoding='utf-8'))


def validate_career_coverage() -> set[str]:
    """Fail loudly when a bundled official or demo occupation lacks a reviewed map."""
    root = Path(__file__).resolve().parent.parent
    expected: set[str] = set()
    for filename in ('onet_roles.json', 'demo_roles.json'):
        document = json.loads((root / 'data' / filename).read_text(encoding='utf-8'))
        expected.update(role['code'] for role in document['roles'])
    missing = sorted(code for code in expected
                     if CATALOG.get('roles', {}).get(code, {}).get('status') != 'analyst_reviewed'
                     or not CATALOG.get('roles', {}).get(code, {}).get('mappings'))
    if missing:
        raise ValueError('Missing locally reviewed SDG career mappings: ' + ', '.join(missing))
    for code in expected:
        for mapping in CATALOG['roles'][code]['mappings']:
            target_id = mapping['target_id']
            if (CATALOG.get('target_goal', {}).get(target_id) != mapping['sdg_id']
                    or target_id not in CATALOG.get('targets', {})
                    or mapping.get('source_checked_on') != CATALOG.get('checked_on')
                    or not mapping.get('source_ids')
                    or any(language not in mapping.get(field, {})
                           for field in ('scenario', 'contribution')
                           for language in ('en', 'zh', 'ms'))
                    or any(source_id not in CATALOG.get('sources', {})
                           for source_id in mapping.get('source_ids', []))):
                raise ValueError(f'Invalid local SDG target or source mapping for {code}')
    return expected


CAREER_IDS = validate_career_coverage()


def associations(code: str) -> list[dict]:
    """Return reviewed career-level links only; IDs and links stay language neutral."""
    record = CATALOG['roles'].get(code, {})
    return record.get('mappings', []) if record.get('status') == 'analyst_reviewed' else []


def skill_associations(code: str, area_id: str) -> list[dict]:
    """Return a reviewed role-and-skill association for a stable plan area ID."""
    record = CATALOG['roles'].get(code, {})
    if record.get('status') != 'analyst_reviewed':
        return []
    return record.get('skills', {}).get(area_id, [])


def _mapping_card(st: Any, mapping: dict, *, skill_name: str | None = None) -> None:
    goal = CATALOG['goals'][mapping['sdg_id']]
    prefix = tr('Skill application') if skill_name else tr('Career application')
    if skill_name:
        st.markdown('**' + tr('Skill link: {name}', name=display_text(skill_name)) + '**')
    st.markdown('**SDG {goal} · {name} · Target {target}**'.format(
        goal=mapping['sdg_id'], name=tr(goal['name']), target=mapping['target_id']))
    language = current_language()
    st.write(tr('Official target definition: ') + CATALOG['targets'][mapping['target_id']][language])
    st.write(prefix + ': ' + mapping['scenario'][language])
    if skill_name:
        st.write(tr('How this skill may be used: ') + mapping['skill_use'][language])
    st.write(tr('Project team analysis: ') + mapping['contribution'][language])
    st.caption(tr('Association type: {kind}', kind=tr(mapping['relation_type'])))
    st.caption(tr('This is a conditional application analysis, not an official SDG endorsement or a measured impact.'))
    with st.expander(tr('View mapping sources')):
        for source_id in mapping['source_ids']:
            source = CATALOG['sources'][source_id]
            st.markdown(f"[{escape(source['title'])}]({source['url']})")
            st.caption(tr('Source ID: {id}', id=source_id))
            if source.get('excerpt'):
                st.write(source['excerpt'])
    st.caption(tr('Sources checked on {date}', date=mapping['source_checked_on']))


def render_sdg_preview(st: Any, code: str) -> None:
    """A compact career association status for result cards."""
    mappings = associations(code)
    badges = []
    for index, mapping in enumerate(mappings[:2]):
        goal = CATALOG['goals'][mapping['sdg_id']]
        label = tr('Primary association') if index == 0 else tr('Additional association')
        text = f"{label}: SDG {mapping['sdg_id']} · {tr(goal['name'])}"
        badges.append(f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:4px 8px;'
                      f'border-left:6px solid {goal["color"]};border-radius:4px;'
                      f'background:#fff;color:#14283f;font-size:0.875rem">{escape(text)}</span>')
    content = ''.join(badges) if badges else escape(tr('No reviewed SDG association'))
    st.markdown(f'<div data-sdg-preview="{escape(code, quote=True)}" '
                f'style="margin:4px 0 12px"><strong>{tr("SDG")}</strong> · {content}</div>',
                unsafe_allow_html=True)


def render_sdg_result_card(st: Any, code: str, title: str | None = None) -> None:
    """Show each recommended occupation's reviewed SDG claim beside results."""
    mappings = associations(code)
    display_name = career_name(code, title or code)
    st.markdown(f'<div data-sdg-result="{escape(code, quote=True)}"></div>',
                unsafe_allow_html=True)
    st.markdown('#### ' + tr('SDG links for {career}', career=display_name))
    if not mappings:
        st.info(tr('No reviewed SDG association'))
        return
    language = current_language()
    for index, mapping in enumerate(mappings):
        goal = CATALOG['goals'][mapping['sdg_id']]
        st.markdown('**SDG {goal} · {name} · Target {target}**'.format(
            goal=mapping['sdg_id'], name=tr(goal['name']), target=mapping['target_id']))
        st.write(tr('Project team analysis: ') + mapping['contribution'][language])
        with st.expander(tr('View target and sources · {target}', target=mapping['target_id']),
                         key=f'sdg_result_{code}_{index}'):
            st.write(tr('Application scenario: ') + mapping['scenario'][language])
            st.write(tr('Official target definition: ') + CATALOG['targets'][mapping['target_id']][language])
            for source_id in mapping['source_ids']:
                source = CATALOG['sources'][source_id]
                st.markdown(f"[{escape(source['title'])}]({source['url']})")
                st.caption(tr('Source ID: {id}', id=source_id))
            st.caption(tr('Sources checked on {date}', date=mapping['source_checked_on']))


def render_sdg_details(st: Any, code: str, role: dict | None = None,
                       area_ids: list[str] | tuple[str, ...] = (), labels: dict | None = None,
                       *, include_career: bool = True) -> None:
    """Render local career and selected-plan mappings without AI, network or cache access."""
    st.markdown('#### ' + tr('Reviewed SDG associations'))
    st.caption(tr('The career directory is a fixed local snapshot. Profile matching is computed from the bundled occupation data; external evidence snapshots are separate. SDG links below are local, human-reviewed interpretations and do not affect scores.'))
    career_mappings = associations(code) if include_career else []
    if include_career and not career_mappings:
        st.info(tr('No reviewed SDG association'))
        st.write(tr('No reliable occupation-to-target application link is currently recorded for this item.'))
    else:
        for mapping in career_mappings:
            _mapping_card(st, mapping)
    if area_ids:
        st.markdown('##### ' + tr('Skills in this learning plan'))
        for area_id in sorted(set(area_ids)):
            name = (labels or {}).get(area_id, area_id)
            mappings = skill_associations(code, area_id)
            if not mappings:
                st.write(tr('No reviewed SDG link for {item}', item=display_text(name)))
                continue
            for mapping in mappings:
                _mapping_card(st, mapping, skill_name=name)


def render_local_sdg(st: Any, rows: list[dict], roles: dict, labels: dict,
                     assessment: dict) -> None:
    """Show local SDG associations for learning-plan skills."""
    from src.learning_plan import build_plan

    st.subheader(tr('SDG links for learning-plan skills'))
    st.caption(tr('Fixed local mapping catalog · no AI configuration, network call or runtime generation.'))
    hours = assessment.get('selected_hours') or {'3 hours': 3, '5 hours': 5,
        '8 hours': 8, '10+ hours': 10}.get(assessment['answers'].get('Weekly learning time'), 3)
    for row in rows:
        code = row['code']
        role = roles[code]
        plan = build_plan(row, role, hours)
        areas = [task['area'] for task in plan['tasks']]
        with st.expander(tr('SDG links · {career}', career=career_name(code, role['title']))):
            render_sdg_details(st, code, role, areas, labels, include_career=False)
