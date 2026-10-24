"""Questionnaire contracts and actual guided UI; real HTTP is forbidden."""
from ui_helpers import open_personal_profile
from copy import deepcopy
import importlib.util
import unittest
from unittest.mock import patch

import app
from src.pathway import (INTERESTS, SKILLS, KNOWLEDGE, confirmed_profile,
                         scoring_errors, save_answer)
from src.scoring import rank_roles
from src.sdg import CAREER_IDS
from src.official_labor_evidence import CAREERS as OFFICIAL_CAREERS
from src.career_pool import official_ranking


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

    def test_all_interest_dimensions_keep_documented_positive_mapping(self):
        draft = answers()
        draft.update(zip((key for key, _ in INTERESTS),
                         (1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 1, 5)))
        self.assertEqual(confirmed_profile(draft)['riasec'],
                         [0, 0.25, 0.5, 0.75, 1, 0.5])

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
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(timeout=30))
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['page_mode'], 'Career pathway prototype')
            planned = [button for button in page.button if 'Planned' in button.label]
            self.assertEqual(len(planned), 0)
            self.assertTrue(all(button.disabled for button in planned))
            page.button(key='pathway_start').click().run()
            page.radio(key='pathway_Identity').set_value('Recent graduate').run()
            page.text_area(key='pathway_Optional career goal').set_value('Explore technology').run()
            page.button(key='pathway_next').click().run()
            self.assertTrue(all(box.value is None for box in page.radio if box.key.startswith('pathway_')))
            page.radio(key='pathway_skill_01').set_value(3).run()
            page.button(key='pathway_back').click().run()
            self.assertEqual(page.text_area(key='pathway_Optional career goal').value, 'Explore technology')
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.radio(key='pathway_skill_01').value, 3)
            # Switching modes removes widgets but must preserve the durable questionnaire draft.
            page.button(key='mode_Synthetic simulation').click().run()
            page.button(key='mode_Career pathway prototype').click().run()
            self.assertEqual(page.radio(key='pathway_skill_01').value, 3)
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
            with patch('src.career_pool.official_ranking', wraps=official_ranking) as engine:
                page.button(key='pathway_confirm').click().run()
                self.assertFalse(page.exception)
                engine.assert_called_once()
                self.assertEqual(engine.call_args.args[0], expected)
                self.assertEqual(engine.call_args.args[1], app.load_onet())
            for disclosure in page.expander:
                if disclosure.label == 'Technical details':
                    self.assertFalse(disclosure.proto.expanded)
            self.assertEqual(page.session_state['pathway_confirmed'], expected)
            self.assertFalse(any('Prototype simulation — not a labour-market prediction' in warning.value
                                 for warning in page.warning))
            self.assertEqual(len([e for e in page.expander if 'Why this match?' in e.label]), 6)
            page.button(key='pathway_back').click().run()
            page.button(key='pathway_back').click().run()
            page.button(key='pathway_back').click().run()
            page.radio(key='pathway_R1').set_value(5).run()
            self.assertNotIn('pathway_confirmed', page.session_state)

    def test_complete_questionnaire_with_direct_choices_and_languages(self):
        """Click every scored answer; localization/navigation never changes raw values."""
        from streamlit.testing.v1 import AppTest
        expected = {}
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')):
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
            page.button(key='pathway_start').click().run()
            self.assertIsNone(page.radio(key='pathway_Identity').value)
            self.assertEqual(len([x for x in page.selectbox if x.key.startswith('pathway_')]), 2)
            page.radio(key='pathway_Identity').set_value('Recent graduate').run()
            page.button(key='pathway_next').click().run()
            for keys, values in ((SKILLS, range(5)), (KNOWLEDGE, range(5)),
                                 (tuple(key for key, _ in INTERESTS), range(1, 6))):
                self.assertFalse([x for x in page.selectbox if x.key.startswith('pathway_')])
                for i, key in enumerate(keys):
                    widget = page.radio(key='pathway_' + key)
                    self.assertIsNone(widget.value)
                    self.assertTrue(widget.proto.horizontal)
                    self.assertEqual(widget.options, list(map(str, values)))
                    value = values[i % len(values)]
                    page.radio(key='pathway_' + key).set_value(value).run()
                    expected[key] = value
                for language in ('zh', 'ms', 'en'):
                    page.session_state['ui_language'] = language; page.run()
                    self.assertFalse(page.exception)
                    for key in keys:
                        self.assertEqual(page.radio(key='pathway_' + key).value, expected[key])
                    self.assertEqual({k: page.session_state['pathway_draft'][k] for k in expected}, expected)
                page.button(key='pathway_back').click().run()
                page.button(key='pathway_next').click().run()
                for key in keys:
                    self.assertEqual(page.radio(key='pathway_' + key).value, expected[key])
                page.button(key='pathway_next').click().run()
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.session_state['pathway_step'], 6)
            page.button(key='pathway_confirm').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_step'], 7)
            self.assertEqual(page.session_state['pathway_confirmed'], confirmed_profile(expected))
            self.assertTrue(page.session_state['pathway_assessment']['rows'])
            page.button(key='pathway_reassess').click().run()
            page.button(key='pathway_next').click().run()
            for key in SKILLS:
                self.assertEqual(page.radio(key='pathway_' + key).value, expected[key])

    def test_missing_count_and_untouched_scales_in_all_languages(self):
        from streamlit.testing.v1 import AppTest
        from src.i18n import CATALOGS
        page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run())
        page.button(key='pathway_start').click().run()
        for step, keys in ((2, SKILLS), (3, KNOWLEDGE), (4, tuple(k for k, _ in INTERESTS))):
            page.session_state['pathway_step'] = step
            page.run()
            self.assertTrue(all(page.radio(key='pathway_' + k).value is None for k in keys))
        self.assertEqual(len(scoring_errors(page.session_state['pathway_draft'])), 30)
        page.session_state['pathway_step'] = 5
        page.run()
        for language in ('en', 'zh', 'ms'):
            page.session_state['ui_language'] = language; page.run()
            page.button(key='pathway_next').click().run()
            self.assertEqual(page.session_state['pathway_step'], 5)
            message = CATALOGS[language]['{count} required questions remain unanswered.'].format(count=30)
            self.assertTrue(any(x.value == message for x in page.error))
            self.assertNotIn('pathway_confirmed', page.session_state)

    def test_official_and_synthetic_modes_keep_state_separate_across_languages(self):
        from streamlit.testing.v1 import AppTest

        def visible(page):
            parts = []
            for kind in ('markdown', 'subheader', 'caption', 'info', 'warning', 'text', 'code'):
                parts.extend(str(item.value) for item in page.get(kind))
            for table in page.table:
                if table.value is not None:
                    parts.extend(map(str, table.value.columns))
                    parts.extend(table.value.astype(str).to_numpy().ravel().tolist())
            return '\n'.join(parts)

        with patch('urllib.request.urlopen', side_effect=AssertionError('No network')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            self.assertEqual(page.session_state['page_mode'], 'Career pathway prototype')
            page.button(key='scenario_explore').click().run()
            page.button(key='pathway_sample').click().run()
            self.assertFalse(page.exception)
            self.assertFalse(any(widget.key == 'career_catalog_mode' for widget in page.radio))
            self.assertIn('fixed local recommendation pool', visible(page))
            official_cards = '\n'.join(item.value for item in page.markdown if 'data-sdg-result=' in item.value)
            self.assertEqual(sum('data-sdg-result=' in item.value for item in page.markdown), 6)
            self.assertNotIn('15-2051.00', official_cards)
            display_role = page.selectbox(key='learning_role').options[0]
            page.selectbox(key='learning_role').set_value(display_role).run()
            role = page.session_state['learning_role']
            checkbox = next(box for box in page.checkbox if box.key.startswith('learning_check_'))
            checkbox.check().run()
            official_assessment = deepcopy(page.session_state['pathway_assessment'])
            official_progress = deepcopy(page.session_state['learning_progress'])

            # The explicitly labeled demo has its own profile and never renders the official plan/cards.
            page.button(key='mode_Synthetic simulation').click().run()
            self.assertFalse(page.exception)
            self.assertTrue(any('independent demo' in item.value for item in page.info))
            self.assertNotIn('data-sdg-result=', visible(page))
            self.assertNotIn('Official O*NET 31.0 requirements', visible(page))
            self.assertEqual(page.session_state['pathway_assessment'], official_assessment)
            self.assertEqual(page.session_state['learning_progress'], official_progress)
            page.checkbox(key='simulation_confirm').check()
            submit = next(button for button in page.button if 'Confirm profile & calculate matches' in button.label)
            submit.click().run()
            self.assertFalse(page.exception)
            demo_text = visible(page)
            self.assertIn('Matched to your profile', demo_text)
            self.assertNotIn('Information Security Analysts', demo_text)
            self.assertEqual(page.session_state['pathway_assessment'], official_assessment)
            self.assertEqual(page.session_state['learning_progress'], official_progress)

            # Returning restores the same official selection/progress; language changes do not recalculate it.
            page.button(key='mode_Career pathway prototype').click().run()
            self.assertEqual(page.session_state['learning_role'], role)
            self.assertEqual(page.session_state['learning_progress'], official_progress)
            self.assertEqual(sum('data-sdg-result=' in item.value for item in page.markdown), 6)
            for language, title in (('en', 'Matched to your profile'),
                                    ('zh', '基于您的画像为您匹配'),
                                    ('ms', 'Padanan berdasarkan profil anda')):
                page.session_state['ui_language'] = language; page.run()
                self.assertFalse(page.exception)
                self.assertEqual(page.session_state['pathway_assessment'], official_assessment)
                self.assertEqual(page.session_state['learning_role'], role)
                self.assertEqual(page.session_state['learning_progress'], official_progress)
                self.assertIn({'en': 'fixed local recommendation pool', 'zh': '当前推荐范围', 'ms': 'Kumpulan cadangan tetap'}[language], visible(page))
