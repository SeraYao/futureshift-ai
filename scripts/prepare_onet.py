"""Extract O*NET 31.0 offline with csv; never download or impute values.

Run from the repository: python3 scripts/prepare_onet.py --raw-dir /tmp
--accessed-on 2026-10-21. Accepts official filenames or the previously downloaded
futureshift-onet-<name>.csv. All questionnaire items are retained; no unreviewed
core subset is silently selected to avoid quality flags.
"""
import argparse
import csv
from datetime import date
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = 'https://www.onetcenter.org/dl_files/database/db_31_0_csv/'
FILES = ('essential_skills', 'transferable_skills', 'knowledge',
         'career_interest_types', 'occupation_data', 'scales_reference',
         'content_model_reference')
SCALES = {'IM': (1.0, 5.0), 'LV': (0.0, 7.0), 'OI': (1.0, 7.0)}
RIASEC_IDS = ('1.B.1.a', '1.B.1.b', '1.B.1.c', '1.B.1.d', '1.B.1.e', '1.B.1.f')


def normalized_value(raw: object, scale: str) -> tuple[float | None, list[str]]:
    """Apply official scale bounds, rejecting missing, nonfinite or out-of-range values."""
    low, high = SCALES[scale]
    try:
        if raw is None or isinstance(raw, bool):
            raise ValueError
        value = float(raw)
        if not isfinite(value) or not low <= value <= high:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        return None, [f'{scale}: missing, invalid or out-of-range Data Value']
    return (value - low) / (high - low), []


def read_sources(raw_dir: Path, accessed_on: str) -> tuple[dict, dict]:
    """Read local official CSVs and retain reproducible hashes and line numbers."""
    date.fromisoformat(accessed_on)
    tables, sources = {}, {}
    for name in FILES:
        path = raw_dir / (name + '.csv')
        if not path.exists():
            path = raw_dir / ('futureshift-onet-' + name + '.csv')
        contents = path.read_bytes()
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            rows = []
            for number, raw in enumerate(reader, 2):
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError(f'{name}: malformed/truncated CSV record {number}')
                rows.append({'row_number': number, 'raw': raw})
        tables[name] = rows
        sources[name] = {'url': BASE_URL + name + '.csv', 'accessed_on': accessed_on,
                         'bytes': len(contents), 'sha256': hashlib.sha256(contents).hexdigest()}
    return tables, sources


def questionnaire_mapping(text: str, tables: dict) -> dict[str, dict]:
    """Match exact questionnaire names in their own domain; never use fuzzy aliases."""
    fields = re.findall(r'^\| ((?:skill|knowledge)_\d+) \| ([^|]+) \|', text, re.M)
    if (len(fields) != 18 or len({key for key, _ in fields}) != 18
            or sum(key.startswith('skill_') for key, _ in fields) != 11
            or sum(key.startswith('knowledge_') for key, _ in fields) != 7):
        raise ValueError('Expected 11 unique skill and 7 knowledge questionnaire fields')
    mapping = {}
    for key, label in fields:
        domain = ('knowledge',) if key.startswith('knowledge') else ('essential_skills', 'transferable_skills')
        matches = {(name, row['raw']['Element ID']) for name in domain for row in tables[name]
                   if row['raw']['Element Name'] == label.strip()}
        issues = []
        source, element = None, None
        if len(matches) == 1:
            source, element = next(iter(matches))
            if not any(row['raw']['Element ID'] == element and
                       row['raw']['Element Name'] == label.strip()
                       for row in tables['content_model_reference']):
                issues.append('Element ID/name not confirmed in Content Model Reference')
        else:
            issues.append('No unique exact Element ID match; no approximate substitution')
        mapping[key] = {'name': label.strip(), 'file': source, 'element_id': element, 'issues': issues}
    return mapping


def extract_rating(rows: list[dict], code: str, element: str | None,
                   scale: str, filename: str) -> dict[str, Any]:
    """Keep raw rows but block missing, duplicate and flagged ratings from scoring."""
    matches = [row for row in rows if row['raw']['O*NET-SOC Code'] == code
               and row['raw']['Element ID'] == element and row['raw']['Scale ID'] == scale]
    result: dict[str, Any] = {'file': filename, 'element_id': element, 'scale_id': scale,
                              'source_rows': matches, 'normalized_raw': None,
                              'value': None, 'issues': []}
    if len(matches) != 1:
        result['issues'] = [f'{code}/{element}/{scale}: expected one row, found {len(matches)}']
        return result
    raw = matches[0]['raw']
    value, issues = normalized_value(raw.get('Data Value'), scale)
    result['normalized_raw'] = value
    if scale in ('IM', 'LV'):
        # Optional precision statistics are not supplied for official expert knowledge ratings.
        # Preserve the blank flag; never reinterpret it as N or accept an explicit Y.
        expert_optional = (filename == 'knowledge' and raw.get('Domain Source') == 'Occupational Expert'
                           and raw.get('Recommend Suppress') == ''
                           and raw.get('N', '').isdigit() and int(raw['N']) >= 10)
        if raw.get('Recommend Suppress') != 'N' and not expert_optional:
            issues.append(f"Recommend Suppress={raw.get('Recommend Suppress') or 'unknown'}")
        # IM rows normally have an empty Not Relevant field: preserve it as
        # not supplied, not a guessed N. LV must explicitly establish relevance.
        if raw.get('Not Relevant') == 'Y':
            issues.append('Not Relevant=Y')
        elif scale == 'LV' and raw.get('Not Relevant') != 'N':
            issues.append('LV relevance unknown')
    result['issues'] = issues
    result['value'] = value if not issues else None
    return result


def build_dataset(tables: dict, sources: dict, pool_text: str,
                  questionnaire_text: str) -> dict:
    """Build only the fixed ten roles and eighteen exact capability elements."""
    for scale, bounds in SCALES.items():
        matches = [r['raw'] for r in tables['scales_reference'] if r['raw']['Scale ID'] == scale]
        if len(matches) != 1 or (float(matches[0]['Minimum']), float(matches[0]['Maximum'])) != bounds:
            raise ValueError(f'Unexpected official scale bounds: {scale}')
    identities = re.findall(r'^\| (\d{2}-\d{4}\.\d{2}) \| ([^|]+) \|', pool_text, re.M)
    if len(identities) != 10 or len({code for code, _ in identities}) != 10:
        raise ValueError('Expected ten unique CAREER_POOL occupations')
    mapping = questionnaire_mapping(questionnaire_text, tables)
    roles = []
    for code, title in sorted(identities):
        title = title.strip()
        matches = [r for r in tables['occupation_data'] if r['raw']['O*NET-SOC Code'] == code]
        if len(matches) != 1 or matches[0]['raw']['Title'] != title:
            raise ValueError(f'Official occupation code/title mismatch: {code} {title}')
        role: dict[str, Any] = {'code': code, 'title': title, 'data_status': 'official_derived',
                               'identity_source_url': 'https://www.onetonline.org/link/summary/' + code,
                               'identity_source': matches[0], 'skills': {}, 'knowledge': {},
                               'riasec': [], 'riasec_sources': [], 'data_issues': []}
        for key, item in mapping.items():
            filename = item['file']
            ratings = {scale: extract_rating(tables.get(filename, []), code, item['element_id'], scale, filename)
                       for scale in ('IM', 'LV')}
            issues = item['issues'] + [f'{scale}: {issue}' for scale in ratings for issue in ratings[scale]['issues']]
            value = {'element_id': item['element_id'], 'name': item['name'],
                     'importance': ratings['IM']['value'], 'required': ratings['LV']['value'],
                     'sources': ratings, 'issues': issues}
            if item['issues']:
                value.update(importance=None, required=None)
            group = 'knowledge' if key.startswith('knowledge') else 'skills'
            role[group][key] = value
            role['data_issues'].extend(f'{key} ({item["name"]}): {issue}' for issue in issues)
        for element in RIASEC_IDS:
            rating = extract_rating(tables['career_interest_types'], code, element, 'OI', 'career_interest_types')
            role['riasec'].append(rating['value'])
            role['riasec_sources'].append(rating)
            role['data_issues'].extend(f'{element}: {issue}' for issue in rating['issues'])
        roles.append(role)
    return {'schema_version': 1, 'data_status': 'official_derived', 'database_version': '31.0',
            'released': '2026-08', 'accessed_on': sources['occupation_data']['accessed_on'],
            'database_url': 'https://www.onetcenter.org/database.html',
            'license': {'name': 'CC BY 4.0', 'url': 'https://creativecommons.org/licenses/by/4.0/',
                        'official_notice_url': 'https://www.onetcenter.org/license_db.html',
                        'attribution': 'O*NET® 31.0 Database, U.S. Department of Labor, Employment and Training Administration (USDOL/ETA). O*NET® is a trademark of USDOL/ETA.',
                        'modifications': 'FutureShift AI selected occupations and questionnaire elements, normalized ratings and blocked flagged or unavailable values. USDOL/ETA has not approved, endorsed, or tested these modifications.'},
            'transformations': {'version': 'onet31-v2', 'user': 'response / 4 (questionnaire only)',
                                'importance': '(IM - 1) / 4', 'required': 'LV / 7', 'riasec': '(OI - 1) / 6',
                                'caution': 'Different measurement systems: normalization is not validity calibration. U.S. occupational requirements are not Malaysian employment forecasts.',
                                'quality_policy': 'Retain all 11 skills and 7 knowledge items. Missing/duplicate/flagged/out-of-range values are null with reasons, not zero; no automatic core-subset exclusions. Optional blank precision flags on Knowledge Occupational Expert rows with N>=10 are preserved as not supplied, not N; explicit suppression still blocks. IM Not Relevant blanks are not supplied (preserved), while LV requires explicit N. No imputation or reweighting.'},
            'selection': {'career_pool_sha256': hashlib.sha256(pool_text.encode()).hexdigest(),
                          'questionnaire_sha256': hashlib.sha256(questionnaire_text.encode()).hexdigest()},
            'sources': sources, 'questionnaire_fields': mapping, 'roles': roles}


def main() -> None:
    """Regenerate a stable, reviewable artifact without retaining full CSVs in Git."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=Path('/tmp'))
    parser.add_argument('--accessed-on', required=True, help='Actual official download date, YYYY-MM-DD')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/onet_roles.json')
    args = parser.parse_args()
    tables, sources = read_sources(args.raw_dir, args.accessed_on)
    dataset = build_dataset(tables, sources, (ROOT / 'docs/CAREER_POOL.md').read_text(),
                            (ROOT / 'docs/QUESTIONNAIRE.md').read_text())
    args.output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Wrote {len(dataset["roles"])} official-derived roles to {args.output}')


if __name__ == '__main__':
    main()
