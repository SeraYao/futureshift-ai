"""Test local UI data integration without requiring Streamlit or network access."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest

from app import display_score, fingerprint, load_demo, profile_from_edits
from src.scoring import Score, rank_roles


class AppIntegrationTests(unittest.TestCase):
    """Verify that edits flow through the actual scoring interface safely."""

    def test_fixture_loading_and_trace_serialization(self) -> None:
        """Actual demo data produces three explainable, serializable matches."""
        profile, roles, trends = load_demo()
        results = rank_roles(profile, roles['roles'], trends['topics'])
        self.assertEqual(len(results), 3)
        self.assertTrue(all(row['moderate_rank'] is not None for row in results))
        trace = json.loads(json.dumps(results, default=asdict))
        self.assertIn('snapshot', trace[0]['trend']['topics'][0])
        self.assertIn('gap', trace[0]['skills']['gaps'][0])

    def test_edits_change_scores_without_mutating_data(self) -> None:
        """Confirming higher ability updates scores while leaving original JSON objects intact."""
        profile, roles, trends = load_demo()
        original = deepcopy((profile, roles, trends))
        edited = profile_from_edits(profile, {key:4 for key in profile['skills']},
                                    {key:4 for key in profile['knowledge']}, profile['riasec'])
        before = rank_roles(profile, roles['roles'], trends['topics'])
        after = rank_roles(edited, roles['roles'], trends['topics'])
        before_by_code = {row['code']:row['P'].value for row in before}
        self.assertTrue(all(row['P'].value > before_by_code[row['code']] for row in after))
        self.assertEqual((profile, roles, trends), original)
        self.assertNotEqual(fingerprint(profile), fingerprint(edited))

    def test_zero_interests_remain_explicitly_unavailable(self) -> None:
        """The UI integration keeps zero-vector failures instead of showing zero matches."""
        profile, roles, trends = load_demo()
        edited = profile_from_edits(profile, profile['skills'], profile['knowledge'], [0.0]*6)
        rows = rank_roles(edited, roles['roles'], trends['topics'])
        self.assertTrue(all(row['moderate_rank'] is None for row in rows))
        self.assertTrue(all('RIASEC zero vector' in row['moderate'].issues for row in rows))
        self.assertEqual(display_score(Score(None)), 'Unavailable')
        self.assertEqual(display_score(Score(0)), '0.00')

    def test_fingerprint_ignores_mapping_insertion_order(self) -> None:
        """Equivalent confirmed inputs have the same identifier."""
        self.assertEqual(fingerprint({'a':1,'b':2}), fingerprint({'b':2,'a':1}))
