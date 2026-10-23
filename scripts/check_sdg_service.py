"""Opt-in real AI SDG check: public tasks + synthetic profile; no real personal data.

Uses existing AI_* configuration, one bounded call per selected career, no retries.
Reports validation, cache reuse and exact mapping IDs, never credentials or payloads.
"""
import json
import logging
from pathlib import Path
import sys
from time import monotonic
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import load_onet
from src.pathway import sample_answers, confirmed_profile
from src.career_pool import official_ranking
from src.learning_plan import build_plan
from src.sdg_ai import SDGCache, context_for, generate_mapping
from src.cv_client import AIConfig, request_json


def main():
    logging.basicConfig(level=logging.INFO,format='%(name)s %(message)s')
    profile=confirmed_profile(sample_answers());data=load_onet()
    rows=official_ranking(profile,data);roles={r['code']:r for r in data['roles']}
    config=AIConfig.from_env();cache=SDGCache()
    # Two domains, bounded; remaining careers show explicit pending status in UI.
    for code in ('17-2199.03',):
        row=next(r for r in rows if r['code']==code)
        plan=build_plan(row,roles[code],5)
        areas=sorted({t['area'] for t in plan['tasks']})
        context=context_for(roles[code],areas);started=monotonic()
        try:
            def generator(ctx, cfg):
                def transport(payload, **kwargs):
                    document=request_json(payload, **kwargs)
                    # Public-source response only; no credentials, profile or request headers.
                    Path('/private/tmp/futureshift-sdg-public-response.json').write_text(json.dumps(document,ensure_ascii=False,indent=2))
                    return document
                return generate_mapping(ctx,cfg,transport=transport)
            entry,hit=cache.generate(context,config,generator=generator)
            # Fail loudly if any refresh or language render attempts another request.
            def no_request(*args):raise AssertionError('Cache missed; unexpected duplicate request')
            cached,hit_again=cache.generate(context,config,generator=no_request)
            assert hit_again and cached==entry
            print(json.dumps({'real_service':not hit,'cache_hit_initially':hit,'cache_reuse':hit_again,
                'career':code,'model':entry['model'],'elapsed_seconds':round(monotonic()-started,2),
                'entries':[{k:e[k] for k in ('item_id','status','task_source_id','target_id','source_ids')}
                           for e in entry['result']['entries']]},ensure_ascii=False),flush=True)
        except Exception as exc:
            # Error type and allowlisted validation codes only, never provider prose.
            from src.sdg_ai import SDGError
            print(json.dumps({'real_service_success':False,'career':code,'exception':type(exc).__name__,
                'validation_category':str(exc) if isinstance(exc,SDGError) else ('truncated' if 'truncated' in str(exc) else 'invalid_json' if 'invalid JSON' in str(exc) else 'timeout' if 'timeout' in str(exc) else 'protocol_or_service'),
                'elapsed_seconds':round(monotonic()-started,2)}),flush=True)
            return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
