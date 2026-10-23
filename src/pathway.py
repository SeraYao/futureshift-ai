"""Student questionnaire and session-only confirmation flow; no external data access."""
from src.i18n import career_name, tr, display_text, table_text, translated_options, translate_error
from src.sdg import render_sdg_preview
from copy import deepcopy
from typing import Any, Callable

from src.cv_intake import render_cv_intake, render_cv_context, clear_cv_review
from src.evidence_reassessment import render_evidence_reassessment
from src.learning_plan import render_learning_plan
from src.plan_transfer import render_restore
from src.reassessment import begin_reassessment, store_assessment, render_comparison
from src.scoring import SCORING_VERSION, normalize_0_4, rank_roles

INTERESTS = (
    ('R1', 'I enjoy building a small working object.'),
    ('R2', 'I like testing how tools work in practice.'),
    ('I1', 'I enjoy looking for patterns in unfamiliar data.'),
    ('I2', 'I like comparing explanations for a puzzling result.'),
    ('A1', 'I enjoy expressing an idea through an original design.'),
    ('A2', 'I like trying several creative ways to tell a story.'),
    ('S1', 'I enjoy helping someone understand a difficult idea.'),
    ('S2', 'I like working with others to support their learning.'),
    ('E1', 'I enjoy presenting a proposal to win support.'),
    ('E2', 'I like bringing people together to start an initiative.'),
    ('C1', 'I enjoy organizing information into a clear system.'),
    ('C2', 'I like checking records for consistency and missing details.'),
)
DIMENSIONS = ('Realistic', 'Investigative', 'Artistic', 'Social', 'Enterprising', 'Conventional')
SKILLS = tuple(f'skill_{i:02}' for i in range(1, 12))
KNOWLEDGE = tuple(f'knowledge_{i:02}' for i in range(1, 8))
STEPS = ('Choose your identity', 'Background', 'Skills', 'Knowledge', 'Interests',
         'Goals & preferences', 'Confirm your profile', 'Career matches')
BACKGROUND = {
    'Identity': ('Current student', 'Recent graduate'),
    'Current or completed field of study': ('Computing', 'Engineering', 'Natural sciences',
        'Mathematics and statistics', 'Business and management', 'Social sciences',
        'Arts and humanities', 'Health', 'Education', 'Other'),
    'Highest/current study level': ('Certificate', 'Diploma', "Bachelor's", "Master's", 'Doctorate', 'Other'),
    'Practical exposure': ('No formal experience', 'Coursework', 'Personal project', 'Internship or work'),
}
PREFERENCES = {
    'Weekly learning time': ('3 hours', '5 hours', '8 hours', '10+ hours'),
    'Target plan length': ('4 weeks', '8 weeks', '12 weeks'),
    'Budget': ('Free only', 'Low cost acceptable'),
    'Preferred learning language': ('English', 'Bahasa Malaysia', 'Chinese'),
}
SDGS = ('No poverty', 'Zero hunger', 'Good health and well-being', 'Quality education',
        'Gender equality', 'Clean water and sanitation', 'Affordable and clean energy',
        'Decent work and economic growth', 'Industry, innovation and infrastructure',
        'Reduced inequalities', 'Sustainable cities and communities', 'Responsible consumption and production',
        'Climate action', 'Life below water', 'Life on land', 'Peace, justice and strong institutions',
        'Partnerships for the goals')


def scoring_errors(draft: dict) -> list[str]:
    """List every unanswered or invalid scored question without imputing zero."""
    errors = [key for key in (*SKILLS, *KNOWLEDGE)
              if normalize_0_4(draft.get(key)).value is None]
    for key, _ in INTERESTS:
        value = draft.get(key)
        if type(value) is not int or not 1 <= value <= 5:
            errors.append(key)
    return errors


def confirmed_profile(draft: dict) -> dict:
    """Convert the documented raw answers; reject incomplete scored responses."""
    errors = scoring_errors(draft)
    if errors:
        raise ValueError('Unanswered scoring questions: ' + ', '.join(errors))
    return {'data_status': 'synthetic' if draft.get('data_status') == 'synthetic' else 'user_entered_prototype',
            'skills': {key: draft[key] for key in SKILLS},
            'knowledge': {key: draft[key] for key in KNOWLEDGE},
            'riasec': [((draft[INTERESTS[i][0]] + draft[INTERESTS[i+1][0]]) / 2 - 1) / 4
                       for i in range(0, 12, 2)]}


def sample_answers() -> dict:
    """Create complete fictional student answers, including all 30 scored questions."""
    return {'data_status': 'synthetic',
            **dict(zip(SKILLS, (3, 2, 2, 2, 1, 2, 1, 2, 2, 3, 2))),
            **dict(zip(KNOWLEDGE, (3, 2, 2, 1, 1, 1, 2))),
            **dict(zip((key for key, _ in INTERESTS), (2, 3, 5, 4, 3, 2, 3, 3, 2, 3, 4, 4))),
            'Identity': 'Current student', 'Current or completed field of study': 'Computing',
            'Highest/current study level': "Bachelor's", 'Practical exposure': 'Coursework',
            'Optional career goal': 'Fictional example: explore data and software careers.',
            'Weekly learning time': '5 hours', 'Target plan length': '4 weeks',
            'Budget': 'Free only', 'Preferred learning language': 'English',
            'SDG preferences': ['4. Quality education']}


def goal_display(draft: dict) -> str:
    """Localize the authored sample narrative, never arbitrary user free text."""
    goal = draft.get('Optional career goal')
    if draft.get('data_status') == 'synthetic' and goal == sample_answers()['Optional career goal']:
        return tr('Fictional example: explore data and software careers.')
    return goal or tr('Not provided')


def switch_profile_workspace(state: Any, target: str) -> None:
    """Keep personal questionnaire drafts/results separate from the editable sample session."""
    if target not in ('manual', 'sample'):
        raise ValueError('Unknown profile workspace')
    active = state.get('profile_workspace', 'manual')
    if active == target:
        return
    workspaces = state.setdefault('profile_workspaces', {})
    keys = [key for key in state if key.startswith(('pathway_', 'learning_'))]
    buttons = {'pathway_start', 'pathway_sample', 'pathway_identity', 'pathway_back',
               'pathway_next', 'pathway_confirm', 'pathway_reassess'}
    workspaces[active] = deepcopy({key: state[key] for key in keys if key not in buttons})
    for key in keys:
        del state[key]
    for key, value in deepcopy(workspaces.get(target, {})).items():
        state[key] = value
    state['profile_workspace'] = target


def save_answer(state: Any, name: str) -> None:
    """Persist widget answers independently of Streamlit's hidden-widget cleanup."""
    state['pathway_draft'][name] = deepcopy(state['pathway_' + name])
    state.pop('pathway_confirmed', None)


def render_pathway(st: Any, labels: dict, levels: tuple,
                   load_demo: Callable, render_role: Callable,
                   official_loader: Callable | None = None, client_factory: Callable | None = None) -> None:
    """Guide a student through intake, explicit confirmation and synthetic matches."""
    st.session_state.setdefault('pathway_step', 0)
    st.session_state.setdefault('pathway_draft', {})
    step = st.session_state.pathway_step
    draft = st.session_state.pathway_draft
    if step == 0:
        st.header(tr('Let us get to know you'))
    if step != 0:
        st.caption(tr('No name, age, gender or contact details are required. Occupational requirements are synthetic; the results page lets you choose GitHub snapshots or synthetic demo trends.'))
    if draft.get('data_status') == 'synthetic':
        st.warning(tr('SAMPLE PROFILE · Synthetic student answers, including any edits to this example. Not real personal data or a real employment prediction.'))
    if step != 0:
        st.progress(step / 7, text=tr('Step {v0} of 8 · {v1}', v0=step + 1, v1=display_text(STEPS[step])))
        st.subheader(display_text(STEPS[step]))

    def field(name: str, options: tuple | None = None, label: str | None = None,
              kind: str = 'select', **kwargs: Any) -> None:
        """Restore a durable answer and persist edits immediately."""
        key = 'pathway_' + name
        if key not in st.session_state:
            st.session_state[key] = deepcopy(draft.get(name, [] if kind == 'multi' else '' if kind == 'text' else None))
        common = dict(key=key, on_change=save_answer, args=(st.session_state, name))
        if kind == 'text':
            st.text_area(display_text(label or name), **common)
        elif kind == 'multi':
            st.multiselect(display_text(label or name), options, max_selections=3,
                           placeholder=tr('Select up to three options'), **common, format_func=translated_options())
        elif kind == 'radio':
            st.radio(display_text(label or name), options, index=None, horizontal=True,
                     **common, format_func=translated_options(kwargs.pop('format_func', None)),
                     **kwargs)
        else:
            st.selectbox(display_text(label or name), options, index=None, **common,
                         placeholder=tr('Select an answer'),
                         format_func=translated_options(kwargs.pop('format_func', None)), **kwargs)

    def sample_entry(label: str = 'Try with a sample profile', *, describe: bool = True) -> None:
        """Expose the same isolated sample shortcut on identity and background pages."""
        if st.button(tr(label), key='pathway_sample'):
            switch_profile_workspace(st.session_state, 'sample')
            st.session_state.setdefault('pathway_draft', sample_answers())
            st.session_state.pathway_confirmed = confirmed_profile(st.session_state.pathway_draft)
            st.session_state.pathway_step = 7
            st.rerun()
        if describe:
            st.caption(tr('The sample is fictional, editable and kept separate from your own questionnaire answers.'))

    if step == 1:
        render_cv_intake(st, labels, levels)
        render_restore(st, load_demo, labels)
    elif step != 0:
        clear_cv_review(st.session_state)
    if step in (1, 6):
        render_cv_context(st, st.session_state.get('pathway_cv_context'), labels)
    if st.session_state.get('pathway_restored'):
        st.caption(tr('Restored from a local prototype plan file. Background and free-text answers were not exported; you may enter them again when reassessing. No live GitHub history was restored.'))
    if step == 0:
        if st.button(tr('Complete a CV questionnaire'), key='pathway_start'):
            switch_profile_workspace(st.session_state, 'manual')
            st.session_state.pathway_step = 1
            st.rerun()
        if st.button(tr('Recognize a PDF CV with AI'), key='profile_cv'):
            st.session_state['profile_entry'] = 'cv'
        sample_entry('Try a virtual example', describe=False)
        if st.button(tr('Restore a saved plan'), key='profile_restore'):
            st.session_state['profile_entry'] = 'restore'
        st.caption(tr('No name, age, gender or contact details are required. Occupational requirements are synthetic; the results page lets you choose GitHub snapshots or synthetic demo trends.'))
        st.caption(tr('The sample is fictional, editable and kept separate from your own questionnaire answers.'))
        if st.session_state.get('profile_entry') == 'cv':
            render_cv_intake(st, labels, levels, expanded=True)
        elif st.session_state.get('profile_entry') == 'restore':
            render_restore(st, load_demo, labels, expanded=True)
        return
    if step == 1:
        st.info(tr('Fill in your profile below, or skip the questionnaire using a complete synthetic sample.'))
        sample_entry()
        st.caption(tr('Background and optional career goal do not affect scores. No text parsing is enabled.'))
        for name, options in BACKGROUND.items():
            field(name, options, kind='radio' if name in ('Identity', 'Practical exposure') else 'select')
        field('Optional career goal', kind='text')
    elif step in (2, 3):
        st.caption(tr('0 = no exposure · 1 = basic awareness · 2 = applied with guidance · 3 = independently applied · 4 = advanced. Unanswered is not zero.'))
        st.caption(tr('Rate Mathematics separately as a skill and a knowledge area. Study field does not imply ability.'))
        for key in SKILLS if step == 2 else KNOWLEDGE:
            field(key, tuple(range(5)), labels[key], kind='radio',
                  help=tr('0 = no exposure · 1 = basic awareness · 2 = applied with guidance · 3 = independently applied · 4 = advanced. Unanswered is not zero.'))
            st.caption(tr('0 · No exposure → 4 · Advanced'))
            if draft.get(key) is None:
                st.caption(tr('Not answered'))
            st.divider()
    elif step == 4:
        st.caption(tr('Original exploration statements, not a diagnostic or validated interest test. 1 = strongly disagree · 2 = disagree · 3 = neutral · 4 = agree · 5 = strongly agree.'))
        for key, statement in INTERESTS:
            field(key, tuple(range(1, 6)), statement, kind='radio',
                  help=tr('Original exploration statements, not a diagnostic or validated interest test. 1 = strongly disagree · 2 = disagree · 3 = neutral · 4 = agree · 5 = strongly agree.'))
            st.caption(tr('1 · Strongly disagree → 5 · Strongly agree'))
            if draft.get(key) is None:
                st.caption(tr('Not answered'))
            st.divider()
    elif step == 5:
        st.caption(tr('Not scored. Weekly time can initialize a four-week practice plan after matching. Longer plans and SDG filtering are planned. Language preference does not change the interface.'))
        for name, options in PREFERENCES.items():
            field(name, options, kind='radio')
        field('SDG preferences', tuple(f'{i+1}. {name}' for i, name in enumerate(SDGS)), kind='multi')
    elif step == 6:
        errors = scoring_errors(draft)
        if errors:
            st.error(tr('{count} required questions remain unanswered.', count=len(errors)))
            st.error(translate_error(tr('Complete scoring questions before confirming: ') + ', '.join((display_text(labels.get(k, k)) for k in errors))))
        else:
            profile = confirmed_profile(draft)
            st.markdown(tr('#### Scored answers · review and return to edit'))
            for group, keys in (('Skills', SKILLS), ('Knowledge', KNOWLEDGE)):
                st.markdown(tr('#### {v0} · strongest self-ratings first', v0=display_text(group)))
                st.table(table_text([{'Area': labels[key], 'Your answer (0–4)': draft[key],
                           'Normalized (0–1)': draft[key] / 4}
                          for key in sorted(keys, key=lambda k: (-draft[k], k))]))
            st.markdown(tr('#### RIASEC results · scored'))
            st.table(table_text([{'Dimension': name, 'First answer (1–5)': draft[INTERESTS[i*2][0]],
                       'Second answer (1–5)': draft[INTERESTS[i*2+1][0]], 'Normalized': value}
                      for i, (name, value) in enumerate(zip(DIMENSIONS, profile['riasec']))]))
            if not any(profile['riasec']):
                st.warning(tr('All interest answers are 1: the zero vector prevents interest similarity and complete rankings. You may edit answers or confirm to inspect available coverage and gaps only.'))
            st.markdown(tr('#### Goals, background & preferences · not scored'))
            st.table(table_text([{'Field': key, 'Answer': value if isinstance(value, list) else str(value)
                       if value is not None else 'Not answered'}
                      for key, value in ((key, draft.get(key)) for key in
                       (*BACKGROUND, 'Optional career goal', *PREFERENCES, 'SDG preferences'))]))
            st.caption(tr('Open text, background, SDGs and learning preferences never add points. Weekly time can initialize the practice plan; it never changes matching scores. Only four-week plans are currently available, regardless of target plan length.'))
            st.info(tr('This pool uses three synthetic skill requirements and two knowledge requirements. Other answers are retained but have no requirements in this pool. All six interest dimensions enter scoring. GitHub trend snapshots can be used after confirmation.'))
            with st.expander(tr('Technical details'), expanded=False):
                _, roles, trends = load_demo()
                st.caption(tr('Scoring rules: {v0}. Fixed synthetic catalog and trend snapshot; no live refresh.', v0=SCORING_VERSION))
                st.json({'occupations': [{'code': role['code'], 'title': role['title'],
                         'topics': role['topics']} for role in roles['roles']],
                         'trend_snapshot': trends, 'confirmed_candidate': profile}, expanded=False)
            if st.button(tr('Confirm profile & view matches'), key='pathway_confirm'):
                st.session_state.pathway_confirmed = deepcopy(profile)
                st.session_state.pathway_step = 7
                st.rerun()
    elif step == 7:
        profile = st.session_state.get('pathway_confirmed')
        if profile is None:
            st.warning(tr('Review and confirm your profile before calculating matches.'))
        else:
            _, role_file, trend_file = load_demo()
            st.caption(tr('Your confirmed profile + synthetic occupational requirements. Trend evidence and its source are shown below; no official O*NET requirements are substituted.'))
            st.write(tr('Career goal: ') + goal_display(draft))
            current = st.session_state.get('pathway_assessment')
            if current is None or current['profile'] != profile or current['answers'] != draft:
                # Pin the synthetic inputs for a profile reassessment.
                if current is not None:
                    role_file, trend_file = current['roles'], current['trends']
                rows = rank_roles(profile, role_file['roles'], trend_file['topics'])
                old_time = current['answers'].get('Weekly learning time') if current else None
                current = store_assessment(st.session_state, profile, draft, rows, role_file, trend_file)
                if old_time != draft.get('Weekly learning time'):
                    st.session_state.pop('learning_hours', None)
            else:
                rows = current['rows']
                role_file, trend_file = current['roles'], current['trends']
            with st.expander(tr('Profile reassessment · fixed synthetic baseline')):
                render_comparison(st, st.session_state.get('pathway_previous'), current, labels)
            if st.button(tr('Update my profile and reassess'), key='pathway_reassess'):
                begin_reassessment(st.session_state)
                st.rerun()
            if official_loader is not None and client_factory is not None:
                rows = render_evidence_reassessment(st, current, official_loader, client_factory)
            st.caption(tr('Moderate = 85% personal fit + 15% trend; Fast = 65% personal fit + 35% trend. These are unvalidated sensitivity assumptions, not probabilities or employment forecasts.'))
            st.table(table_text([{
                'Career': career_name(row['code'], row['title']),
                'Personal fit': row['P'].value if row['P'].value is not None else 'Unavailable',
                'Trend signal': row['trend']['score'].value if row['trend']['score'].value is not None else 'Unavailable',
                'Moderate score': row['moderate'].value if row['moderate'].value is not None else 'Unavailable',
                'Fast score': row['fast'].value if row['fast'].value is not None else 'Unavailable',
                'Trend impact · Moderate': row['moderate'].value - row['P'].value if row['moderate'].value is not None else 'Unavailable',
                'Trend impact · Fast': row['fast'].value - row['P'].value if row['fast'].value is not None else 'Unavailable',
            } for row in rows]))
            for scenario, title in (('moderate', 'Moderate'), ('fast', 'Fast disruption')):
                st.markdown(tr('### {v0}', v0=display_text(title)))
                ranked = sorted((row for row in rows if row[scenario+'_rank'] is not None),
                                key=lambda row: row[scenario+'_rank'])
                if not ranked:
                    st.info(tr('No complete rankings available. Review the component reasons below.'))
                for row in ranked:
                    st.write(tr('{v0}. {v1} · {v2:.2f} / 100', v0=row[scenario + '_rank'], v1=career_name(row['code'], row['title']), v2=row[scenario].value))
                    render_sdg_preview(st, row['code'])
            by_code = {role['code']: role for role in role_file['roles']}
            for row in rows:
                with st.expander(career_name(row['code'], row['title']) + tr(' · Why this match?')):
                    render_role(st, row, by_code[row['code']], profile=profile,
                                real_trends=current.get('recommendation_source') == 'GitHub snapshots')
            st.caption(tr('Choose a career from the current results below. A career without a complete trend score can still have synthetic skill gaps, but has no complete evidence-based match score.'))
            st.caption(tr('Plan downloads retain the fixed synthetic comparison baseline and practice tasks; live GitHub rankings are not exported or restored. Evidence provenance remains available above.'))
            render_learning_plan(st, sorted(rows, key=lambda row: row['code']), by_code, labels, draft.get('Weekly learning time'),
                                 current, st.session_state.get('pathway_previous'))
            with st.expander(tr('Technical details'), expanded=False):
                st.json(profile, expanded=False)
    if st.button(tr('Return to identity selection'), key='pathway_identity'):
        st.session_state.pathway_step = 0
        st.rerun()
    left, right = st.columns(2)
    if left.button(tr('Back'), key='pathway_back'):
        st.session_state.pathway_step = step - 1
        st.rerun()
    if step < 6 and right.button(tr('Review profile') if step == 5 else tr('Next'), key='pathway_next'):
        errors = scoring_errors(draft) if step == 5 else []
        if errors:
            st.error(tr('{count} required questions remain unanswered.', count=len(errors)))
            st.error(translate_error(tr('Please answer these scoring questions: ') + ', '.join((display_text(labels.get(k, k)) for k in errors))))
        else:
            st.session_state.pathway_step = step + 1
            st.rerun()
