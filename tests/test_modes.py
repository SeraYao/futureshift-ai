"""Data isolation, simulation sensitivity and visible audit evidence checks."""
from contextlib import nullcontext
from copy import deepcopy
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
from src.scoring import rank_roles


class RecordingUI:
    """Capture rendered evidence without Streamlit or any simulation session state."""

    def __init__(self) -> None:
        """Initialize a simple render log."""
        self.calls = []

    def __getattr__(self, method: str):
        """Record output; any audit access to session data is a test failure."""
        if method == 'session_state':
            raise AssertionError('Audit must not read simulation session state')

        def record(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            return nullcontext() if method == 'expander' else None
        return record


class ModeIsolationTests(unittest.TestCase):
    """Prove each mode works with only its permitted files present."""

    def test_synthetic_loader_requires_only_three_demo_files(self) -> None:
        """Official data can be completely absent in the simulation directory."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('demo_profile.json', 'demo_roles.json', 'demo_trends.json'):
                shutil.copyfile(app.ROOT/'data'/name, root/name)
            profile, roles, trends = app.load_demo(root)
            ranked = rank_roles(profile, roles['roles'], trends['topics'])
            self.assertEqual(len(ranked), 3)
            self.assertTrue(all(row['moderate_rank'] is not None for row in ranked))
            self.assertTrue(all(row['data_status'] == 'synthetic' for row in ranked))
            with self.assertRaises(FileNotFoundError):
                app.load_onet(root)

    def test_audit_loader_requires_only_official_file(self) -> None:
        """Missing or malformed synthetic data cannot affect the official loader."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(app.ROOT/'data/onet_roles.json', root/'onet_roles.json')
            official = app.load_onet(root)
            (root/'demo_trends.json').write_text('INVALID JSON MUST NOT BE READ')
            self.assertEqual(app.load_onet(root), official)
            self.assertEqual(len(official['roles']), 10)
            self.assertTrue(all('topics' not in role for role in official['roles']))
            with self.assertRaises(FileNotFoundError):
                app.load_demo(root)

    def test_editing_trends_changes_scores_without_changing_personal_fit(self) -> None:
        """Changing one synthetic count flows through the existing formula."""
        profile, roles, trends = app.load_demo()
        before = deepcopy(trends)
        changed = app.trends_from_edits(trends, {'synthetic-data-science': {'recent':2000, 'previous':90}})
        self.assertEqual(trends, before)
        self.assertTrue(changed['topics']['synthetic-data-science']['simulation_edited'])
        initial = {row['code']:row for row in rank_roles(profile, roles['roles'], trends['topics'])}
        updated = {row['code']:row for row in rank_roles(profile, roles['roles'], changed['topics'])}
        code = '15-2051.00'
        self.assertEqual(initial[code]['P'], updated[code]['P'])
        self.assertNotEqual(initial[code]['moderate'], updated[code]['moderate'])
        self.assertNotEqual(initial[code]['fast'], updated[code]['fast'])
        for component in ('P', 'moderate', 'fast', 'trend'):
            self.assertEqual(initial['15-1252.00'][component], updated['15-1252.00'][component])
        for counts in ({'recent':-1, 'previous':1}, {'recent':1.5, 'previous':1}):
            with self.assertRaises(ValueError):
                app.trends_from_edits(trends, {'synthetic-data-science':counts})

    def test_audit_renderer_never_loads_simulation_or_calls_ranker(self) -> None:
        """All ten identities and specific quality blockers are visible, without scoring calls."""
        ui = RecordingUI()
        with patch('app.load_demo', side_effect=AssertionError('No synthetic data allowed')), \
             patch('app.rank_roles', side_effect=AssertionError('No ranking allowed')), \
             patch('app.get_trend_client', return_value=Mock(
                 cached=Mock(return_value={'snapshot': None, 'error': None}),
                 refresh=Mock(side_effect=AssertionError('No Refresh click')))):
            app.render_audit(ui)
        warnings = [args[0] for method, args, _ in ui.calls if method == 'warning']
        self.assertTrue(any('Recommend Suppress=Y' in text for text in warnings))
        self.assertTrue(any('Not Relevant=Y' in text for text in warnings))
        self.assertTrue(any('unknown' in text for text in warnings))
        table = next(args[0] for method, args, _ in ui.calls if method == 'table')
        self.assertEqual(len(table), 10)
        self.assertTrue(all('Code' in row and 'Official title' in row for row in table))
        frames = [args[0] for method, args, _ in ui.calls if method == 'dataframe']
        self.assertEqual(len(frames), 30)
        self.assertTrue(all('Raw value' in row and 'Scale' in row
                            and 'Usable converted value' in row for rows in frames for row in rows))
        self.assertFalse(any(method in ('progress', 'metric') for method, _, _ in ui.calls))

    def test_missing_evidence_is_visible_not_imputed(self) -> None:
        """An absent source row remains null and its exact reason reaches the audit output."""
        role = deepcopy(app.load_onet()['roles'][0])
        rating = role['skills']['skill_01']['sources']['LV']
        rating.update(source_rows=[], normalized_raw=None, value=None,
                      issues=['Missing LV source record'])
        role['skills']['skill_01'].update(required=None, issues=['Missing LV source record'])
        role['data_issues'].append('Missing LV source record')
        audited = app.audit_role(role)
        row = next(r for r in audited['rows']['skills']
                   if r['Field ID'] == 'skill_01' and r['Scale'] == 'LV')
        self.assertIsNone(row['Raw value'])
        self.assertIsNone(row['Usable converted value'])
        self.assertIn('Missing LV source record', row['Blockers'])
        self.assertIn('Missing LV source record', audited['blockers'])


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit is not installed in this interpreter')
class StreamlitModeTests(unittest.TestCase):
    """Exercise real rendering with AppTest, without starting a web server."""

    def test_submit_edit_and_switch_modes(self) -> None:
        """Simulation edits recalculate, then audit shows source evidence without totals."""
        from streamlit.testing.v1 import AppTest
        from src.github_trends import GitHubTrends
        empty_client = GitHubTrends(opener=Mock(side_effect=AssertionError('No HTTP in mode test')))
        client_patch = patch('src.github_trends.shared_client', return_value=empty_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        page = AppTest.from_file(str(app.ROOT/'app.py')).run(timeout=30)
        page.radio(key='page_mode').set_value('Synthetic simulation').run(timeout=30)
        self.assertFalse(page.exception)
        page.checkbox(key='simulation_confirm').check()
        page.button[0].click().run(timeout=30)
        self.assertFalse(page.exception)
        before = [bar.value for bar in page.get('progress')]
        self.assertEqual(len(before), 6)
        page.number_input(key='simulation_recent_synthetic-data-science').set_value(2000)
        page.button[0].click().run(timeout=30)
        self.assertFalse(page.exception)
        self.assertNotEqual(before, [bar.value for bar in page.get('progress')])
        # Track actual file access while confirmed simulation state still exists.
        read_text = Path.read_text
        reads = []

        def tracked_read(path, *args, **kwargs):
            if path.name in ('demo_profile.json', 'demo_roles.json', 'demo_trends.json', 'onet_roles.json'):
                reads.append(path.name)
            return read_text(path, *args, **kwargs)

        with patch.object(Path, 'read_text', tracked_read):
            page.radio(key='page_mode').set_value('O*NET data audit').run(timeout=30)
        self.assertEqual(reads, ['onet_roles.json'])
        self.assertFalse(page.exception)
        self.assertFalse(page.error)
        self.assertEqual(len(page.get('progress')), 0)
        self.assertEqual(len(page.selectbox), 0)
        self.assertEqual(len(page.dataframe), 30)
        self.assertTrue(any('unknown' in warning.value for warning in page.warning))
        self.assertTrue(any('Recommend Suppress=Y' in warning.value for warning in page.warning))
        self.assertEqual(len(page.table[0].value), 10)
