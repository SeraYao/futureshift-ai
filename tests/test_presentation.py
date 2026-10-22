"""Check visitor-facing information and closed technical disclosures; never use real HTTP."""
import ast
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import app


class DisclosureStructureTests(unittest.TestCase):
    """Raw JSON must require opening a deliberately closed Technical details section."""

    def test_every_explicit_json_is_in_closed_technical_details(self) -> None:
        """Prevent debug JSON from accidentally returning to any normal page surface."""
        tree=ast.parse((app.ROOT/'app.py').read_text())
        json_calls=[]

        def visit(node, technical=False):
            if isinstance(node,ast.With):
                for item in node.items:
                    call=item.context_expr
                    if (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                            and call.func.attr=='expander' and call.args
                            and ((isinstance(call.args[0],ast.Constant) and call.args[0].value=='Technical details')
                                 or (isinstance(call.args[0],ast.Call)
                                     and isinstance(call.args[0].func,ast.Name)
                                     and call.args[0].func.id=='tr'
                                     and isinstance(call.args[0].args[0],ast.Constant)
                                     and call.args[0].args[0].value=='Technical details'))):
                        self.assertTrue(any(k.arg=='expanded' and isinstance(k.value,ast.Constant)
                                            and k.value.value is False for k in call.keywords))
                        technical=True
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='json':
                json_calls.append(node)
                self.assertTrue(technical,f'JSON outside Technical details at line {node.lineno}')
                self.assertTrue(any(k.arg=='expanded' and isinstance(k.value,ast.Constant)
                                    and k.value.value is False for k in node.keywords))
            for child in ast.iter_child_nodes(node):
                visit(child,technical)

        visit(tree)
        self.assertGreater(len(json_calls),0)


@unittest.skipUnless(importlib.util.find_spec('streamlit'),'Streamlit not installed in this interpreter')
class VisitorPresentationTests(unittest.TestCase):
    """Exercise the real Streamlit tree without launching a persistent server."""

    def check_disclosures(self,page) -> list:
        """Assert automatic JSON and formulas are hidden; return visitor-level elements."""
        visible=[]
        technical_blocks=[]
        raw_json=[]

        def walk(node,technical=False):
            if getattr(node,'type',None)=='expander' and node.label=='Technical details':
                self.assertFalse(node.proto.expanded)
                technical_blocks.append(node)
                technical=True
            if getattr(node,'type',None) in ('json','code'):
                self.assertTrue(technical,'Raw data or formulas visible outside Technical details')
                if node.type=='json':
                    raw_json.append(node)
            if not technical:
                visible.append(node)
            for child in getattr(node,'children',{}).values():
                walk(child,technical)

        walk(page._tree)
        self.assertTrue(technical_blocks)
        self.assertTrue(raw_json,'Technical details must retain inspectable raw evidence')
        return visible

    def test_both_modes_keep_useful_results_and_hide_internal_data(self) -> None:
        """A reviewer sees working simulation and raw counts, while caches stay behind disclosures."""
        from streamlit.testing.v1 import AppTest
        from src.github_trends import GitHubTrends
        from test_github_trends import response
        opener=Mock(side_effect=[response(23),response(19),response(7),response(5)])
        client=GitHubTrends(opener=opener,
                           now=lambda:datetime(2026,10,21,12,tzinfo=timezone.utc))
        client.refresh('15-2051.00')  # Four mock responses; no real API request.
        with patch('app.shared_client',return_value=client), \
             patch('src.github_trends.shared_client',return_value=client), \
             patch('urllib.request.urlopen',side_effect=AssertionError('Real HTTP forbidden')):
            page=AppTest.from_file(str(app.ROOT/'app.py')).run(timeout=30)
            page.radio(key='page_mode').set_value('Synthetic simulation').run(timeout=30)
            self.assertFalse(page.exception)
            page.checkbox(key='simulation_confirm').check()
            page.button[0].click().run(timeout=30)
            self.assertFalse(page.exception)
            simulation=self.check_disclosures(page)
            self.assertEqual(len(page.get('progress')),6)
            self.assertTrue(any('synthetic demonstration data' in warning.value for warning in page.warning))
            self.assertFalse(any('Fixture snapshot:' in str(getattr(node,'value','')) for node in simulation))
            page=AppTest.from_file(str(app.ROOT/'scripts/onet_audit.py')).run(timeout=30)
            self.assertFalse(page.exception)
            self.assertFalse(page.error)
            audit=self.check_disclosures(page)
            visitor_text=' '.join(str(getattr(node,'value','')) for node in audit)
            self.assertIn('GitHub activity trend score T',visitor_text)
            self.assertIn('Topic score T_k',visitor_text)
            self.assertNotIn('Cache state:',visitor_text)
            self.assertNotIn('cached_at',visitor_text)
            self.assertNotIn('Recommend Suppress=',visitor_text)
            self.assertNotIn('Source files, transformations',visitor_text)
            tables=[node.value for node in audit if getattr(node,'type',None)=='table']
            counts=[int(value) for table in tables if 'Repository count' in table
                    for value in table['Repository count']]
            self.assertEqual(counts,[19,23,5,7])
            self.assertTrue(any('Official title' in table and len(table)==10 for table in tables))
            self.assertEqual(opener.call_count,4,'Rendering must not issue any additional request')
