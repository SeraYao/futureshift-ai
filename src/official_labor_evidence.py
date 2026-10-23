"""Versioned BLS occupational-projection evidence and O*NET-SOC mapping.

This module keeps official employment projections separate from personal-fit scoring.
The bundled snapshot is an extract of rows read from the official BLS HTML table;
manual refresh parses the same published table and official O*NET crosswalk page.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from math import isfinite
from pathlib import Path
import re
from typing import Callable
from urllib.request import Request, urlopen

BLS_TABLE_URL = 'https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm'
BLS_XLSX_URL = 'https://www.bls.gov/emp/ind-occ-matrix/occupation.xlsx'
BLS_FAQ_URL = 'https://www.bls.gov/emp/frequently-asked-questions.htm'
ONET_CROSSWALK_URL = 'https://www.onetcenter.org/taxonomy/2019/soc.html'
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / 'data' / 'official_labor_evidence.json'

CAREERS = {
    '13-1199.05': {'title': 'Sustainability Specialists', 'mapping': 'aggregate'},
    '15-1212.00': {'title': 'Information Security Analysts', 'mapping': 'exact'},
    '15-2031.00': {'title': 'Operations Research Analysts', 'mapping': 'exact'},
    '17-2081.00': {'title': 'Environmental Engineers', 'mapping': 'exact'},
    '17-2199.03': {'title': 'Energy Engineers, Except Wind and Solar', 'mapping': 'aggregate'},
    '17-2199.08': {'title': 'Robotics Engineers', 'mapping': 'aggregate'},
}
EXPECTED_SOC = {
    '13-1199.05': '13-1199', '15-1212.00': '15-1212',
    '15-2031.00': '15-2031', '17-2081.00': '17-2081',
    '17-2199.03': '17-2199', '17-2199.08': '17-2199',
}


class _Rows(HTMLParser):
    """Small stdlib-only HTML table reader for published source pages."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row.append(' '.join(' '.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def _html_rows(body: bytes | str) -> list[list[str]]:
    parser = _Rows()
    parser.feed(body.decode('utf-8', errors='replace') if isinstance(body, bytes) else body)
    return parser.rows


def _number(value: str) -> float | None:
    value = value.strip().replace(',', '')
    if value in ('', '—', '-', 'N/A'):
        return None
    return float(value)


def parse_bls_table(body: bytes | str) -> dict[str, dict]:
    """Parse the current BLS table 1.2 rows, keyed by SOC code."""
    parsed = {}
    for row in _html_rows(body):
        if len(row) < 12 or not re.fullmatch(r'\d{2}-\d{4}', row[1].strip()):
            continue
        code = row[1].strip()
        parsed[code] = {
            'title': row[0], 'soc_code': code, 'occupation_type': row[2],
            'employment_start_thousands': _number(row[3]),
            'employment_target_thousands': _number(row[4]),
            'employment_change_thousands': _number(row[7]),
            'employment_change_percent': _number(row[8]),
            'annual_openings_thousands': _number(row[10]),
        }
    return parsed


def parse_onet_crosswalk(body: bytes | str) -> dict[str, dict]:
    """Parse O*NET-SOC 2019 -> 2018 SOC entries from the official listing."""
    mappings = {}
    for row in _html_rows(body):
        if len(row) < 4 or not re.fullmatch(r'\d{2}-\d{4}\.\d{2}', row[0].strip()):
            continue
        mappings[row[0].strip()] = {
            'onet_title': row[1], 'soc_code': row[2].strip(), 'soc_title': row[3],
        }
    return mappings


def parse_release_metadata(body: bytes | str) -> tuple[str, str]:
    text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else body
    clean = ' '.join(_RowsText().extract(text).split())
    match = re.search(
        r'most recent projections are for\s+(\d{4})[–-](\d{2,4}).{0,180}?released.{0,100}?on\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})',
        clean, re.I)
    if not match:
        raise ValueError('Could not verify current BLS projection period and release date')
    end = match.group(2) if len(match.group(2)) == 4 else match.group(1)[:2] + match.group(2)
    release = datetime.strptime(match.group(3), '%B %d, %Y').date().isoformat()
    return f'{match.group(1)}-{end}', release


class _RowsText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def extract(self, body):
        self.feed(body)
        return ' '.join(self.parts)


def _fetch(url: str, timeout: int = 20) -> bytes:
    request = Request(url, headers={'User-Agent': 'FutureShift public labor evidence updater'})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f'Official source returned HTTP {response.status}')
        data = response.read(15_000_001)
    if len(data) > 15_000_000:
        raise ValueError('Official source exceeded the 15 MB safety limit')
    return data


def build_snapshot(table_html: bytes | str, crosswalk_html: bytes | str,
                   faq_html: bytes | str, retrieved_at: str | None = None) -> dict:
    rows = parse_bls_table(table_html)
    crosswalk = parse_onet_crosswalk(crosswalk_html)
    period, release_date = parse_release_metadata(faq_html)
    base_year, target_year = (int(part) for part in period.split('-'))
    if target_year - base_year != 10:
        raise ValueError(f'Unexpected BLS projection span {period}')
    mappings = {}
    for code, career in CAREERS.items():
        mapping = crosswalk.get(code)
        if not mapping:
            raise ValueError(f'Missing official O*NET-SOC mapping for {code}')
        record = rows.get(mapping['soc_code'])
        if not record:
            raise ValueError(f'Missing BLS SOC row {mapping["soc_code"]} for {code}')
        if record['title'].casefold() != mapping['soc_title'].casefold():
            raise ValueError(f'BLS and O*NET SOC titles disagree for {code}')
        mappings[code] = {
            **career, **mapping, 'mapping_precision': career['mapping'],
            'projection': record,
        }
    return {
        'schema_version': 1,
        'dataset': 'BLS Occupational Projections Table 1.2',
        'source_url': BLS_TABLE_URL,
        'download_url': BLS_XLSX_URL,
        'release_date': release_date,
        'period': period,
        'base_year': base_year,
        'target_year': target_year,
        'geography': 'United States',
        'metric': 'Employment change, percent (projected)',
        'unit': 'employment in thousands; change is percent',
        'access_method': 'official_html_table_extract',
        'retrieved_at': retrieved_at or datetime.now(timezone.utc).isoformat(),
        'crosswalk': {
            'name': 'O*NET-SOC 2019 to 2018 SOC', 'source_url': ONET_CROSSWALK_URL,
            'version': 'O*NET-SOC 2019 / SOC 2018',
        },
        'careers': mappings,
    }


def validate_snapshot(snapshot: dict) -> None:
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 1:
        raise ValueError('Unsupported official labor evidence snapshot')
    if (not re.fullmatch(r'\d{4}-\d{4}', snapshot.get('period', ''))
            or type(snapshot.get('target_year')) is not int
            or type(snapshot.get('base_year')) is not int
            or snapshot.get('target_year', 0) - snapshot.get('base_year', 0) != 10
            or snapshot.get('geography') != 'United States'):
        raise ValueError('Projection period or geography is invalid')
    period_years = tuple(int(year) for year in snapshot['period'].split('-'))
    if period_years != (snapshot['base_year'], snapshot['target_year']):
        raise ValueError('Projection year metadata does not match the period')
    for field in ('release_date', 'retrieved_at', 'source_url', 'metric', 'unit'):
        if not isinstance(snapshot.get(field), str) or not snapshot[field].strip():
            raise ValueError(f'Missing snapshot metadata: {field}')
    for field in ('source_url', 'download_url'):
        if not str(snapshot.get(field, '')).startswith('https://'):
            raise ValueError(f'Invalid official source URL: {field}')
    datetime.fromisoformat(snapshot['retrieved_at'].replace('Z', '+00:00'))
    if not str(snapshot.get('crosswalk', {}).get('source_url', '')).startswith('https://'):
        raise ValueError('Missing official occupational crosswalk source')
    if set(snapshot.get('careers', {})) != set(CAREERS):
        raise ValueError('Snapshot must contain mappings for all six displayed careers')
    for code, expected in CAREERS.items():
        entry = snapshot['careers'][code]
        if entry.get('mapping_precision') != expected['mapping']:
            raise ValueError(f'Unexpected mapping precision for {code}')
        if entry.get('soc_code') != EXPECTED_SOC[code]:
            raise ValueError(f'Unexpected official SOC mapping for {code}')
        proj = entry.get('projection', {})
        if proj.get('soc_code') != entry.get('soc_code'):
            raise ValueError(f'Career/SOC mapping mismatch for {code}')
        if not isinstance(proj.get('employment_change_percent'), (int, float)):
            raise ValueError(f'Missing projection value for {code}')
        if isinstance(proj.get('employment_change_percent'), bool) or not isfinite(proj['employment_change_percent']):
            raise ValueError(f'Invalid projection value for {code}')
        for field in ('employment_start_thousands', 'employment_target_thousands',
                      'employment_change_thousands', 'annual_openings_thousands'):
            if type(proj.get(field)) not in (int, float) or not isfinite(proj[field]):
                raise ValueError(f'Missing projection field {field} for {code}')


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict:
    snapshot = json.loads(path.read_text(encoding='utf-8'))
    validate_snapshot(snapshot)
    return snapshot


def refresh_snapshot(path: Path = SNAPSHOT_PATH, *, fetch: Callable[[str], bytes] = _fetch,
                     retrieved_at: str | None = None) -> dict:
    """Fetch, parse, validate, then atomically replace. Any failure leaves old data intact."""
    candidate = build_snapshot(fetch(BLS_TABLE_URL), fetch(ONET_CROSSWALK_URL),
                               fetch(BLS_FAQ_URL), retrieved_at=retrieved_at)
    validate_snapshot(candidate)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return candidate


def exact_comparison(rows: list[dict], snapshot: dict, sensitivity_weight: float = 0.40) -> list[dict]:
    """Compute the single 80/20 Result plus a separate 40%-weight sensitivity test."""
    validate_snapshot(snapshot)
    if not 0 <= sensitivity_weight <= 1:
        raise ValueError('Sensitivity weight must be between 0 and 1')
    exact = [row for row in rows if row['code'] in snapshot['careers']
             and snapshot['careers'][row['code']]['mapping_precision'] == 'exact'
             and row['P'].value is not None]
    if len(exact) != 3:
        raise ValueError('Comparison requires all three exact-match occupations with personal-fit scores')
    raw = {row['code']: snapshot['careers'][row['code']]['projection']['employment_change_percent']
           for row in exact}
    low, high = min(raw.values()), max(raw.values())
    normalized = {code: (50.0 if high == low else 100.0 * (value-low)/(high-low))
                  for code, value in raw.items()}
    output = []
    for row in exact:
        code, personal, trend = row['code'], row['P'].value, normalized[row['code']]
        result_weight = 0.20
        output.append({
            'code': code, 'personal_fit': personal, 'projection_percent': raw[code],
            'normalized_projection': trend,
            'result': {
                'weight': result_weight,
                'personal_contribution': (1-result_weight)*personal,
                'projection_contribution': result_weight*trend,
                'combined': (1-result_weight)*personal + result_weight*trend,
            },
            'sensitivity': {
                'weight': sensitivity_weight,
                'personal_contribution': (1-sensitivity_weight)*personal,
                'projection_contribution': sensitivity_weight*trend,
                'combined': (1-sensitivity_weight)*personal + sensitivity_weight*trend,
            },
        })
    for cohort in ('result', 'sensitivity'):
        ordered = sorted(output, key=lambda item: (-item[cohort]['combined'], item['code']))
        for rank, item in enumerate(ordered, 1):
            item[cohort]['rank'] = rank
    result_ranks = {item['code']:item['result']['rank'] for item in output}
    for item in output:
        item['sensitivity']['rank_change'] = (
            result_ranks[item['code']] - item['sensitivity']['rank']
        )
    return sorted(output, key=lambda item: item['code'])
