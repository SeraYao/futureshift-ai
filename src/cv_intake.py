"""Transient PDF intake, evidence review and explicit mapping to the existing questionnaire."""
from src.i18n import tr, display_text, translated_options, translate_error
from copy import deepcopy
import hashlib
import logging
import re
from time import monotonic
from typing import Any

from src.cv_client import AIConfig, extract_with_ai, redact_text, supports_education
from src.cv_pdf import CVError, extract_pdf
from src.scoring import normalize_0_4

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def render_cv_error(st: Any, message: str) -> None:
    """Keep the safe client diagnosis visible across reruns, with collapsed details."""
    st.warning(translate_error(message))
    with st.expander(tr('Technical error details'), expanded=False):
        status = re.search(r'AI HTTP error (\d{3})\.', message)
        if status:
            st.text(tr('HTTP status: ') + status[1])
        else:
            category = next((label for token, label in (
                ('SSL error', 'SSL'), ('timeout error', 'timeout'),
                ('connection error', 'connection'), ('configur', 'configuration'),
                ('response format', 'response format')) if token in message), 'validation')
            st.text(tr('Error category: ') + display_text(category))
        for detail in re.findall(r'(?:type|code): [a-z_]+\.|Request ID: [a-zA-Z0-9_-]+\.', message):
            st.text(detail)


def release_cv_upload(state: Any) -> None:
    """Remove the managed in-memory upload and rotate its widget, without saving PDF bytes."""
    reference = state.pop('cv_upload_ref', None)
    if reference:
        from streamlit.runtime import get_instance
        manager = get_instance().uploaded_file_mgr
        manager.remove_file(*reference)
    generation = state.get('cv_upload_generation', 0)
    state.pop(f'cv_pdf_upload_{generation}', None)
    state['cv_upload_generation'] = generation + 1


def clear_cv_review(state: Any) -> None:
    """Discard unconfirmed evidence and edit widgets, leaving the user's profile unchanged."""
    release_cv_upload(state)
    for key in list(state):
        if key in ('cv_review', 'cv_review_confirm', 'cv_upload_hash') or key.startswith(('cv_edit_', 'cv_rating_', 'cv_consent_')):
            del state[key]


def apply_cv_fields(state: Any, extraction: dict, education: dict, ratings: dict,
                    summaries: list[str], confirmed: bool) -> None:
    """Merge only explicitly confirmed supported fields; model skill mentions never imply levels."""
    if confirmed is not True:
        raise CVError('Confirm the reviewed fields before applying. Your questionnaire is unchanged.')
    supported = {item['field'] for group in ('skills', 'knowledge') for item in extraction[group]}
    if any(key not in supported for key in ratings):
        raise CVError('Only supported questionnaire fields can be applied here.')
    for value in ratings.values():
        if value is not None and normalize_0_4(value).value is None:
            raise CVError('Self-ratings must be integer values from 0 to 4.')
    evidence = {item['field']: item for item in extraction['education']}
    if any(key not in evidence or (value is not None and not supports_education(key, value, evidence[key]['evidence']))
           for key, value in education.items()):
        raise CVError('The edited education category is not supported by the quoted evidence. Fill it in manually instead.')
    if len(summaries) != len(extraction['experience']) or any(not isinstance(s, str) or len(s) > 160 for s in summaries):
        raise CVError('Keep each experience summary within 160 characters.')
    from src.pathway import switch_profile_workspace
    switch_profile_workspace(state, 'manual')
    draft = deepcopy(state.get('pathway_draft', {}))
    draft.pop('data_status', None)
    for key, value in {**education, **ratings}.items():
        if value is not None:
            draft[key] = value
            state.pop('pathway_' + key, None)
    context = deepcopy(extraction)
    for item, summary in zip(context['experience'], summaries):
        item['summary'] = redact_text(summary)
    state['pathway_cv_context'] = context
    state['pathway_draft'] = draft
    state.pop('pathway_confirmed', None)
    state['pathway_step'] = 1


def render_cv_context(st: Any, context: dict | None, labels: dict) -> None:
    """Expose confirmed evidence and non-scored experience notes, never an entire CV."""
    if not context:
        return
    with st.expander(tr('CV-supported context · not an ability assessment'), expanded=False):
        st.caption(tr('Only your explicit 0–4 self-ratings affect ability scoring. CV excerpts and experience notes do not add points. Interest questions must still be answered. These notes are not exported with plans.'))
        for group in ('education', 'skills', 'knowledge'):
            for item in context[group]:
                st.write(display_text(labels.get(item['field'], item['field'])) + tr(' · Evidence: ') + item['evidence'])
        for item in context['experience']:
            st.write(tr('Experience note: ') + item['summary'])
            st.caption(tr('Original evidence: ') + item['evidence'])


def render_cv_intake(st: Any, labels: dict, levels: tuple, *, expanded: bool = False) -> None:
    """Offer PDF upload and a consent-gated AI action on student entry/background pages."""
    with st.expander(tr('Upload a PDF CV'), expanded=expanded):
        st.caption(tr('Optional · selectable-text PDF only · up to 3 MB and 5 pages · no OCR. Keep using the questionnaire if parsing or AI is unavailable. No CV file is written to disk or logs. Uploads use temporary server memory; only reviewed structured fields and short evidence excerpts remain in this session.'))
        if st.session_state.get('cv_notice'):
            render_cv_error(st, st.session_state['cv_notice'])
        review = st.session_state.get('cv_review')
        if review is None:
            generation = st.session_state.get('cv_upload_generation', 0)
            uploaded = st.file_uploader(tr('Choose a PDF CV'), type=['pdf'], key=f'cv_pdf_upload_{generation}',
                                        max_upload_size=3)
            if uploaded is None:
                return
            digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
            if st.session_state.get('cv_upload_hash') != digest:
                st.session_state.pop('cv_notice', None)
                st.session_state['cv_upload_hash'] = digest
                st.session_state.pop(f'cv_consent_{generation}', None)
            if getattr(uploaded, 'file_id', None):
                from streamlit.runtime.scriptrunner import get_script_run_ctx
                ctx = get_script_run_ctx()
                if ctx:
                    st.session_state['cv_upload_ref'] = (ctx.session_id, uploaded.file_id)
            if st.button(tr('Cancel CV upload'), key='cv_cancel_upload'):
                clear_cv_review(st.session_state)
                st.rerun()
            parse_started = monotonic()
            try:
                text = extract_pdf(getattr(uploaded, 'name', ''), uploaded.getvalue())
            except CVError as exc:
                logger.warning('cv_intake stage=pdf_parse elapsed_ms=%d exception=CVError',
                               (monotonic() - parse_started) * 1000)
                st.error(translate_error(str(exc)))
                release_cv_upload(st.session_state)
                return
            logger.info('cv_intake stage=pdf_parse elapsed_ms=%d text_chars=%d',
                        (monotonic() - parse_started) * 1000, len(text))
            sanitized = redact_text(text)
            with st.expander(tr('Review text that would be sent'), expanded=False):
                st.text(sanitized)
            st.caption(tr('Local removal of common emails, phone numbers, URLs and address lines is best effort. Names or identifying details may remain: review the text before consenting. Only the first 8,000 redacted characters are sent. No raw PDF is sent to AI.'))
            try:
                AIConfig.from_env()
                configured = True
            except CVError as exc:
                configured = False
                st.info(translate_error(str(exc) + tr(' Continue with Fill in my profile; no profile was changed.')))
                render_cv_error(st, str(exc))
            consent = st.checkbox(tr('I agree to send the extracted, locally redacted CV text to the configured AI service for processing.'),
                                  key=f'cv_consent_{generation}', value=False)
            st.caption(tr('The provider may retain requests under its own policy. Do not continue unless you accept that policy. Nothing is sent by uploading or checking consent alone: the next button sends the request.'))
            def begin_extraction() -> None:
                st.session_state['cv_extract_pending'] = True
                st.session_state['cv_extract_busy'] = True

            st.button(tr('Extract supported fields with AI'), key='cv_extract',
                      disabled=not (consent and configured) or st.session_state.get('cv_extract_busy', False),
                      on_click=begin_extraction)
            if st.session_state.pop('cv_extract_pending', False):
                try:
                    st.session_state.pop('cv_notice', None)
                    st.session_state['cv_review'] = extract_with_ai(text, consent, labels)
                except CVError as exc:
                    st.session_state['cv_notice'] = str(exc)
                else:
                    release_cv_upload(st.session_state)
                finally:
                    st.session_state['cv_extract_busy'] = False
                st.rerun()
            return
        st.subheader(tr('Review CV-supported fields'))
        st.caption(tr('Evidence and quoted source text are shown in their original language.'))
        st.caption(tr('Edit supported categories and enter your own ability ratings. A CV mention is not a skill score. Missing fields remain unanswered; existing manual answers are retained unless you explicitly replace them.'))
        if review.get('unverified_fields'):
            st.warning(translate_error(tr('Unable to verify these AI fields; they were excluded: ') + ', '.join((display_text(labels.get(key, key)) for key in review['unverified_fields'])) + tr('. Fill them in manually in the questionnaire.')))
        for key, reason in review.get('verification_failures', {}).items():
            st.text(key + ': ' + translate_error(reason))
        education, ratings, summaries = {}, {}, []
        from src.pathway import BACKGROUND
        for item in review['education']:
            key = item['field']
            st.write(display_text(key) + tr(' · Evidence: ') + item['evidence'])
            options = (None, *BACKGROUND[key])
            education[key] = st.selectbox(display_text(key) + tr(' · CV review'), options, index=options.index(item['value']),
                                          key='cv_edit_' + key, format_func=translated_options(lambda value: value or 'Do not apply'))
        for group in ('skills', 'knowledge'):
            for item in review[group]:
                key = item['field']
                st.write(display_text(labels[key]) + tr(' · Evidence: ') + item['evidence'])
                ratings[key] = st.selectbox(tr('Your self-rating · ') + display_text(labels[key]) + ' (' + display_text(group) + ')',
                    tuple(range(5)), index=None, key='cv_rating_' + key,
                    format_func=translated_options(lambda value: f'{value} — {levels[value]}'))
        for index, item in enumerate(review['experience']):
            st.caption(tr('Original experience evidence: ') + item['evidence'])
            summaries.append(st.text_area(tr('Experience note · not scored'), value=item['summary'],
                                           max_chars=160, key=f'cv_edit_experience_{index}'))
        st.write(tr('Still unconfirmed — answer in the questionnaire: ') + ', '.join((display_text(labels.get(key, key)) for key in review['unconfirmed_fields'])))
        confirm = st.checkbox(tr('I confirm the reviewed fields and my own self-ratings.'), key='cv_review_confirm')
        if st.button(tr('Apply confirmed fields and continue questionnaire'), disabled=not confirm, key='cv_apply'):
            try:
                apply_cv_fields(st.session_state, review, education, ratings, summaries, confirm)
            except CVError as exc:
                st.error(translate_error(str(exc)))
            else:
                clear_cv_review(st.session_state)
                st.session_state.pop('cv_review_confirm', None)
                st.rerun()
        if st.button(tr('Cancel CV review'), key='cv_cancel_review'):
            clear_cv_review(st.session_state)
            st.session_state.pop('cv_review_confirm', None)
            st.rerun()
