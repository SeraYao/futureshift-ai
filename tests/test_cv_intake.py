"""PDF parsing, consent, fixed-schema AI extraction and real intake UI; all HTTP mocked."""
from ui_helpers import open_personal_profile
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

    def test_safe_stage_logs_and_body_read_timeout(self):
        response = reply()
        response.read.side_effect = TimeoutError('PRIVATE RESPONSE AND KEY')
        with self.assertLogs('src.cv_client', level='INFO') as logs:
            with self.assertRaisesRegex(CVError, 'timeout error'):
                extract_with_ai(SOURCE, True, app.LABELS, config=CONFIG,
                                opener=Mock(return_value=response))
        records = '\n'.join(logs.output)
        self.assertIn('stage=request_start timeout_seconds=300', records)
        self.assertIn('stage=response_headers', records)
        self.assertIn('http_status=200', records)
        self.assertIn('stage=body_read', records)
        self.assertIn('reason_type=TimeoutError', records)
        for secret in (SOURCE, CONFIG.api_key, 'PRIVATE RESPONSE AND KEY', 'Authorization'):
            self.assertNotIn(secret, records)

    def test_connect_timeout_has_separate_stage_and_keeps_tls_defaults(self):
        from src.cv_client import _ObservedHTTPSConnection
        connection = _ObservedHTTPSConnection('example.invalid', timeout=1)
        self.assertTrue(connection._context.check_hostname)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        with patch('http.client.HTTPSConnection.connect', side_effect=TimeoutError('PRIVATE')):
            with self.assertLogs('src.cv_client', level='WARNING') as logs:
                with self.assertRaises(TimeoutError):
                    connection.connect()
        self.assertIn('stage=connect_tls', logs.output[0])
        self.assertIn('exception=TimeoutError', logs.output[0])
        self.assertNotIn('PRIVATE', logs.output[0])

    def test_default_timeout(self):
        env = {'AI_BASE_URL': CONFIG.base_url, 'AI_MODEL': CONFIG.model, 'AI_API_KEY': CONFIG.api_key}
        config = AIConfig.from_env(env)
        self.assertEqual(config.timeout_seconds, 300)
        send = Mock(return_value=reply())
        extract_with_ai(SOURCE, True, app.LABELS, config=config, opener=send)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs, {'timeout': 300})

    def test_custom_timeout(self):
        for seconds in ('1', ' 600 ', '3600'):
            with self.subTest(seconds=seconds):
                env = {'AI_BASE_URL': CONFIG.base_url, 'AI_MODEL': CONFIG.model,
                       'AI_API_KEY': CONFIG.api_key, 'AI_TIMEOUT_SECONDS': seconds}
                with patch.dict('os.environ', env, clear=True):
                    send = Mock(return_value=reply())
                    extract_with_ai(SOURCE, True, app.LABELS, opener=send)
                send.assert_called_once()
                self.assertEqual(send.call_args.kwargs, {'timeout': int(seconds)})

    def test_invalid_timeout_configuration_sends_nothing(self):
        for value in ('', ' ', '0', '-1', '1.5', 'nan', 'inf', '+300', '٣٠٠', '3601', '9' * 5000):
            with self.subTest(value=value[:20]):
                env = {'AI_BASE_URL': CONFIG.base_url, 'AI_MODEL': CONFIG.model,
                       'AI_API_KEY': CONFIG.api_key, 'AI_TIMEOUT_SECONDS': value}
                send = Mock()
                with patch.dict('os.environ', env, clear=True), self.assertRaisesRegex(CVError, 'AI_TIMEOUT_SECONDS'):
                    extract_with_ai(SOURCE, True, app.LABELS, opener=send)
                send.assert_not_called()
        for value in (0, -1, 3601, True, 300.0, '300'):
            with self.subTest(value=value), self.assertRaises(CVError):
                AIConfig(CONFIG.base_url, CONFIG.model, CONFIG.api_key, value)

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

    def test_upload_empty_profile_failure_retry_and_busy(self):
        """Parse a real PDF and retry without uploading again or filling in a profile."""
        from streamlit.testing.v1 import AppTest
        import streamlit
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        pdf_page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        pdf_page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 50 700 Td (Skills: Programming) Tj ET')
        pdf_page[NameObject('/Contents')] = writer._add_object(stream)
        uploaded = BytesIO()
        writer.write(uploaded)
        uploaded.name = 'cv.pdf'
        current = [None]
        def upload(label, **kwargs):
            return current[0] if label == 'Choose a PDF CV' else None
        def fail_once(*args):
            self.assertTrue(page.session_state['cv_extract_busy'])
            extract_button = next(call for call in reversed(button.call_args_list)
                                  if call.kwargs.get('key') == 'cv_extract')
            self.assertTrue(extract_button.kwargs['disabled'])
            self.assertEqual(page.session_state['pathway_draft'], {})
            if ai.call_count == 1:
                raise CVError('AI timeout error. No profile was changed.')
            return validate_extraction({'education': [], 'skills': [
                {'field': 'skill_04', 'evidence': 'Skills: Programming'}],
                'knowledge': [], 'experience': [], 'unconfirmed_fields': []}, args[0], app.LABELS)
        with patch('streamlit.file_uploader', side_effect=upload), \
             patch('streamlit.button', wraps=streamlit.button) as button, \
             patch('src.cv_intake.AIConfig.from_env', return_value=CONFIG), \
             patch('src.cv_intake.extract_with_ai', side_effect=fail_once) as ai:
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
            current[0] = uploaded
            page.run()
            next(box for box in page.checkbox if box.key.startswith('cv_consent_')).check().run()
            self.assertFalse(page.button(key='cv_extract').disabled)
            page.button(key='cv_extract').click().run()
            self.assertFalse(page.exception)
            self.assertFalse(page.session_state['cv_extract_busy'])
            self.assertFalse(page.button(key='cv_extract').disabled)
            self.assertEqual(page.session_state.get('cv_upload_generation', 0), 0)
            page.run()
            self.assertEqual(ai.call_count, 1)
            page.button(key='cv_extract').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(ai.call_count, 2)
            self.assertFalse(page.session_state['cv_extract_busy'])
            self.assertNotIn('cv_notice', page.session_state)
            self.assertTrue(page.session_state['cv_review']['skills'])
            self.assertEqual(page.session_state['pathway_draft'], {})

    def test_entry_both_pages_and_no_config_fallback(self) -> None:
        """PDF upload is visible on identity and background; missing configuration leaves manual intake usable."""
        from streamlit.testing.v1 import AppTest
        with patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP')):
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
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
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
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
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
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
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
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
                        page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
                        draft = {'skill_04': 1, 'Optional career goal': 'Existing'}
                        page.session_state['pathway_draft'] = deepcopy(draft)
                        page.session_state['pathway_confirmed'] = {'existing': True}
                        next(box for box in page.checkbox if box.key.startswith('cv_consent_')).check().run()
                        page.button(key='cv_extract').click().run()
                        self.assertFalse(page.exception)
                        warning = ' '.join(item.value for item in page.warning)
                        self.assertIn(expected, warning)
                        self.assertIn('No profile was changed', warning)
                        if kind in ('timeout', 'wrapped_timeout'):
                            self.assertIn('may still be cold starting', warning)
                            from src.i18n import translate_error
                            with patch('src.i18n._language') as language:
                                language.get.return_value = 'zh'
                                self.assertIn('AI 服务仍可能正在冷启动。本次未修改画像，请稍后手动重试。', translate_error(page.session_state['cv_notice']))
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
        page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
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
            page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
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

class CVRegressionTests(unittest.TestCase):
    def test_real_synthetic_pdf_boundaries(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        def pdf(*, blank=False, encrypted=False, pages=1):
            writer = PdfWriter()
            for _ in range(pages):
                page = writer.add_blank_page(width=612, height=792)
                if not blank:
                    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                             NameObject('/Subtype'): NameObject('/Type1'),
                                             NameObject('/BaseFont'): NameObject('/Helvetica')})
                    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
                    stream = DecodedStreamObject()
                    stream.set_data(b'BT /F1 12 Tf 50 700 Td (Skills: Programming) Tj 0 -20 Td (Knowledge: Mathematics) Tj ET')
                    page[NameObject('/Contents')] = writer._add_object(stream)
            if encrypted:
                writer.encrypt('synthetic-password')
            output = BytesIO()
            writer.write(output)
            return output.getvalue()

        self.assertIn('Programming', extract_pdf('synthetic.pdf', pdf()))
        for data, expected in ((pdf(blank=True), 'No selectable text'),
                               (pdf(encrypted=True), 'Encrypted'),
                               (pdf(pages=6), '1–5'),
                               (b'%PDF-1.7 broken', 'damaged')):
            with self.subTest(expected=expected), self.assertRaisesRegex(CVError, expected):
                extract_pdf('synthetic.pdf', data)

    def test_typography_and_failure_reasons(self):
        source = SOURCE.replace("Bachelor's", 'Bachelor’s').replace('Programming', 'programming')
        document = extraction()
        document['skills'][0]['evidence'] = 'Skills: programming and Critical Thinking'
        result = validate_extraction(document, source, app.LABELS)
        self.assertEqual(len(result['education']), 2)
        self.assertEqual(len(result['skills']), 1)
        document['skills'][0]['evidence'] = 'Programming expert'
        result = validate_extraction(document, source, app.LABELS)
        self.assertIn('skill_04', result['verification_failures'])
        self.assertNotIn(source, str(result['verification_failures']))

    def test_response_error_categories_and_fences(self):
        from src.cv_client import parse_response
        cases = [(b'broken', 'invalid JSON'), (b'{}', 'missing Chat Completions fields'),
                 (json.dumps({'choices': [{'message': {'refusal': 'PRIVATE'}, 'finish_reason': 'stop'}]}).encode(), 'refused'),
                 (json.dumps({'choices': [{'message': {}, 'finish_reason': 'length'}]}).encode(), 'truncated')]
        for raw, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(CVError, expected) as caught:
                parse_response(raw)
            self.assertNotIn('PRIVATE', str(caught.exception))
        result = extract_with_ai(SOURCE, True, app.LABELS, config=CONFIG,
                                opener=Mock(return_value=reply('```json\n' + json.dumps(extraction()) + '\n```')))
        self.assertTrue(result['skills'])

    def test_preview_sent_and_verified_text_identical(self):
        source = 'Name: Synthetic\n' + SOURCE + '\nmail: synthetic@example.com'
        send = Mock(return_value=reply())
        with patch('src.cv_client.validate_extraction', wraps=validate_extraction) as validate:
            extract_with_ai(source, True, app.LABELS, config=CONFIG, opener=send)
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload['messages'][1]['content'], redact_text(source))
        self.assertEqual(validate.call_args.args[1], redact_text(source))
        self.assertEqual(payload['model'], CONFIG.model)
        self.assertEqual(send.call_args.args[0].get_header('Authorization'), 'Bearer ' + CONFIG.api_key)
        full = AIConfig(CONFIG.base_url + '/chat/completions', CONFIG.model, CONFIG.api_key)
        extract_with_ai(SOURCE, True, app.LABELS, config=full, opener=send)
        self.assertEqual(send.call_args.args[0].full_url, full.base_url)

    def test_page_all_unverified_is_actionable(self):
        from streamlit.testing.v1 import AppTest
        try:
            extract_with_ai('Unrelated synthetic text', True, app.LABELS, config=CONFIG,
                            opener=Mock(return_value=reply()))
        except CVError as exc:
            message = str(exc)
        page = open_personal_profile(AppTest.from_file(str(app.ROOT/'app.py')).run(), entry='cv')
        original = {'skill_04': 1}
        page.session_state['pathway_draft'] = deepcopy(original)
        page.session_state['cv_notice'] = message
        page.run()
        warning = ' '.join(item.value for item in page.warning)
        self.assertIn('No CV fields could be verified', warning)
        self.assertIn('fill in your profile manually', warning)
        self.assertIn('skill_04', warning)
        self.assertEqual(page.session_state['pathway_draft'], original)
        self.assertNotIn(SOURCE, warning)
        self.assertNotIn(CONFIG.api_key, warning)

    def test_pdf_headers_footers_and_crlf_evidence(self):
        source = 'Synthetic header\r\n' + SOURCE.replace('Programming', 'Pro-\r\ngramming') + '\r\nPage 1'
        text = extract_pdf('synthetic.pdf', b'%PDF-1.7', PDFTests().reader(source))
        result = extract_with_ai(text, True, app.LABELS, config=CONFIG, opener=Mock(return_value=reply()))
        self.assertTrue(result['skills'])
        self.assertEqual(result['unverified_fields'], [])
