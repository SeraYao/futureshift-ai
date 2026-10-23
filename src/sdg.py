"""Read-only SDG presentation metadata, isolated from occupational scoring inputs."""
from html import escape
import json
from pathlib import Path
from typing import Any

from src.i18n import tr, career_name

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


def render_dynamic_sdg(st: Any, rows: list[dict], roles: dict, labels: dict, assessment: dict) -> None:
    """Status for every recommended role and actual budget-selected practice area."""
    from src.cv_client import AIConfig
    from src.cv_pdf import CVError
    from src.learning_plan import build_plan
    from src.sdg_ai import (SDGCache, SDGError, context_for, cache_key, PROMPT_VERSION)
    import re
    st.subheader(tr('AI analysis · career and skill links to SDG targets'))
    st.caption(tr('Only public occupational tasks, recommended skill IDs and official target definitions are sent after your click. No profile answers or CV are sent. No automatic calls or retries.'))
    st.warning(tr('AI analysis, not verified impact. Source validity does not prove the inference. Contribution depends on the application; no SDG score affects career matching.'))
    try:
        config=AIConfig.from_env()
    except CVError:
        st.info(tr('SDG AI is not configured. Career recommendations and learning plans remain available.'))
        config=None
    if config:
        st.caption(tr('Configured SDG model: {model} · Prompt: {prompt}',model=config.model,prompt=PROMPT_VERSION))
    cache=SDGCache()
    language=st.session_state.get('ui_language','en')
    hours=assessment.get('selected_hours') or {'3 hours':3,'5 hours':5,'8 hours':8,'10+ hours':10}.get(
        assessment['answers'].get('Weekly learning time'),3)
    for row in rows:
        code=row['code'];role=roles[code]
        plan=build_plan(row,role,hours)
        areas=sorted({t['area'] for t in plan['tasks']})
        names={code:career_name(code,role['title']),**{a:tr('Skills' if a.startswith('skill_') else 'Knowledge')+' · '+tr(labels[a]) for a in areas}}
        with st.expander(tr('SDG analysis for {career}',career=names[code])):
            st.caption(tr('Scope: this career and the skill/knowledge areas selected by the current practice-time budget. Changing career context or areas creates a separate analysis.'))
            try:
                context=context_for(role,areas)
                key=cache_key(context,config) if config else code
                entry=cache.get(context,config) if config else None
            except SDGError as exc:
                st.warning(tr('SDG analysis unavailable: {reason}. Recommendations and plans are unchanged.',reason=tr('Source or response validation failed')))
                # Missing context is never sent; invalid cache can be repaired by explicit retry.
                if str(exc)!='invalid_cache':continue
                entry=None
            if entry:
                st.caption(tr('Cached AI analysis · Model: {model} · Prompt: {prompt} · Generated: {date}',
                    model=entry['model'],prompt=entry['prompt_version'],date=entry['created_at']))
                for item in entry['result']['entries']:
                    st.markdown('**'+names[item['item_id']]+'**')
                    if item['status']=='insufficient_evidence':
                        st.info(tr('No reliable association established'))
                    else:
                        st.write('SDG '+item['target_id'].split('.')[0]+' · '+tr('Target {target}',target=item['target_id']))
                    st.write(item['scenario'][language]);st.write(item['explanation'][language])
                    if item['source_ids']:
                        with st.expander(tr('View supporting public sources')+' · '+names[item['item_id']]):
                            for source_id in item['source_ids']:
                                source=context['sources'][source_id]
                                st.markdown(f'[{source_id}]({source["url"]})')
                                st.caption(tr('Original official source text; the application scenario above is AI analysis.'))
                                st.write(source['text'])
                            st.caption(tr('Official context checked: {date}',date='2026-10-23'))
                continue
            for item_id,name in names.items():
                st.write(name+' · '+tr('Not analysed yet'))
            failure=st.session_state.get('sdg_failure_'+key)
            if failure:
                explanation = (tr('AI service timed out') if failure == 'timeout' else
                    tr('AI connection or response error') if failure == 'response_or_connection' else
                    tr('Local cache is unavailable') if failure in ('cache_unavailable', 'cache_write_failed', 'invalid_cache') else
                    failure if failure.startswith('HTTP ') else tr('Source or response validation failed'))
                st.warning(tr('SDG analysis unavailable: {reason}. Recommendations and plans are unchanged.',reason=explanation))
            busy_key='sdg_busy_'+key
            def queue(state, target, busy):
                state[busy]=True
                state['sdg_pending']=target
            st.button(tr('Retry SDG analysis') if failure else tr('Generate SDG analysis'),key='sdg_generate_'+code,
                disabled=config is None or st.session_state.get(busy_key,False),
                on_click=queue,args=(st.session_state,key,busy_key))
            if st.session_state.get('sdg_pending')==key:
                st.session_state.pop('sdg_pending',None)
                try:
                    with st.spinner(tr('Analysing public evidence…')):
                        cache.generate(context,config)
                    st.session_state.pop('sdg_failure_'+key,None)
                except (CVError,SDGError,OSError) as exc:
                    if isinstance(exc,SDGError):reason=tr('Source or response validation failed')
                    elif isinstance(exc,CVError):
                        match=re.search(r'HTTP error (\d{3})',str(exc))
                        reason='HTTP '+match[1] if match else ('timeout' if 'timeout' in str(exc).lower() else 'response_or_connection')
                    else:reason='cache_unavailable'
                    st.session_state['sdg_failure_'+key]=reason
                finally:
                    st.session_state[busy_key]=False
                st.rerun()
