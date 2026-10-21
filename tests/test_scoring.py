"""Formula, failure-mode and synthetic integration checks; no network access."""
import copy
import json
from pathlib import Path
import unittest

from src.scoring import (
    Score, normalize_0_4, skill_coverage, knowledge_coverage,
    calculate_gaps, capability_breakdown, riasec_similarity, capability_score,
    personal_fit, github_trend, role_trend, match_score, rank_roles,
    MODERATE_LAMBDA, FAST_LAMBDA,
)


class ScoringTests(unittest.TestCase):
    """Check calculations against independent expected values and invariants."""

    def setUp(self) -> None:
        """Load explicitly synthetic fixtures relative to the repository."""
        root = Path(__file__).resolve().parents[1] / 'data'
        self.profile = json.loads((root / 'demo_profile.json').read_text())
        self.roles = json.loads((root / 'demo_roles.json').read_text())['roles']
        self.trends = json.loads((root / 'demo_trends.json').read_text())['topics']

    def test_normalization(self) -> None:
        """Questionnaire bounds are preserved; invalid inputs are not clamped."""
        self.assertEqual([normalize_0_4(n).value for n in range(5)], [0,.25,.5,.75,1])
        for value in (None, -1, 5, 2.5, True, '2', float('nan'), float('inf')):
            self.assertIsNone(normalize_0_4(value).value)

    def test_coverage_cap_and_zero_requirement(self) -> None:
        """Excess capability cannot offset a separate gap; zero requirements drop out."""
        req = {'a':{'required':.25,'importance':1},'b':{'required':1,'importance':1},
               'z':{'required':0,'importance':1}}
        self.assertEqual(skill_coverage({'a':4,'b':2},req).value,75)
        capped = capability_breakdown({'a':4,'b':4},req)
        self.assertEqual(capped['score'].value,100)
        self.assertEqual(capped['items'][0]['coverage'],1)
        self.assertFalse(capped['items'][2]['included'])
        self.assertEqual(knowledge_coverage({'a':4,'b':2},req).value,75)

    def test_gaps_and_ties(self) -> None:
        """Weighted severity and stable IDs control gap order."""
        req = {'b':{'required':.5,'importance':1},'a':{'required':1,'importance':.5},
               'c':{'required':1,'importance':1}}
        result = calculate_gaps({'a':0,'b':0,'c':0},req)
        self.assertEqual([(g['id'],g['gap']) for g in result['gaps']], [('c',1),('a',.5),('b',.5)])

    def test_missing_and_zero_weights(self) -> None:
        """Unavailable data never produces fabricated zero scores."""
        for req in ({}, {'a':{'required':1,'importance':0}}, {'a':{'required':0,'importance':1}},
                    {'a':{'importance':1}}, {'a':{'required':1,'importance':1}}):
            result = skill_coverage({},req)
            self.assertIsNone(result.value)
            self.assertTrue(result.issues)
        self.assertIsNone(role_trend({}, {})['score'].value)
        self.assertIsNone(role_trend({'missing':1}, {})['score'].value)
        self.assertIsNone(role_trend({'a':0}, {'a':{'recent':1,'previous':1}})['score'].value)

    def test_riasec(self) -> None:
        """Cosine similarity has known identity/orthogonal and failure cases."""
        self.assertEqual(riasec_similarity([1,0,0,0,0,0],[1,0,0,0,0,0]).value,100)
        self.assertEqual(riasec_similarity([1,0,0,0,0,0],[0,1,0,0,0,0]).value,0)
        for user in ([0]*6, [], [None]*6, [-1]*6):
            result = riasec_similarity(user,[1]*6)
            self.assertIsNone(result.value)
            self.assertTrue(result.issues)

    def test_fixed_formulas(self) -> None:
        """Check composite weights against independently calculated expected values."""
        capability = capability_score(Score(80),Score(40))
        self.assertEqual(capability.value,70)
        personal = personal_fit(capability,Score(50))
        self.assertEqual(personal.value,64)
        self.assertAlmostEqual(match_score(personal,Score(80),.15).value,66.4)
        self.assertIsNone(capability_score(Score(None,('missing',)),Score(50)).value)

    def test_trend_direction_smoothing_and_clipping(self) -> None:
        """Equal windows are neutral, doubling smoothed counts saturates correctly."""
        self.assertEqual(github_trend(10,10).value,50)
        self.assertEqual(github_trend(0,0).value,50)
        self.assertEqual(github_trend(20,0).value,100)
        self.assertEqual(github_trend(0,20).value,0)
        self.assertGreater(github_trend(110,100).value,50)
        self.assertLess(github_trend(90,100).value,50)
        self.assertEqual(github_trend(10000,0).value,100)
        self.assertIsNone(github_trend(-1,0).value)
        self.assertIsNone(github_trend(None,0).value)
        aggregate = role_trend({'up':3,'down':1}, {'up':{'recent':20,'previous':0},'down':{'recent':0,'previous':20}})
        self.assertEqual(aggregate['score'].value,75)

    def test_scenarios_and_no_mutation(self) -> None:
        """Only lambda differs; profile, roles and snapshots stay unchanged."""
        original = copy.deepcopy((self.profile,self.roles,self.trends))
        for row in rank_roles(self.profile,self.roles,self.trends):
            p,t = row['P'].value,row['trend']['score'].value
            self.assertEqual(row['moderate'].value,(1-MODERATE_LAMBDA)*p+MODERATE_LAMBDA*t)
            self.assertEqual(row['fast'].value,(1-FAST_LAMBDA)*p+FAST_LAMBDA*t)
            self.assertAlmostEqual(row['score_delta'],.20*(t-p))
        self.assertEqual((self.profile,self.roles,self.trends),original)

    def test_trend_update_propagates(self) -> None:
        """Changing only a snapshot changes a role's trend and final score."""
        before = {r['code']:r for r in rank_roles(self.profile,self.roles,self.trends)}
        changed = copy.deepcopy(self.trends)
        changed['synthetic-data-science']['recent']=1000
        after = {r['code']:r for r in rank_roles(self.profile,self.roles,changed)}
        code='15-2051.00'
        self.assertNotEqual(before[code]['moderate'],after[code]['moderate'])
        self.assertNotEqual(before[code]['trend']['score'],after[code]['trend']['score'])
        self.assertEqual(before[code]['P'],after[code]['P'])

    def test_reproducibility_order_and_sdg_exclusion(self) -> None:
        """Repeated/reordered inputs and non-scoring preferences preserve results."""
        expected = rank_roles(self.profile,self.roles,self.trends)
        self.assertEqual(expected,rank_roles(self.profile,self.roles,self.trends))
        self.assertEqual(expected,rank_roles(self.profile,list(reversed(self.roles)),dict(reversed(list(self.trends.items())))))
        modified = dict(self.profile,sdgs=[1,4,8],field_of_study='Other')
        self.assertEqual(expected,rank_roles(modified,self.roles,self.trends))

    def test_incomplete_roles_unranked(self) -> None:
        """Missing interest or topic blocks total scores but preserves valid components."""
        roles=copy.deepcopy(self.roles)
        del roles[0]['riasec']
        roles[1]['topics']={'unknown':1}
        rows={r['code']:r for r in rank_roles(self.profile,roles,self.trends)}
        for role in roles[:2]:
            row=rows[role['code']]
            self.assertIsNone(row['moderate'].value)
            self.assertIsNone(row['moderate_rank'])
            self.assertIsNotNone(row['skills']['score'].value)
        self.assertEqual(rank_roles({},[],{}),[])

    def test_tie_break_and_duplicate_codes(self) -> None:
        """Exact ties resolve by code; duplicate identities are rejected."""
        a=copy.deepcopy(self.roles[0]); b=copy.deepcopy(a)
        b['code']='15-1252.00'; b['title']='Software Developers'
        rows=rank_roles(self.profile,[a,b],self.trends)
        self.assertEqual([r['code'] for r in rows],['15-1252.00','15-2051.00'])
        with self.assertRaises(ValueError):
            rank_roles(self.profile,[a,a],self.trends)


if __name__ == '__main__':
    unittest.main()
