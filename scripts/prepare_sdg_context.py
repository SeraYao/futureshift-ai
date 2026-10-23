"""Offline, source-preserving extract of official tasks and SDG target definitions.

Requires a complete O*NET 31.0 task_statements.csv and content_model_reference.csv.
UN target definitions checked against the linked official pages on 2026-10-23.
No occupational requirements or associations are generated here.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TARGETS={
 '6.3':'By 2030, improve water quality by reducing pollution, eliminating dumping and minimizing release of hazardous chemicals and materials, halving the proportion of untreated wastewater and substantially increasing recycling and safe reuse globally',
 '7.3':'By 2030, double the global rate of improvement in energy efficiency',
 '9.4':'By 2030, upgrade infrastructure and retrofit industries to make them sustainable, with increased resource-use efficiency and greater adoption of clean and environmentally sound technologies and industrial processes, with all countries taking action in accordance with their respective capabilities',
 '9.5':'Enhance scientific research, upgrade the technological capabilities of industrial sectors in all countries, in particular developing countries, including, by 2030, encouraging innovation and substantially increasing the number of research and development workers per 1 million people and public and private research and development spending',
 '12.2':'By 2030, achieve the sustainable management and efficient use of natural resources',
 '12.5':'By 2030, substantially reduce waste generation through prevention, reduction, recycling and reuse',
 '12.6':'Encourage companies, especially large and transnational companies, to adopt sustainable practices and to integrate sustainability information into their reporting cycle',
}

def extract(tasks_path, elements_path):
    official=json.loads((ROOT/'data/onet_roles.json').read_text())
    codes={r['code'] for r in official['roles']}
    raw=tasks_path.read_bytes()
    with tasks_path.open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    if len(rows)<18000 or any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError('Incomplete task CSV; no extract written')
    roles={code:[] for code in codes}
    for line,row in enumerate(rows,2):
        code=row['O*NET-SOC Code']
        if code in roles:
            roles[code].append({'id':f'onet-task:{code}:{row["Task ID"]}', 'kind':'task',
                'career_code':code,'task_id':row['Task ID'],'text':row['Task'],
                'url':'https://www.onetonline.org/link/details/'+code+'#Tasks',
                'date':row['Date'],'row_number':line,'raw':row})
    with elements_path.open(encoding='utf-8-sig',newline='') as f:
        elements={r['Element ID']:r for r in csv.DictReader(f)}
    definitions={key:{'id':'onet-element:'+item['element_id'],'kind':'element',
                 'element_id':item['element_id'],'text':elements[item['element_id']]['Description'],
                 'name':item['name'],'url':'https://www.onetcenter.org/content.html'}
                 for key,item in official['questionnaire_fields'].items()}
    targets={key:{'id':'un-target:'+key,'kind':'target','target_id':key,'goal':key.split('.')[0],
                 'text':text,'url':'https://sdgs.un.org/goals/goal'+key.split('.')[0],
                 'checked_on':'2026-10-23'} for key,text in TARGETS.items()}
    return {'version':'official-context-v1','checked_on':'2026-10-23','database_version':'31.0',
            'task_source':{'url':'https://www.onetcenter.org/dl_files/database/db_31_0_csv/task_statements.csv',
                           'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'total_rows':len(rows)},
            'element_source':official['sources']['content_model_reference'],
            'license':official['license'],'roles':roles,'elements':definitions,'targets':targets}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks',type=Path,required=True);parser.add_argument('--elements',type=Path,required=True)
    args=parser.parse_args();data=extract(args.tasks,args.elements)
    (ROOT/'data/sdg_context.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('Extracted official task context for',len(data['roles']),'careers; target definitions:',len(data['targets']))
