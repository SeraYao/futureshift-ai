"""Opt-in LIVE check: synthetic PDF + Streamlit UI + configured real AI, once.

Run from the project environment with AI_* already injected. This sends synthetic
text to the configured provider and can incur usage charges. No HTTP is mocked.
"""
from io import BytesIO
import argparse
import json
import logging
from pathlib import Path
import sys
from time import monotonic
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from streamlit.testing.v1 import AppTest

from src.cv_client import AIConfig


def synthetic_pdf(*, partial: bool = False) -> BytesIO:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 50 700 Td (Skills: Programming) Tj ET' if partial else
                    b"BT /F1 12 Tf 50 700 Td (Bachelor's degree in Computing) Tj "
                    b"0 -20 Td (Skills: Programming and Critical Thinking) Tj "
                    b"0 -20 Td (Knowledge: Mathematics) Tj ET")
    page[NameObject('/Contents')] = writer._add_object(stream)
    uploaded = BytesIO()
    writer.write(uploaded)
    uploaded.name = 'synthetic.pdf'
    return uploaded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partial', action='store_true', help='Use a skills-only CV and verify manual completion.')
    args = parser.parse_args()
    config = AIConfig.from_env()
    logging.basicConfig(level=logging.INFO, format='%(name)s %(message)s')
    current = [None]

    def upload(label, **kwargs):
        return current[0] if kwargs.get('key', '').startswith('cv_pdf_upload_') else None

    started = monotonic()
    # Only bridge the uploader (unsupported by AppTest); parsing, consent widgets,
    # request construction, TLS, HTTP and validation all use production code.
    with patch('streamlit.file_uploader', side_effect=upload):
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
        page.button(key='scenario_explore').click().run()
        page.button(key='profile_cv').click().run()
        initial = {'knowledge_02': 3, 'Highest/current study level': "Bachelor's"} if args.partial else {}
        page.session_state['pathway_draft'] = initial.copy()
        current[0] = synthetic_pdf(partial=args.partial)
        page.run()
        assert not page.exception
        assert page.session_state['pathway_draft'] == initial
        assert page.button(key='cv_extract').disabled  # Explicit consent required.
        next(box for box in page.checkbox if box.key.startswith('cv_consent_')).check().run()
        assert not page.button(key='cv_extract').disabled
        page.button(key='cv_extract').click().run(timeout=config.timeout_seconds + 30)
        assert not page.exception
        assert not page.session_state['cv_extract_busy']
        assert page.session_state['pathway_draft'] == initial
        if 'cv_review' not in page.session_state:
            print(json.dumps({'live_ui_success': False, 'elapsed_seconds': round(monotonic() - started, 3),
                              'retry_enabled': not page.button(key='cv_extract').disabled,
                              'safe_error': page.session_state.get('cv_notice')}))
            return 1
        review = page.session_state['cv_review']
        counts = {key: len(review[key]) for key in ('education', 'skills', 'knowledge', 'experience')}
        if args.partial:
            assert counts == {'education': 0, 'skills': 1, 'knowledge': 0, 'experience': 0}
            assert 'knowledge_01' in review['unconfirmed_fields']
        expected_education = {item['field']: item['value'] for item in review['education']}
        rating_fields = [item['field'] for group in ('skills', 'knowledge') for item in review[group]]
        assert page.button(key='cv_apply').disabled
        for key in rating_fields:
            page.selectbox(key='cv_rating_' + key).set_value(2).run()
        assert page.session_state['pathway_draft'] == initial
        page.checkbox(key='cv_review_confirm').check().run()
        assert page.session_state['pathway_draft'] == initial
        assert not page.button(key='cv_apply').disabled
        current[0] = None
        page.button(key='cv_apply').click().run()
        assert not page.exception
        draft = page.session_state['pathway_draft']
        assert all(draft[key] == value for key, value in expected_education.items())
        assert all(draft[key] == 2 for key in rating_fields)
        assert 'cv_review' not in page.session_state
        if args.partial:
            from src.pathway import SKILLS, KNOWLEDGE, INTERESTS, scoring_errors
            assert all(draft[key] == value for key, value in initial.items())
            assert scoring_errors(draft)
            page.session_state['pathway_step'] = 5
            page.run()
            page.button(key='pathway_next').click().run()
            assert page.session_state['pathway_step'] == 5
            assert page.error
            # Simulate explicit user choices in the existing questionnaire, never AI defaults.
            for step, fields, choice in ((2, SKILLS, 1), (3, KNOWLEDGE, 1),
                                         (4, tuple(key for key, _ in INTERESTS), 3)):
                page.session_state['pathway_step'] = step
                page.run()
                for key in fields:
                    if page.session_state['pathway_draft'].get(key) is None:
                        page.radio(key='pathway_' + key).set_value(choice).run()
                page.button(key='pathway_next').click().run()
                assert not page.exception
            page.button(key='pathway_next').click().run()
            assert page.session_state['pathway_step'] == 6
            assert not scoring_errors(page.session_state['pathway_draft'])
            assert page.button(key='pathway_confirm')
            assert all(page.session_state['pathway_draft'][key] == value for key, value in initial.items())
        print(json.dumps({'live_ui_success': True, 'elapsed_seconds': round(monotonic() - started, 3),
                          'timeout_seconds': config.timeout_seconds,
                          'profile_unchanged_before_confirmation': True,
                          'profile_updated_after_confirmation': True,
                          'manual_completion_verified': args.partial,
                          'verified_counts': counts}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
