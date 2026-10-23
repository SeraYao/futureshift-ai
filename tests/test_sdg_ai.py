"""Strict provenance, coverage, versioned cache and non-blocking manual retry."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import load_onet, ROOT
from src.cv_client import AIConfig
from src.cv_pdf import CVError
from src.i18n import set_language
from src.sdg_ai import (CONTEXT, SDGCache, SDGError, context_for, cache_key,
                        validate_mapping, generate_mapping)


def context(code='17-2199.03', areas=('skill_01','knowledge_03')):
    return context_for(next(r for r in load_onet()['roles'] if r['code']==code),areas)


def response(ctx, *, linked=True):
    code=ctx['career_code'];task=next(k for k,v in ctx['sources'].items() if v['kind']=='task')
    entries=[]
    for item in ctx['items']:
        entries.append({'item_id':item,'status':'linked' if linked else 'insufficient_evidence',
            'task_source_id':task if linked else None,'target_id':'7.3' if linked else None,
            'source_ids':([task,'un-target:7.3']+([f'onet-rating:{code}:{item}'] if item!=code else [])) if linked else [],
            'scenario':{'en':'Review an energy audit.','zh':'审核能源审计。','ms':'Semak audit tenaga.'},
            'explanation':{'en':'Could inform efficiency improvements.','zh':'可为能效改进提供依据。','ms':'Boleh memaklumkan penambahbaikan kecekapan.'}})
    return {'career_code':code,'entries':entries}


class SDGValidationTests(unittest.TestCase):
    def setUp(self):
        self.context=context();self.config=AIConfig('https://example.org/v1','test-model','test-key')

    def test_official_context_is_source_derived(self):
        self.assertEqual(CONTEXT['task_source']['total_rows'],18838)
        self.assertEqual(len(CONTEXT['task_source']['sha256']),64)
        for source in CONTEXT['targets'].values():
            self.assertTrue(source['url'].startswith('https://sdgs.un.org/goals/goal'))
            self.assertTrue(source['text'])
        for task in self.context['sources'].values():
            if task['kind']=='task':self.assertEqual(task['text'],task['raw']['Task'])

    def test_valid_linked_and_explicit_insufficient(self):
        for linked in (True,False):
            doc=response(self.context,linked=linked)
            self.assertEqual(validate_mapping(doc,self.context),doc)

    def test_diagnostic_accepts_raw_and_cached_result_shapes(self):
        from scripts.check_sdg_service import mapping_result
        doc=response(self.context)
        self.assertEqual(mapping_result(doc),doc)
        self.assertEqual(mapping_result({'result':doc,'model':'test-model'}),doc)
        with self.assertRaises(ValueError):mapping_result({'result':{'wrong':True}})

    def test_target_identifiers_are_not_mistaken_for_statistics(self):
        doc=response(self.context)
        doc['entries'][0]['explanation']={'en':'Could support SDG 7.3.', 'zh':'可支持 SDG 7.3。', 'ms':'Boleh menyokong SDG 7.3.'}
        validate_mapping(doc,self.context)
        doc['entries'][0]['explanation']['en']='Could save 20 units.'
        with self.assertRaises(SDGError):validate_mapping(doc,self.context)

    def test_verified_task_references_and_target_deadline_are_not_statistics(self):
        doc=response(self.context)
        task=self.context['sources'][doc['entries'][0]['task_source_id']]['task_id']
        doc['entries'][0]['explanation']={'en':f'Task {task} could support energy efficiency by 2030.',
            'zh':f'任务 {task} 可为2030年能效目标提供支持。',
            'ms':f'Tugas {task} boleh menyokong kecekapan tenaga menjelang 2030.'}
        validate_mapping(doc,self.context)
        doc['entries'][0]['explanation']['en']='Could save 208550 units.'
        with self.assertRaises(SDGError):validate_mapping(doc,self.context)

    def test_internal_item_ids_in_prose_are_not_statistics(self):
        doc=response(self.context,linked=False)
        item=self.context['items'][1]
        doc['entries'][1]['explanation']={'en':f'Insufficient task evidence for {item}.',
            'zh':f'{item} 缺少具体任务依据。','ms':f'Bukti tugas tidak mencukupi bagi {item}.'}
        validate_mapping(doc,self.context)

    def test_career_can_cite_its_own_skills_without_reusing_another_skill_mapping(self):
        doc=response(self.context)
        doc['entries'][0]['source_ids'].append(f'onet-rating:{self.context["career_code"]}:skill_01')
        validate_mapping(doc,self.context)
        doc['entries'][1]['source_ids'].append(f'onet-rating:{self.context["career_code"]}:skill_01')
        with self.assertRaises(SDGError):validate_mapping(doc,self.context)

    def test_reject_unknown_duplicate_missing_items_and_fields(self):
        for mutate in (lambda d:d.update(career_code='wrong'),
                       lambda d:d['entries'].pop(),
                       lambda d:d['entries'][1].update(item_id=d['entries'][0]['item_id']),
                       lambda d:d['entries'][0].update(item_id='unknown'),
                       lambda d:d.update(extra=True),
                       lambda d:d['entries'][0].update(extra=True)):
            doc=response(self.context);mutate(doc)
            with self.assertRaises(SDGError):validate_mapping(doc,self.context)

    def test_reject_unknown_target_source_wrong_skill_and_task(self):
        for changes in ({'target_id':'99.1'}, {'source_ids':['fabricated']},
                        {'task_source_id':'un-target:7.3'}, {'source_ids':['un-target:7.3']},
                        {'status':'guaranteed'}, {'scenario':{'en':'Only English'}},
                        {'explanation':{'en':'Saves 50%.','zh':'节省百分比50%。','ms':'Menjimatkan 50%.'}}):
            doc=response(self.context);doc['entries'][0].update(changes)
            with self.assertRaises(SDGError):validate_mapping(doc,self.context)
        doc=response(self.context)
        doc['entries'][1]['source_ids'].append(f'onet-rating:{self.context["career_code"]}:skill_01')
        with self.assertRaises(SDGError):validate_mapping(doc,self.context)
        doc=response(self.context,linked=False);doc['entries'][0]['target_id']='7.3'
        with self.assertRaises(SDGError):validate_mapping(doc,self.context)

    def test_prompt_transport_uses_only_public_context(self):
        seen=[]
        def transport(payload,**kwargs):
            seen.append((payload,kwargs));return response(self.context)
        result=generate_mapping(self.context,self.config,transport=transport)
        self.assertEqual(result,response(self.context))
        payload,kwargs=seen[0]
        self.assertEqual(payload['model'],self.config.model)
        self.assertEqual(payload['max_tokens'],4200)
        self.assertNotIn('profile',json.loads(kwargs['source']))
        self.assertNotIn('api_key',kwargs['source'])

    def test_cache_and_invalidation_include_context_model_prompt_not_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=SDGCache(Path(tmp)/'cache.json');calls=[]
            def generator(ctx,config):calls.append(True);return response(ctx)
            first,hit=cache.generate(self.context,self.config,generator=generator)
            self.assertFalse(hit)
            for language in ('en','zh','ms'):
                set_language(language)
                self.assertEqual(cache.get(self.context,self.config),first)
                self.assertTrue(cache.generate(self.context,self.config,generator=generator)[1])
            self.assertEqual(len(calls),1)
            changed=context(areas=('skill_01',))
            self.assertNotEqual(cache_key(changed,self.config),cache_key(self.context,self.config))
            self.assertIsNone(cache.get(changed,self.config))
            self.assertIsNone(cache.get(self.context,AIConfig('https://example.org/v1','changed','key')))
            changed=deepcopy(self.context);next(iter(changed['sources'].values()))['text']+=' changed'
            self.assertNotEqual(cache_key(changed,self.config),cache_key(self.context,self.config))
            with patch('src.sdg_ai.PROMPT_VERSION','changed'):
                self.assertIsNone(cache.get(self.context,self.config))
            self.assertNotEqual(cache_key(context('17-2081.00'),self.config),cache_key(self.context,self.config))
        set_language('en')

    def test_failed_generation_never_cached_and_manual_retry_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=SDGCache(Path(tmp)/'cache.json');calls=[]
            def fail(ctx,config):calls.append(True);raise CVError('AI timeout error.')
            with self.assertRaises(CVError):cache.generate(self.context,self.config,generator=fail)
            self.assertIsNone(cache.get(self.context,self.config))
            self.assertEqual(calls,[True])
            entry,hit=cache.generate(self.context,self.config,generator=lambda ctx,c:response(ctx,linked=False))
            self.assertFalse(hit);self.assertIsNotNone(cache.get(self.context,self.config))
            # A damaged cached response is not accepted as a successful mapping.
            doc=json.loads(cache.path.read_text());doc[cache_key(self.context,self.config)]['result']['entries'][0]['target_id']='99.1'
            cache.path.write_text(json.dumps(doc))
            with self.assertRaises(SDGError):cache.get(self.context,self.config)

    def test_actual_ui_failure_retry_and_state_preservation(self):
        from streamlit.testing.v1 import AppTest
        config=self.config
        with tempfile.TemporaryDirectory() as tmp:
            cache=SDGCache(Path(tmp)/'cache.json')
            original_generate=cache.generate
            calls=[];busy_during_calls=[]
            def generation(ctx,c):
                calls.append(ctx['career_code'])
                from streamlit import session_state
                busy_during_calls.append(session_state.get('sdg_busy_'+cache_key(ctx,c),False))
                if len(calls)==1:raise CVError('AI timeout error.')
                return original_generate(ctx,c,generator=lambda ctx,c:response(ctx,linked=False))
            with patch('src.cv_client.AIConfig.from_env',return_value=config),patch('src.sdg_ai.SDGCache',return_value=cache),patch.object(cache,'generate',side_effect=generation):
                page=AppTest.from_file(str(ROOT/'app.py')).run()
                page.button(key='scenario_explore').click().run()
                page.button(key='pathway_sample').click().run()
                page.selectbox(key='learning_role').set_value('17-2199.03').run()
                task=next(b for b in page.checkbox if b.key.startswith('learning_check_'));task.check().run()
                assessment=deepcopy(page.session_state['pathway_assessment']);progress=deepcopy(page.session_state['learning_progress'])
                self.assertEqual(calls,[])
                page.button(key='sdg_generate_17-2199.03').click().run()
                self.assertFalse(page.exception)
                self.assertFalse(page.button(key='sdg_generate_17-2199.03').disabled)
                self.assertTrue(any('timed out' in v.value for v in page.warning))
                page.run();self.assertEqual(len(calls),1)
                page.button(key='sdg_generate_17-2199.03').click().run()
                self.assertEqual(len(calls),2)
                self.assertEqual(busy_during_calls,[True,True])
                self.assertFalse(page.exception)
                for language in ('zh','ms','en'):
                    page.selectbox(key='ui_language').set_value(language).run()
                    self.assertFalse(page.exception)
                    self.assertEqual(page.session_state['pathway_assessment'],assessment)
                    self.assertEqual(page.session_state['learning_progress'],progress)
                self.assertEqual(len(calls),2)
