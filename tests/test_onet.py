"""Offline official-data extraction and mixed-source application tests."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app import ROOT, load_app_data, load_demo, profile_from_edits
from scripts.prepare_onet import (
    FILES, SCALES, build_dataset, extract_rating, normalized_value,
    questionnaire_mapping, read_sources,
)
from src.scoring import rank_roles


def sample_row(scale: str, value: object, **flags: str) -> dict:
    """Build an explicitly test-only CSV record for isolated converter checks."""
    raw = {'O*NET-SOC Code': 'test-code', 'Element ID': 'test-element',
           'Scale ID': scale, 'Data Value': value,
           'Recommend Suppress': 'N', 'Not Relevant': 'N'}
    raw.update(flags)
    return {'row_number': 2, 'raw': raw}


def reconstructed_tables(dataset: dict) -> dict:
    """Reconstruct only selected source records, without depending on /tmp CSVs."""
    tables = {name: [] for name in FILES}
    for role in dataset['roles']:
        tables['occupation_data'].append(deepcopy(role['identity_source']))
        for group in ('skills', 'knowledge'):
            for item in role[group].values():
                for rating in item['sources'].values():
                    tables[rating['file']].extend(deepcopy(rating['source_rows']))
        for rating in role['riasec_sources']:
            tables['career_interest_types'].extend(deepcopy(rating['source_rows']))
    tables['content_model_reference'] = [{'row_number': i + 2, 'raw': {
        'Element ID': item['element_id'], 'Element Name': item['name']}}
        for i, item in enumerate(dataset['questionnaire_fields'].values())]
    tables['scales_reference'] = [{'row_number': i + 2, 'raw': {
        'Scale ID': scale, 'Minimum': str(low), 'Maximum': str(high)}}
        for i, (scale, (low, high)) in enumerate(SCALES.items())]
    return tables


class OnetConversionTests(unittest.TestCase):
    """Check explicit conversions, quality exclusions and artifact reproducibility."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the small committed extract; no network or full CSVs needed."""
        cls.dataset = json.loads((ROOT / 'data/onet_roles.json').read_text())

    def test_distinct_scale_conversions(self) -> None:
        """Official values use official bounds, not the user response normalizer."""
        self.assertEqual(normalized_value('3', 'IM'), (.5, []))
        self.assertEqual(normalized_value('3.5', 'LV'), (.5, []))
        self.assertEqual(normalized_value('4', 'OI'), (.5, []))
        self.assertEqual(normalized_value('1', 'IM'), (0, []))
        self.assertEqual(normalized_value('7', 'LV'), (1, []))
        for scale in SCALES:
            for value in (None, '', 'NaN', 'inf', -1, 8, True):
                converted, reasons = normalized_value(value, scale)
                self.assertIsNone(converted)
                self.assertTrue(reasons)

    def test_quality_flags_keep_raw_and_block_scoring(self) -> None:
        """Suppressed and irrelevant values retain evidence but never become requirements."""
        for flags in ({'Recommend Suppress':'Y'}, {'Not Relevant':'Y'}, {'Recommend Suppress':''}):
            result = extract_rating([sample_row('LV', '3.5', **flags)],
                                    'test-code', 'test-element', 'LV', 'test')
            self.assertIsNone(result['value'])
            self.assertEqual(result['normalized_raw'], .5)
            self.assertEqual(result['source_rows'][0]['raw']['Data Value'], '3.5')
            self.assertTrue(result['issues'])
        # IM has no relevance flag in the real file; don't fabricate N.
        im = extract_rating([sample_row('IM', '3', **{'Not Relevant':''})],
                            'test-code', 'test-element', 'IM', 'test')
        self.assertEqual(im['value'], .5)
        self.assertEqual(im['source_rows'][0]['raw']['Not Relevant'], '')

    def test_missing_duplicate_and_zero_are_different(self) -> None:
        """Missing and conflicting records are null; an explicit valid zero remains zero."""
        row = sample_row('LV', '0')
        for rows in ([], [row, row]):
            result = extract_rating(rows, 'test-code', 'test-element', 'LV', 'test')
            self.assertIsNone(result['value'])
            self.assertTrue(result['issues'])
        self.assertEqual(extract_rating([row], 'test-code', 'test-element', 'LV', 'test')['value'], 0)

    def test_artifact_scope_and_provenance(self) -> None:
        """Only ten official roles and the exact 11/7/6 inputs are retained."""
        self.assertEqual(self.dataset['database_version'], '31.0')
        self.assertEqual(len(self.dataset['roles']), 10)
        self.assertEqual(len(self.dataset['questionnaire_fields']), 18)
        self.assertEqual(self.dataset['license']['name'], 'CC BY 4.0')
        for source in self.dataset['sources'].values():
            self.assertTrue(source['url'].startswith('https://www.onetcenter.org/'))
            self.assertEqual(len(source['sha256']), 64)
        for role in self.dataset['roles']:
            self.assertEqual(len(role['skills']), 11)
            self.assertEqual(len(role['knowledge']), 7)
            self.assertEqual(len(role['riasec']), 6)
            self.assertEqual(len(role['riasec_sources']), 6)
            self.assertTrue(all(r['scale_id'] == 'OI' for r in role['riasec_sources']))
            for group in ('skills', 'knowledge'):
                for item in role[group].values():
                    self.assertEqual(item['required'], item['sources']['LV']['value'])
                    self.assertEqual(item['importance'], item['sources']['IM']['value'])

    def test_rebuild_matches_committed_extract(self) -> None:
        """Regeneration from selected official records gives the identical artifact."""
        tables = reconstructed_tables(self.dataset)
        args = (tables, self.dataset['sources'], (ROOT / 'docs/CAREER_POOL.md').read_text(),
                (ROOT / 'docs/QUESTIONNAIRE.md').read_text())
        rebuilt = build_dataset(*args)
        self.assertEqual(rebuilt, self.dataset)
        self.assertEqual(build_dataset(*args), rebuilt)

    def test_missing_official_fields_preserve_shape_and_reasons(self) -> None:
        """Missing LV/OI records stay null and block scores, without dropping fields."""
        tables = reconstructed_tables(self.dataset)
        code = '17-2199.08'
        tables['essential_skills'] = [row for row in tables['essential_skills']
            if not (row['raw']['O*NET-SOC Code'] == code and
                    row['raw']['Element ID'] == '2.A.2.a' and row['raw']['Scale ID'] == 'LV')]
        tables['career_interest_types'] = [row for row in tables['career_interest_types']
            if not (row['raw']['O*NET-SOC Code'] == code and row['raw']['Element ID'] == '1.B.1.a')]
        result = build_dataset(tables, self.dataset['sources'],
                               (ROOT/'docs/CAREER_POOL.md').read_text(),
                               (ROOT/'docs/QUESTIONNAIRE.md').read_text())
        role = next(role for role in result['roles'] if role['code'] == code)
        self.assertEqual(len(role['skills']), 11)
        self.assertIsNone(role['skills']['skill_01']['required'])
        self.assertIsNone(role['riasec'][0])
        self.assertTrue(role['skills']['skill_01']['issues'])
        self.assertTrue(role['riasec_sources'][0]['issues'])

    def test_unmatched_questionnaire_name_not_substituted(self) -> None:
        """A similar-looking typo remains missing rather than matching approximately."""
        tables = reconstructed_tables(self.dataset)
        text = (ROOT / 'docs/QUESTIONNAIRE.md').read_text().replace(
            '| skill_01 | Critical Thinking |', '| skill_01 | Critical Thinkin |')
        mapping = questionnaire_mapping(text, tables)
        self.assertIsNone(mapping['skill_01']['element_id'])
        self.assertTrue(mapping['skill_01']['issues'])

    def test_scale_or_identity_mismatch_stops_build(self) -> None:
        """A different release's bounds or mismatched occupation title cannot slip through."""
        tables = reconstructed_tables(self.dataset)
        pool = (ROOT / 'docs/CAREER_POOL.md').read_text()
        questionnaire = (ROOT / 'docs/QUESTIONNAIRE.md').read_text()
        tables['scales_reference'][0]['raw']['Maximum'] = '7'
        with self.assertRaises(ValueError):
            build_dataset(tables, self.dataset['sources'], pool, questionnaire)
        tables = reconstructed_tables(self.dataset)
        tables['occupation_data'][0]['raw']['Title'] = 'Invented AI Role'
        with self.assertRaises(ValueError):
            build_dataset(tables, self.dataset['sources'], pool, questionnaire)

    def test_csv_reader_hashes_and_detects_truncation(self) -> None:
        """The actual reader uses csv and rejects truncated rows instead of inventing fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in FILES:
                with (root / (name + '.csv')).open('w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['field_a', 'field_b'])
                    writer.writerow(['a', 'b'])
            tables, sources = read_sources(root, '2026-10-21')
            self.assertEqual(tables['knowledge'][0]['row_number'], 2)
            self.assertEqual(sources['knowledge']['sha256'], hashlib.sha256((root/'knowledge.csv').read_bytes()).hexdigest())
            (root/'knowledge.csv').write_text('field_a,field_b\nonly_one\n')
            with self.assertRaises(ValueError):
                read_sources(root, '2026-10-21')


class OnetAppTests(unittest.TestCase):
    """Check the actual loader, quality gates and unchanged score integration."""

    def test_official_requirements_replace_only_role_data(self) -> None:
        """Original profile/trends stay synthetic; seven topic mappings stay missing."""
        original, demo_roles, demo_trends = load_demo()
        profile, official, trends = load_app_data()
        self.assertEqual(trends, demo_trends)
        for group in ('skills', 'knowledge'):
            for key, value in original[group].items():
                self.assertEqual(profile[group][key], value)
        self.assertEqual(len(profile['skills']), 11)
        self.assertEqual(len(profile['knowledge']), 7)
        self.assertIsNone(profile['skills']['skill_02'])
        self.assertEqual(sum(not role['topics'] for role in official['roles']), 7)
        ds = next(role for role in official['roles'] if role['code'] == '15-2051.00')
        self.assertEqual(ds['topics'], demo_roles['roles'][0]['topics'])
        self.assertIsNone(ds['skills']['skill_04']['required'])  # suppressed LV
        self.assertEqual(ds['skills']['skill_01']['importance'],
                         (float(ds['skills']['skill_01']['sources']['IM']['source_rows'][0]['raw']['Data Value'])-1)/4)

    def test_missing_profile_and_official_quality_block_ranking(self) -> None:
        """Engine preserves available scores without fabricating missing requirements or trends."""
        profile, official, trends = load_app_data()
        rows = rank_roles(profile, official['roles'], trends['topics'])
        self.assertTrue(all(row['moderate_rank'] is None for row in rows))
        self.assertTrue(all(row['I'].value is not None for row in rows))
        complete = profile_from_edits(profile, {key:3 for key in profile['skills']},
                                      {key:3 for key in profile['knowledge']}, profile['riasec'])
        scored = rank_roles(complete, official['roles'], trends['topics'])
        self.assertEqual(scored, rank_roles(complete, official['roles'], trends['topics']))
        ds = next(row for row in scored if row['code'] == '15-2051.00')
        self.assertIsNone(ds['skills']['score'].value)
        self.assertIsNotNone(ds['trend']['score'].value)
        bio = next(row for row in scored if row['code'] == '19-1029.01')
        self.assertIsNotNone(bio['knowledge']['score'].value)
        self.assertIsNone(bio['trend']['score'].value)

    def test_loader_does_not_modify_files(self) -> None:
        """Loading and editing a session leave every stored data file unchanged."""
        files = list((ROOT/'data').glob('*.json'))
        before = {p:p.read_bytes() for p in files}
        profile, official, trends = load_app_data()
        rank_roles(profile, official['roles'], trends['topics'])
        self.assertEqual(before, {p:p.read_bytes() for p in files})
