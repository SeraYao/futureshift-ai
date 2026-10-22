"""Questionnaire contracts and actual guided UI; real HTTP is forbidden."""
from copy import deepcopy
import importlib.util
import unittest
from unittest.mock import patch

import app
from src.pathway import (INTERESTS, SKILLS, KNOWLEDGE, confirmed_profile,
                         scoring_errors, save_answer)
from src.scoring import rank_roles


def answers() -> dict:
    """Return complete, deliberately fictional practice responses."""
    return {**{key: 2 for key in (*SKILLS, *KNOWLEDGE)},
            **{key: 3 for key, _ in INTERESTS}}


class QuestionnaireTests(unittest.TestCase):
    """Verify exact documented questions, missing values and deterministic conversion."""

    def test_document_contract(self) -> None:
        """Every questionnaire name and original interest statement is preserved."""
        doc = (app.ROOT / 'docs/QUESTIONNAIRE.md').read_text()
        self.assertEqual((len(SKILLS), len(KNOWLEDGE), len(INTERESTS)), (11, 7, 12))
        for key in (*SKILLS, *KNOWLEDGE):
            self.assertIn(app.LABELS[key], doc)
        for key, statement in INTERESTS:
            self.assertIn(f'| {key} | {statement}', doc)

    def test_scales_and_missing(self) -> None:
        """No default zero; each scored answer must be valid before confirmation."""
        self.assertEqual(len(scoring_errors({})), 30)
        for key, invalid in (('skill_01', None), ('knowledge_01', 5), ('R1', 0), ('I1', True)):
            draft = answers()
            draft[key] = invalid
            self.assertIn(key, scoring_errors(draft))
            with self.assertRaises(ValueError):
                confirmed_profile(draft)
        draft = answers()
        draft.update(R1=1, R2=5, I1=5, I2=5, skill_01=0)
        profile = confirmed_profile(draft)
        self.assertEqual(profile['riasec'][:2], [0.5, 1])
        self.assertEqual(profile['skills']['skill_01'], 0)
        self.assertEqual(profile['knowledge']['knowledge_01'], 2)

    def test_persistence_and_invalidation(self) -> None:
        """Durable drafts survive hidden widgets; edits revoke old confirmation."""
        state = {'pathway_draft': {}, 'pathway_skill_01': 4, 'pathway_confirmed': {}}
        save_answer(state, 'skill_01')
        del state['pathway_skill_01']
        self.assertEqual(state['pathway_draft'], {'skill_01': 4})
        self.assertNotIn('pathway_confirmed', state)

    def test_answer_changes_and_non_scored_fields(self) -> None:
        """Only documented scored answers change existing engine components."""
        _, roles, trends = app.load_demo()
        draft = answers()
        before = deepcopy(draft)
        initial = rank_roles(confirmed_profile(draft), roles['roles'], trends['topics'])
        draft['skill_04'] = 4
        changed = rank_roles(confirmed_profile(draft), roles['roles'], trends['topics'])
        self.assertNotEqual(initial[0]['skills']['score'], changed[0]['skills']['score'])
        for key, component in (('knowledge_01', 'knowledge'), ('R1', 'I')):
            edited = before | {key: 4 if key == 'knowledge_01' else 5}
            result = rank_roles(confirmed_profile(edited), roles['roles'], trends['topics'])
            old = {row['code']: row for row in initial}
            self.assertTrue(any((row[component]['score'] if component == 'knowledge' else row[component])
                                != (old[row['code']][component]['score'] if component == 'knowledge'
                                    else old[row['code']][component]) for row in result))
        draft = before | {'Optional career goal': 'Explore science', 'SDG preferences': ['4']}
        self.assertEqual(initial, rank_roles(confirmed_profile(draft), roles['roles'], trends['topics']))
        draft.update({key: 1 for key, _ in INTERESTS})
        zero = rank_roles(confirmed_profile(draft), roles['roles'], trends['topics'])
        self.assertTrue(all(row['moderate_rank'] is None for row in zero))
        self.assertTrue(all(row['skills']['score'].value is not None for row in zero))


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class GuidedUITests(unittest.TestCase):
    """Drive the actual multi-step UI without a server or external requests."""

    def test_identity_missing_persistence_confirmation_and_results(self) -> None:
        """Only the student entry works, draft survives navigation, confirmation calls engine."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run(timeout=30)
            self.assertFalse(page.exception)
            self.assertEqual(page.radio(key='page_mode').value, 'Career pathway prototype')
            planned = [button for button in page.button if 'Planned' in button.label]
            self.assertEqual(len(planned), 2)
            self.assertTrue(all(button.disabled for button in planned))
            page.button(key='pathway_start').click().run()
            page.selectbox(key='pathway_Identity').set_value('Recent graduate').run()
            page.text_area(key='pathway_Optional career goal').set_value('Explore technology').run()
            page.button(key='pathway_next').click().run()
            self.assertTrue(all(box.value is None for box in page.selectbox if box.key.startswith('pathway_')))
            page.selectbox(key='pathway_skill_01').set_value(3).run()
            page.button(key='pathway_back').click().run()
            self.assertEqual(page.text_area(key='pathway_Optional career goal').value, 'Explore technology')
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.selectbox(key='pathway_skill_01').value, 3)
            # Switching modes removes widgets but must preserve the durable questionnaire draft.
            page.radio(key='page_mode').set_value('Synthetic simulation').run()
            page.radio(key='page_mode').set_value('Career pathway prototype').run()
            self.assertEqual(page.selectbox(key='pathway_skill_01').value, 3)
            page.session_state['pathway_step'] = 5
            page.run()
            page.button(key='pathway_next').click().run()
            self.assertTrue(page.error)
            self.assertEqual(page.session_state['pathway_step'], 5)
            self.assertNotIn('pathway_confirmed', page.session_state)
            draft = answers() | {'Optional career goal': 'Explore technology'}
            page.session_state['pathway_draft'] = draft
            page.run()
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.session_state['pathway_step'], 6)
            self.assertFalse(page.exception)
            self.assertNotIn('pathway_confirmed', page.session_state)
            expected = confirmed_profile(draft)
            with patch('src.pathway.rank_roles', wraps=rank_roles) as engine:
                page.button(key='pathway_confirm').click().run()
                self.assertFalse(page.exception)
                engine.assert_called_once()
                self.assertEqual(engine.call_args.args[0], expected)
                self.assertEqual(engine.call_args.args[1], app.load_demo()[1]['roles'])
                self.assertEqual(engine.call_args.args[2], app.load_demo()[2]['topics'])
            for disclosure in page.expander:
                if disclosure.label == 'Technical details':
                    self.assertFalse(disclosure.proto.expanded)
            self.assertEqual(page.session_state['pathway_confirmed'], expected)
            self.assertFalse(any('Prototype simulation — not a labour-market prediction' in warning.value
                                 for warning in page.warning))
            self.assertEqual(len([e for e in page.expander if 'Why this match?' in e.label]), 3)
            page.button(key='pathway_back').click().run()
            page.button(key='pathway_back').click().run()
            page.button(key='pathway_back').click().run()
            page.selectbox(key='pathway_R1').set_value(5).run()
            self.assertNotIn('pathway_confirmed', page.session_state)
