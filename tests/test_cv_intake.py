"""PDF parsing, consent, fixed-schema AI extraction and real intake UI; all HTTP mocked."""
from copy import deepcopy
from io import BytesIO
import importlib.util
import json
import logging
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import app
from src.cv_pdf import CVError, MAX_PDF_BYTES, extract_pdf
from src.cv_client import (AIConfig, MAX_INPUT_CHARS, extract_with_ai, redact_text, validate_extraction)
from src.cv_intake import apply_cv_fields, clear_cv_review
from src.pathway import scoring_errors

SOURCE = "Bachelor's degree in Computing\nSkills: Programming and Critical Thinking\nKnowledge: Mathematics\nCoursework: built a small data project."
CONFIG = AIConfig('https://example.invalid/v1', 'test-model', 'test-key-not-real')


def extraction() -> dict:
    """Use only explicit test CV facts, with literal supporting quotes and no ability scores."""
    return {'education': [
                {'field': 'Current or completed field of study', 'value': 'Computing',
                 'evidence': "Bachelor's degree in Computing"},
                {'field': 'Highest/current study level', 'value': "Bachelor's",
                 'evidence': "Bachelor's degree in Computing"}],
            'skills': [{'field': 'skill_04', 'evidence': 'Skills: Programming and Critical Thinking'}],
            'knowledge': [{'field': 'knowledge_02', 'evidence': 'Knowledge: Mathematics'}],
            'experience': [{'summary': 'built a small data project.',
                            'evidence': 'Coursework: built a small data project.'}],
            'unconfirmed_fields': []}


def reply(content: str | None = None, status: int = 200) -> Mock:
    """Emulate an OpenAI-compatible HTTP response without any connection."""
    response = Mock(status=status)
    response.read.return_value = json.dumps({'choices': [{'message': {
        'content': content if content is not None else json.dumps(extraction())}}]}).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


class PDFTests(unittest.TestCase):
    """Verify PDF boundaries with injectable reader stubs, never real CVs."""

    def reader(self, text: str = SOURCE, pages: int = 1, encrypted: bool = False) -> Mock:
        """Build a mock selectable-text parser."""
        reader = Mock(is_encrypted=encrypted)
        reader.pages = [Mock(extract_text=Mock(return_value=text)) for _ in range(pages)]
        return Mock(return_value=reader)

    def test_valid_pdf_in_memory(self) -> None:
        """A PDF is passed as BytesIO; no disk or metadata extraction is used."""
        factory = self.reader()
        self.assertEqual(extract_pdf('CV.PDF', b'%PDF-1.7 synthetic', factory), SOURCE)
        self.assertIsInstance(factory.call_args.args[0], BytesIO)
        self.assertEqual(factory.call_args.kwargs, {'strict': True})

    def test_invalid_extension_signature_size_and_page_count(self) -> None:
        """Input checks run before parsing and page limits run before text extraction."""
        for name, content in (('cv.docx', b'%PDF-1.7'), ('cv.pdf', b'not PDF'),
                              ('cv.pdf', b'%PDF-' + b'x' * MAX_PDF_BYTES), ('cv.pdf', b'')):
            factory = self.reader()
            with self.subTest(name=name, length=len(content)), self.assertRaises(CVError):
                extract_pdf(name, content, factory)
            factory.assert_not_called()
        for count in (0, 6):
            factory = self.reader(pages=count)
            with self.assertRaisesRegex(CVError, '1–5'):
                extract_pdf('cv.pdf', b'%PDF-1.7', factory)

    def test_corrupt_encrypted_scanned_and_no_logs(self) -> None:
        """All parser failures are sanitized; scanned/encrypted files never become empty profiles."""
        for factory, expected in ((Mock(side_effect=RuntimeError('PRIVATE DOCUMENT')), 'damaged'),
                                  (self.reader(encrypted=True), 'Encrypted'),
                                  (self.reader(text=''), 'No selectable text')):
            with self.subTest(expected=expected), self.assertRaisesRegex(CVError, expected) as caught:
                extract_pdf('cv.pdf', b'%PDF-1.7', factory)
            self.assertNotIn('PRIVATE DOCUMENT', str(caught.exception))
        log = logging.getLogger('pypdf')
        handler = Mock(spec=logging.Handler, level=logging.DEBUG)
        handler.level = logging.DEBUG
        log.addHandler(handler)
        try:
            def noisy(*args, **kwargs):
                log.warning('PRIVATE CV CONTENT')
                raise ValueError('private')
            with self.assertRaises(CVError):
                extract_pdf('cv.pdf', b'%PDF-1.7', noisy)
            handler.handle.assert_not_called()
        finally:
            log.removeHandler(handler)


class AIClientTests(unittest.TestCase):
    """Consent enforced at the client boundary, with local redaction and strict evidence checks."""

    def test_no_consent_zero_requests_and_missing_config(self) -> None:
        """Even direct calls cannot send text without a literal True consent value."""
        opener = Mock()
        for consent in (False, None, 1, 'yes'):
            with self.assertRaisesRegex(CVError, 'Consent'):
                extract_with_ai(SOURCE, consent, app.LABELS, config=CONFIG, opener=opener)
        opener.assert_not_called()
        with self.assertRaisesRegex(CVError, 'not configured'):
            AIConfig.from_env({})
        self.assertNotIn(CONFIG.api_key, repr(CONFIG))

    def test_redaction_limit_and_success(self) -> None:
        """Contact details never enter the outgoing body, and input stays within 8,000 chars."""
        contacts = ('Name: Fictional Student\nAddress: 12 Secret Road\n'
                    'mail: a@example.com phone: +60 12 345 6789\nhttps://private.example/profile\n')
        text = contacts + SOURCE + '\n' + 'x' * 20_000
        opener = Mock(return_value=reply())
        result = extract_with_ai(text, True, app.LABELS, config=CONFIG, opener=opener)
        request = opener.call_args.args[0]
        payload = json.loads(request.data)
        sent = payload['messages'][1]['content']
        self.assertLessEqual(len(sent), MAX_INPUT_CHARS)
        for private in ('Fictional Student', 'Secret Road', 'a@example.com', '345 6789', 'private.example'):
            self.assertNotIn(private, sent)
        self.assertNotIn(CONFIG.api_key, request.data.decode())
        self.assertTrue(request.full_url.endswith('/v1/chat/completions'))
        self.assertEqual(result['skills'][0]['field'], 'skill_04')
        self.assertIn('R1', result['unconfirmed_fields'])
        self.assertIn('skill_01', result['unconfirmed_fields'])
        self.assertNotIn('skill_04', result['unconfirmed_fields'])

    def test_untrusted_metadata_and_body_are_omitted(self) -> None:
        """Malformed, oversized, PII and echoed-secret metadata cannot reach diagnostics."""
        for body in (b'not json', b'x' * 64001, json.dumps({'error': {
                'type': CONFIG.api_key, 'code': SOURCE, 'message': SOURCE}}).encode()):
            failure = HTTPError('https://example.invalid', 400, SOURCE,
                                {'x-request-id': 'private@example.com'}, BytesIO(body))
            with self.assertRaises(CVError) as caught:
                extract_with_ai(SOURCE, True, app.LABELS, config=CONFIG,
                                opener=Mock(side_effect=failure))
            message = str(caught.exception)
            self.assertIn('HTTP error 400', message)
            for sensitive in (SOURCE, CONFIG.api_key, 'private@example.com'):
                self.assertNotIn(sensitive, message)
            self.assertNotIn('Request ID:', message)

    def test_invalid_json_timeouts_service_failures_and_invented_evidence(self) -> None:
        """Failures expose neither provider messages/keys nor unsupported profile facts."""
        for failure in (TimeoutError('PRIVATE'), URLError('PRIVATE'),
                        HTTPError('https://example.invalid', 500, 'PRIVATE', {}, BytesIO(b'PRIVATE'))):
            with self.subTest(failure=type(failure).__name__), self.assertRaises(CVError) as caught:
                extract_with_ai(SOURCE, True, app.LABELS, config=CONFIG, opener=Mock(side_effect=failure))
            self.assertNotIn('PRIVATE', str(caught.exception))
        for response in (reply('not json'), reply(status=503)):
            with self.assertRaises(CVError):
                extract_with_ai(SOURCE, True, app.LABELS, config=CONFIG, opener=Mock(return_value=response))
        document = extraction()
        document['skills'][0]['score'] = 4
        with self.assertRaises(CVError):
            validate_extraction(document, SOURCE, app.LABELS)
        document = extraction()
        document['skills'][0]['evidence'] = 'Invented Programming expert'
        result = validate_extraction(document, SOURCE, app.LABELS)
        self.assertEqual(result['skills'], [])
        self.assertIn('skill_04', result['unverified_fields'])
        document = extraction()
        document['education'][0]['value'] = 'Health'
        result = validate_extraction(document, SOURCE, app.LABELS)
        self.assertEqual(len(result['education']), 1)

    def test_mock_pdf_formatting_and_literal_evidence(self):
        source = SOURCE.replace('Programming', 'Pro-\ngramming').replace('Critical Thinking', 'Critical\n  Thinking').replace('Knowledge:', '• Knowledge:').replace('Computing', 'Ｃomputing')
        factory = PDFTests().reader(source)
        text = extract_pdf('synthetic.pdf', b'%PDF-1.7 synthetic', factory)
        result = extract_with_ai(text, True, app.LABELS, config=CONFIG, opener=Mock(return_value=reply()))
        self.assertEqual(result['skills'], extraction()['skills'])
        self.assertEqual(result['unverified_fields'], [])

    def test_paraphrases_and_fabrication_are_excluded(self):
        for quote in ('Programming expert', 'Skills: Programming & Critical Thinking', 'Skills: programming and Critical Thinking'):
            document = extraction()
            document['skills'][0]['evidence'] = quote
            document['experience'][0]['summary'] = 'Delivered an advanced project.'
            result = extract_with_ai(SOURCE, True, app.LABELS, config=CONFIG, opener=Mock(return_value=reply(json.dumps(document))))
            self.assertEqual(result['skills'], [])
            self.assertEqual(result['experience'], [])
            self.assertIn('skill_04', result['unconfirmed_fields'])
            state = {'pathway_draft': {'skill_04': 1}}
            before = deepcopy(state)
            with self.assertRaises(CVError):
                apply_cv_fields(state, result, {}, {'skill_04': 4}, [], True)
            self.assertEqual(state, before)
            apply_cv_fields(state, result, {}, {}, [], True)
            self.assertEqual(state['pathway_draft']['skill_04'], 1)
            self.assertEqual(state['pathway_cv_context']['skills'], [])

    def test_all_unverifiable_requires_manual_entry(self):
        with self.assertRaisesRegex(CVError, 'fill in your profile manually'):
            extract_with_ai('Unrelated synthetic text', True, app.LABELS, config=CONFIG, opener=Mock(return_value=reply()))

    def test_unicode_whitespace_bullets_and_hyphens(self):
        from src.cv_client import normalize_evidence
        for left, right in [('Café', 'Café'), ('• Critical\n Thinking', '- Critical Thinking'), ('data‑driven', 'data-driven'), ('Pro\u00adgramming', 'Programming')]:
            self.assertEqual(normalize_evidence(left), normalize_evidence(right))


class MappingTests(unittest.TestCase):
    """CV mentions only become ability scores if the user supplies and confirms self-ratings."""

    def test_mapping_missing_fields_preserved_and_cancel_safe(self) -> None:
        """Education and user ratings reuse the existing draft; missing fields stay unanswered."""
        review = validate_extraction(extraction(), SOURCE, app.LABELS)
        state = {'pathway_draft': {'skill_01': 1, 'Optional career goal': 'Existing'}}
        before = deepcopy(state)
        with self.assertRaises(CVError):
            apply_cv_fields(state, review, {}, {'skill_04': 3}, ['Project note'], False)
        self.assertEqual(state, before)
        state['cv_review'] = review
        clear_cv_review(state)
        self.assertEqual(state['pathway_draft'], before['pathway_draft'])
        apply_cv_fields(state, review, {'Current or completed field of study': 'Computing'},
                        {'skill_04': 2, 'knowledge_02': None}, ['Project note'], True)
        draft = state['pathway_draft']
        self.assertEqual(draft['skill_04'], 2)
        self.assertEqual(draft['skill_01'], 1)
        self.assertEqual(draft['Current or completed field of study'], 'Computing')
        self.assertNotIn('knowledge_02', draft)
        self.assertIn('R1', scoring_errors(draft))
        self.assertNotIn('pathway_confirmed', state)
        self.assertNotIn('experience', draft)
        self.assertTrue(state['pathway_cv_context']['experience'])

    def test_invalid_edited_fields_do_not_mutate_state(self) -> None:
        """Unconfirmed fields, unsupported education or invalid ratings cannot overwrite answers."""
        for education, ratings in (({}, {'skill_05': 4}), ({}, {'skill_04': 5}),
                                    ({'Highest/current study level': 'Doctorate'}, {})):
            state = {'pathway_draft': {'skill_04': 1}}
            old = deepcopy(state)
            with self.assertRaises(CVError):
                apply_cv_fields(state, extraction(), education, ratings, ['Note'], True)
            self.assertEqual(state, old)


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit not installed')
class CVPageTests(unittest.TestCase):
    """Verify entry points, consent, review, cancel and confirm using Streamlit interactions."""

    def test_entry_both_pages_and_no_config_fallback(self) -> None:
        """PDF upload is visible on identity and background; missing configuration leaves manual intake usable."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            self.assertTrue(any(e.label == 'Upload a PDF CV' for e in page.expander))
            page.button(key='pathway_start').click().run()
            self.assertTrue(any(e.label == 'Upload a PDF CV' for e in page.expander))
            self.assertTrue(page.text_area(key='pathway_Optional career goal'))
        uploaded = BytesIO(b'%PDF-1.7 synthetic'); uploaded.name = 'cv.pdf'
        def upload(label, **kwargs):
            return uploaded if label == 'Choose a PDF CV' else None
        with patch('streamlit.file_uploader', side_effect=upload), \
             patch('src.cv_intake.extract_pdf', return_value=SOURCE), \
             patch('src.cv_intake.AIConfig.from_env', side_effect=CVError('AI is not configured. Set AI_BASE_URL, AI_MODEL and AI_API_KEY.')), \
             patch('src.cv_intake.extract_with_ai') as ai:
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            self.assertFalse(page.exception)
            self.assertTrue(page.button(key='cv_extract').disabled)
            self.assertTrue(any('AI is not configured' in info.value for info in page.info))
            ai.assert_not_called()

    def test_failed_parse_does_not_replace_existing_answers(self) -> None:
        """An invalid PDF never opens AI review or touches a saved questionnaire draft."""
        from streamlit.testing.v1 import AppTest
        uploaded = BytesIO(b'%PDF-1.7 damaged'); uploaded.name = 'cv.pdf'
        def upload(label, **kwargs):
            return uploaded if label == 'Choose a PDF CV' else None
        with patch('streamlit.file_uploader', side_effect=upload), \
             patch('src.cv_intake.extract_pdf', side_effect=CVError('Damaged PDF; use the questionnaire')), \
             patch('src.cv_intake.extract_with_ai') as ai:
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            draft = {'skill_04': 1, 'Optional career goal': 'Existing goal'}
            page.session_state['pathway_draft'] = draft
            page.run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_draft'], draft)
            self.assertTrue(any('Damaged PDF' in error.value for error in page.error))
            self.assertNotIn('cv_review', page.session_state)
            ai.assert_not_called()

    def test_replacing_upload_requires_fresh_consent(self) -> None:
        """Consent to one uploaded document cannot silently transfer to another document."""
        from streamlit.testing.v1 import AppTest
        current = [BytesIO(b'%PDF-1.7 first')]
        current[0].name = 'first.pdf'
        def upload(label, **kwargs):
            return current[0] if label == 'Choose a PDF CV' else None
        with patch('streamlit.file_uploader', side_effect=upload), \
             patch('src.cv_intake.extract_pdf', return_value=SOURCE), \
             patch('src.cv_intake.AIConfig.from_env', return_value=CONFIG), \
             patch('src.cv_intake.extract_with_ai') as ai:
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            next(box for box in page.checkbox if box.key.startswith('cv_consent_')).check().run()
            self.assertFalse(page.button(key='cv_extract').disabled)
            current[0] = BytesIO(b'%PDF-1.7 second')
            current[0].name = 'second.pdf'
            page.run()
            self.assertTrue(page.button(key='cv_extract').disabled)
            ai.assert_not_called()

    def test_safe_diagnostics_on_page_without_profile_changes_or_retries(self) -> None:
        """Real client exceptions reach the warning; HTTP and transport calls are mocked."""
        from streamlit.testing.v1 import AppTest
        private = SOURCE + ' private.person@example.com +60 12 345 6789 ' + CONFIG.api_key
        request_id = 'req-a12bc34de56fa78bc90de12fa34bc56d'
        cases = [(status, 'HTTP error ' + str(status)) for status in (400, 401, 403, 429, 500, 503)]
        cases += [('ssl', 'SSL error'), ('connection', 'connection error'), ('timeout', 'timeout error'),
                  ('wrapped_timeout', 'timeout error')]
        for kind, expected in cases:
            with self.subTest(kind=kind):
                active = [True]
                uploaded = BytesIO(b'%PDF-1.7 synthetic')
                uploaded.name = 'cv.pdf'
                def upload(label, **kwargs):
                    return uploaded if active[0] and label == 'Choose a PDF CV' else None
                def fail(*args, **kwargs):
                    active[0] = False
                    if isinstance(kind, int):
                        raise HTTPError('https://example.invalid', kind, private,
                                        {'x-request-id': request_id}, BytesIO(json.dumps({'error': {
                                            'type': 'invalid_request_error', 'code': 'invalid_api_key',
                                            'message': private}, 'request': private}).encode()))
                    reason = (ssl.SSLError(private) if kind == 'ssl' else
                              TimeoutError(private) if kind in ('timeout', 'wrapped_timeout') else
                              ConnectionRefusedError(private))
                    raise URLError(reason) if kind != 'timeout' else reason
                handler = Mock(spec=logging.Handler, level=logging.DEBUG)
                handler.level = logging.DEBUG
                root = logging.getLogger()
                root.addHandler(handler)
                try:
                    with patch('streamlit.file_uploader', side_effect=upload), \
                         patch('src.cv_intake.extract_pdf', return_value=SOURCE), \
                         patch('src.cv_intake.AIConfig.from_env', return_value=CONFIG), \
                         patch('urllib.request.OpenerDirector.open', side_effect=fail) as send:
                        page = AppTest.from_file(str(app.ROOT/'app.py')).run()
                        draft = {'skill_04': 1, 'Optional career goal': 'Existing'}
                        page.session_state['pathway_draft'] = deepcopy(draft)
                        page.session_state['pathway_confirmed'] = {'existing': True}
                        next(box for box in page.checkbox if box.key.startswith('cv_consent_')).check().run()
                        page.button(key='cv_extract').click().run()
                        self.assertFalse(page.exception)
                        warning = ' '.join(item.value for item in page.warning)
                        self.assertIn(expected, warning)
                        self.assertIn('No profile was changed', warning)
                        details = next(item for item in page.expander if item.label == 'Technical error details')
                        self.assertFalse(details.proto.expanded)
                        technical = ' '.join(item.value for item in details.text)
                        if isinstance(kind, int):
                            self.assertIn('HTTP status: ' + str(kind), technical)
                            self.assertIn('code: invalid_api_key', technical)
                            self.assertIn(request_id, technical)
                            self.assertIn('type: invalid_request_error', warning)
                            self.assertIn('code: invalid_api_key', warning)
                            self.assertIn(request_id, warning)
                        self.assertEqual(page.session_state['pathway_draft'], draft)
                        self.assertEqual(page.session_state['pathway_confirmed'], {'existing': True})
                        self.assertNotIn('cv_review', page.session_state)
                        page.run()
                        send.assert_called_once()
                        self.assertTrue(any(expected in item.value for item in page.warning))
                        visible = str(page) + warning + technical
                        logs = str(handler.handle.call_args_list)
                        for sensitive in (CONFIG.api_key, SOURCE, 'private.person@example.com',
                                          '+60 12 345 6789', 'Authorization'):
                            self.assertNotIn(sensitive, visible)
                            self.assertNotIn(sensitive, logs)
                finally:
                    root.removeHandler(handler)

    def test_partial_review_excludes_unverified_fields(self):
        """Preview discloses excluded fields; cancel preserves the existing profile."""
        from streamlit.testing.v1 import AppTest
        document = extraction()
        document['skills'][0]['evidence'] = 'Invented Programming expert'
        review = validate_extraction(document, SOURCE, app.LABELS)
        page = AppTest.from_file(str(app.ROOT/'app.py')).run()
        draft = {'skill_04': 1}
        page.session_state['pathway_draft'] = deepcopy(draft)
        page.session_state['cv_review'] = review
        page.run()
        self.assertFalse(page.exception)
        self.assertTrue(any('Unable to verify' in warning.value for warning in page.warning))
        self.assertFalse(any(box.key == 'cv_rating_skill_04' for box in page.selectbox))
        self.assertEqual(page.session_state['pathway_draft'], draft)
        page.button(key='cv_cancel_review').click().run()
        self.assertEqual(page.session_state['pathway_draft'], draft)

    def test_consent_extract_review_cancel_and_apply(self) -> None:
        """Upload/consent alone send nothing; extraction is a click, and applying requires another confirmation."""
        from streamlit.testing.v1 import AppTest
        uploaded = BytesIO(b'%PDF-1.7 synthetic'); uploaded.name = 'cv.pdf'
        active = [True]
        def upload(label, **kwargs):
            return uploaded if label == 'Choose a PDF CV' and active[0] else None
        review = validate_extraction(extraction(), SOURCE, app.LABELS)
        def extract(*args, **kwargs):
            active[0] = False
            return deepcopy(review)
        with patch('streamlit.file_uploader', side_effect=upload), \
             patch('src.cv_intake.extract_pdf', return_value=SOURCE), \
             patch('src.cv_intake.AIConfig.from_env', return_value=CONFIG), \
             patch('src.cv_intake.extract_with_ai', side_effect=extract) as ai, \
             patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')):
            page = AppTest.from_file(str(app.ROOT/'app.py')).run()
            self.assertFalse(page.exception)
            self.assertTrue(page.button(key='cv_extract').disabled)
            ai.assert_not_called()
            consent = next(box for box in page.checkbox if box.key.startswith('cv_consent_'))
            consent.check().run()
            ai.assert_not_called()
            page.button(key='cv_extract').click().run()
            ai.assert_called_once()
            self.assertTrue(ai.call_args.args[1])
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_draft'], {})
            self.assertIsNone(page.selectbox(key='cv_rating_skill_04').value)
            self.assertTrue(page.button(key='cv_apply').disabled)
            page.selectbox(key='cv_rating_skill_04').set_value(2).run()
            page.checkbox(key='cv_review_confirm').check().run()
            page.button(key='cv_apply').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(page.session_state['pathway_step'], 1)
            self.assertEqual(page.session_state['pathway_draft']['skill_04'], 2)
            self.assertNotIn('knowledge_02', page.session_state['pathway_draft'])
            self.assertNotIn('cv_review', page.session_state)
            self.assertNotIn('pathway_confirmed', page.session_state)
            self.assertEqual(page.session_state['pathway_draft']['Highest/current study level'], "Bachelor's")
            # A cancelled later review cannot change confirmed draft fields.
            before = deepcopy(page.session_state['pathway_draft'])
            page.session_state['cv_review'] = review
            page.run()
            page.button(key='cv_cancel_review').click().run()
            self.assertEqual(page.session_state['pathway_draft'], before)
