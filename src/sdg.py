"""Read-only SDG presentation metadata, isolated from occupational scoring inputs."""
from html import escape
import json
from pathlib import Path
from typing import Any

from src.i18n import tr

CATALOG = json.loads((Path(__file__).resolve().parent.parent / 'data' / 'sdg_mappings.json')
                     .read_text(encoding='utf-8'))


def associations(code: str) -> list[dict]:
    """Only source-checked associations may produce a goal badge or a contribution claim."""
    record = CATALOG['roles'].get(code, {})
    return record.get('mappings', [])[:2] if record.get('status') == 'source_checked' else []


def render_sdg_preview(st: Any, code: str) -> None:
    """A fixed slot on every preview; text conveys meaning independently of color."""
    mappings = associations(code)
    badges = []
    for index, mapping in enumerate(mappings):
        goal = CATALOG['goals'][mapping['sdg_id']]
        label = tr('Primary association') if index == 0 else tr('Additional association')
        text = f"{label}: SDG {mapping['sdg_id']} · {tr(goal['name'])}"
        badges.append(f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:4px 8px;'
                      f'border-left:6px solid {goal["color"]};border-radius:4px;'
                      f'background:#fff;color:#14283f;font-size:0.875rem">{escape(text)}</span>')
    content = ''.join(badges) if badges else escape(tr('SDG mapping pending validation'))
    st.markdown(f'<div data-sdg-preview="{escape(code, quote=True)}" '
                f'style="margin:4px 0 12px"><strong>{tr("SDG")}</strong> · {content}</div>',
                unsafe_allow_html=True)


def render_sdg_details(st: Any, code: str) -> None:
    """Explain evidence and context separately from the match calculation."""
    st.markdown('#### ' + tr('How this pathway can contribute to the SDGs'))
    st.caption(tr('SDG associations do not indicate job prospects, career quality or personal fit, and never affect scores or rankings.'))
    mappings = associations(code)
    if not mappings:
        st.info(tr('SDG mapping pending validation'))
        st.write(tr('No task-to-target evidence has been checked for this occupation. No contribution is claimed.'))
        return
    for mapping in mappings:
        goal = CATALOG['goals'][mapping['sdg_id']]
        st.markdown(f"**SDG {mapping['sdg_id']} · {tr(goal['name'])} · "
                    + tr('Target {target}', target=mapping['target_id']) + '**')
        st.write(tr(mapping['reason']))
        st.caption(tr('Association type: {kind}', kind=tr(mapping['relation_type'])))
        st.caption(tr('Mapping status: {status}', status=tr('Source-checked association; impact not validated')))
        st.write(tr('Contribution depends on the actual role and application context.'))
        st.markdown(tr('Sources: [O*NET tasks]({occupation}) · [UN target definition]({target})',
                       occupation=mapping['occupation_source'], target=mapping['target_source']))
        st.caption(tr('Source check date: {date}', date=mapping['source_checked_on']))
