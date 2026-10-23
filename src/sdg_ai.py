"""Explicit, public-context AI SDG analysis with strict provenance and content cache.

No profile text, ratings or CV is sent. No SDG output enters any scoring function.
Source-valid output is an AI inference, never a verified causal contribution.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from threading import RLock
from time import monotonic

from src.cv_client import AIConfig, request_json
from src.cv_pdf import CVError

ROOT=Path(__file__).resolve().parent.parent
CONTEXT=json.loads((ROOT/'data/sdg_context.json').read_text())
PROMPT_VERSION='sdg-context-v3'
VALIDATOR_VERSION='sdg-validator-v2'
CACHE_PATH=ROOT/'data/cache/sdg_ai.json'
_LOCK=RLock()
logger=logging.getLogger(__name__)

class SDGError(ValueError):
    """Safe, allowlisted validation category without returned provider prose."""


def context_for(role, area_ids):
    code=role['code']
    areas=sorted(set(area_ids))
    if not set(areas)<=set(CONTEXT['elements']):
        raise SDGError('unknown_item')
    tasks=CONTEXT['roles'].get(code,[])[:12]
    if not tasks:
        raise SDGError('missing_context')
    sources={t['id']:deepcopy(t) for t in tasks}
    for area in areas:
        group='skills' if area.startswith('skill_') else 'knowledge'
        item=role.get(group,{}).get(area)
        if not item or item.get('issues') or any(r.get('issues') for r in item.get('sources',{}).values()):
            raise SDGError('missing_context')
        element=deepcopy(CONTEXT['elements'][area])
        # A role-specific rating establishes relevance, not task-to-target causality.
        source_id=f'onet-rating:{code}:{area}'
        sources[source_id]={'id':source_id,'kind':'rating','career_code':code,'area_id':area,
            'text':element['name']+': '+element['text'],'element_id':element['element_id'],
            'url':role['identity_source_url'],'sources':deepcopy(item.get('sources',{}))}
    for target in CONTEXT['targets'].values():
        sources[target['id']]=deepcopy(target)
    return {'career_code':code,'official_title':role['title'],'items':[code,*areas],
            'scenario_version':'official-tasks-first12-v1',
            'context_version':CONTEXT['version'],'sources':sources}


def cache_key(context, config):
    return hashlib.sha256(json.dumps({'context':context,'model':config.model,
        'endpoint_hash':hashlib.sha256(config.base_url.encode()).hexdigest(),
        'prompt_version':PROMPT_VERSION,'validator_version':VALIDATOR_VERSION},
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _localized(value, *, context=None, references=(), target=None):
    if not isinstance(value,dict) or set(value)!={'en','zh','ms'}:
        raise SDGError('invalid_translations')
    for language,text in value.items():
        if not isinstance(text,str) or not 3<=len(text.strip())<=500 or re.search(r'https?://|www\.|[%％]',text):
            raise SDGError('invalid_text')
        # Only declared SDG/target identifiers may contain numbers: no invented statistics.
        # Remove full target IDs before goal IDs: SDG 7.3 must not leave a stray .3.
        checked=re.sub(r'(?<![\d.])(?:6\.3|7\.3|9\.4|9\.5|12\.[256])(?!\d|\.\d)', '',text)
        checked=re.sub(r'SDG\s*(?:6|7|9|12)\b', '',checked)
        # Exact cited task identifiers are references, not generated statistics.
        if context is not None:
            for item_id in context['items']:
                checked=checked.replace(item_id,'')
            for source_id in references:
                source=context['sources'][source_id]
                checked=checked.replace(source_id,'')
                if source['kind']=='task':
                    checked=re.sub(r'(?<![\d.])'+re.escape(source['task_id'])+r'(?![\d.])','',checked)
            definition=CONTEXT['targets'].get(target,{}) if isinstance(target,str) else {}
            if '2030' in definition.get('text',''):
                checked=re.sub(r'(?i)\b(?:by|before|menjelang|sebelum|pada tahun)\s+2030\b|2030\s*年','',checked)
        if re.search(r'\d',checked):
            logger.warning('sdg_validation category=unverified_statistics language=%s numeric_tokens=%s',
                           language,re.findall(r'\d+(?:\.\d+)?',checked)[:8])
            raise SDGError('unverified_statistics')
        if language=='zh' and not re.search(r'[\u4e00-\u9fff]',text):
            raise SDGError('invalid_translations')
    return value


def validate_mapping(document, context):
    if not isinstance(document,dict) or set(document)!={'career_code','entries'} or document['career_code']!=context['career_code']:
        raise SDGError('invalid_structure')
    entries=document['entries']
    if not isinstance(entries,list) or len(entries)!=len(context['items']):
        raise SDGError('incomplete_coverage')
    seen=set();sources=context['sources']
    required={'item_id','status','task_source_id','target_id','source_ids','scenario','explanation'}
    for entry in entries:
        if not isinstance(entry,dict) or set(entry)!=required:
            raise SDGError('invalid_structure')
        item=entry['item_id']
        if not isinstance(item,str) or item not in context['items'] or item in seen:
            raise SDGError('unknown_or_duplicate_item')
        seen.add(item)
        if entry['status'] not in ('linked','insufficient_evidence'):
            raise SDGError('invalid_status')
        ids=entry['source_ids']
        if not isinstance(ids,list) or any(not isinstance(x,str) or x not in sources for x in ids) or len(ids)!=len(set(ids)):
            raise SDGError('unknown_source')
        task=entry['task_source_id'];target=entry['target_id']
        for field in ('scenario','explanation'):
            _localized(entry[field],context=context,references=ids,target=target)
        if entry['status']=='insufficient_evidence':
            if target is not None or task is not None or ids:
                raise SDGError('unsupported_claim')
            continue
        if not isinstance(task,str) or task not in sources or sources[task]['kind']!='task' or sources[task]['career_code']!=context['career_code']:
            raise SDGError('wrong_task')
        if not isinstance(target,str) or 'un-target:'+target not in sources:
            raise SDGError('invalid_target')
        required_ids={task,'un-target:'+target}
        if item!=context['career_code']:
            required_ids.add(f'onet-rating:{context["career_code"]}:{item}')
        if not required_ids<=set(ids):
            logger.warning('sdg_validation category=missing_support item=%s missing_sources=%s',
                           item,sorted(required_ids-set(ids)))
            raise SDGError('missing_support')
        if item!=context['career_code'] and len(ids)!=3:
            raise SDGError('wrong_skill_source')
        if item==context['career_code'] and len(ids)>len(context['items'])+1:
            raise SDGError('excess_sources')
        # No cross-career or different-skill citations, even when other sources are valid.
        if item!=context['career_code'] and any(
                sources[x]['kind']=='rating' and sources[x]['area_id']!=item for x in ids):
            raise SDGError('wrong_skill_source')
    if seen!=set(context['items']):
        raise SDGError('incomplete_coverage')
    return deepcopy(document)


def mapping_schema(context):
    localized={'type':'object','properties':{l:{'type':'string'} for l in ('en','zh','ms')},
               'required':['en','zh','ms'],'additionalProperties':False}
    properties={'item_id':{'enum':context['items']},'status':{'enum':['linked','insufficient_evidence']},
        'task_source_id':{'type':['string','null']},'target_id':{'enum':[None,*CONTEXT['targets']]},
        'source_ids':{'type':'array','items':{'enum':list(context['sources'])}},
        'scenario':localized,'explanation':localized}
    task_ids=[k for k,v in context['sources'].items() if v['kind']=='task']
    target_ids=[k for k,v in context['sources'].items() if v['kind']=='target']
    choices=[]
    for item in context['items']:
        count=2 if item==context['career_code'] else 3
        maximum=2+len(context['items'])-1 if item==context['career_code'] else 3
        needs=[{'contains':{'enum':task_ids}},{'contains':{'enum':target_ids}}]
        if count==3:needs.append({'contains':{'const':f'onet-rating:{context["career_code"]}:{item}'}})
        fields=deepcopy(properties);fields['item_id']={'const':item}
        choices.append({'type':'object','properties':fields,'required':list(fields),
            'additionalProperties':False,'if':{'properties':{'status':{'const':'linked'}}},
            'then':{'properties':{'source_ids':{'minItems':count,'maxItems':maximum,'allOf':needs}}},
            'else':{'properties':{'source_ids':{'maxItems':0}}}})
    return {'type':'object','properties':{'career_code':{'const':context['career_code']},
        'entries':{'type':'array','minItems':len(context['items']),'maxItems':len(context['items']),
                   'items':{'oneOf':choices}}},'required':['career_code','entries'],'additionalProperties':False}


def generate_mapping(context, config, *, transport=request_json):
    prompt=('Analyse possible SDG links using ONLY the supplied public source records. '
        'Return JSON only, no reasoning outside JSON. Do not use personal data or outside knowledge. '
        'Cover every item exactly once: career code and EACH recommended skill/knowledge ID. '
        'A skill has no intrinsic SDG contribution: describe how it could be used in one actual supplied occupational task. '
        'Task and target definitions must substantively support the application; a real citation alone is insufficient. '
        'Generic advice, system design or data analysis does not establish research/innovation under target 9.5. '
        'Do not invent a sustainable application absent from the supplied task. No statistics, percentages, impact scores, '
        'employment claims, URLs, citations or numbers in prose (target IDs belong in target_id only). '
        'Use status insufficient_evidence if no defensible specific task-to-target mechanism exists; then task_source_id '
        'and target_id are null, source_ids is [], and explain why. This is a valid successful result. '
        'For linked status, source_ids must include the exact onet-task ID, un-target ID and, for a skill/knowledge item, '
        'its own role-specific onet-rating ID. A career needs task and target IDs and may additionally cite its related skill ratings; a skill needs EXACTLY THREE source_ids. '
        'The target source ID and rating source ID are MANDATORY, not just task IDs. Never copy the entire task list. '
        'Never cite another skill or career. Keep all IDs and dates in the structured fields, not prose. '
        'Write scenario and explanation in en, zh and ms, naturally and with IDENTICAL meaning. '
        'Keep each translation concise (one short clause, at most fifteen words), use conditional language, never promise outcomes. '
        'Schema: '+json.dumps(mapping_schema(context),ensure_ascii=False))
    if config.model.startswith('Qwen/Qwen3-'):
        prompt += '\n/no_think'  # documented Qwen3 soft switch; no model/provider change
    # Public task/definition text only; strip raw rating rows to minimise model input.
    compact=deepcopy(context)
    task_example=next(k for k,v in context['sources'].items() if v['kind']=='task')
    compact['citation_examples']={item:[task_example,'un-target:7.3']+
        ([f'onet-rating:{context["career_code"]}:{item}'] if item!=context['career_code'] else [])
        for item in context['items']}
    prompt += ' Citation examples in the context show the required exact ID format for each item; choose the actual supported target. Use Malaysian Malay (jurutera, mampan), with the same conditional meaning in all languages.'
    for source in compact['sources'].values():
        source.pop('raw',None);source.pop('sources',None)
    source=json.dumps(compact,ensure_ascii=False)
    payload={'model':config.model,'temperature':0,'response_format':{'type':'json_object'},
             'messages':[{'role':'system','content':prompt},{'role':'user','content':source}],
             'max_tokens':4200}
    return validate_mapping(transport(payload,config=config,source=source),context)


class SDGCache:
    def __init__(self,path=CACHE_PATH):
        self.path=Path(path)

    def get(self,context,config):
        with _LOCK:
            try:
                document=json.loads(self.path.read_text())
            except FileNotFoundError:
                return None
            except (OSError,ValueError):
                raise SDGError('invalid_cache') from None
            entry=document.get(cache_key(context,config)) if isinstance(document,dict) else None
            if entry is None:return None
            try:
                validate_mapping(entry['result'],context)
                if entry['model']!=config.model or entry['prompt_version']!=PROMPT_VERSION:
                    raise SDGError('invalid_cache')
            except (KeyError,TypeError,SDGError):
                raise SDGError('invalid_cache') from None
            return deepcopy(entry)

    def generate(self,context,config,*,generator=generate_mapping):
        # Lock spans one explicit request: simultaneous identical submissions reuse success.
        with _LOCK:
            try:existing=self.get(context,config)
            except SDGError:existing=None  # explicit manual retry can repair a damaged cache
            if existing is not None:return existing,True
            started=monotonic()
            result=validate_mapping(generator(context,config),context)
            entry={'result':result,'model':config.model,'prompt_version':PROMPT_VERSION,
                   'created_at':datetime.now(timezone.utc).isoformat()}
            try:
                previous=json.loads(self.path.read_text()) if self.path.exists() else {}
                if not isinstance(previous,dict):previous={}
            except (OSError,ValueError):previous={}
            previous[cache_key(context,config)]=entry
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix('.tmp')
            try:
                temporary.write_text(json.dumps(previous,ensure_ascii=False))
                temporary.replace(self.path)
            except OSError:
                raise SDGError('cache_write_failed') from None
            logger.info('sdg_ai stage=validated career=%s items=%d elapsed_ms=%d',
                        context['career_code'],len(context['items']),(monotonic()-started)*1000)
            return deepcopy(entry),False
