"""Scenario navigation around the existing student workflow; no profile conversion."""
from typing import Any

from src.i18n import tr

SCENARIOS = (
    ('explore', 'Explore career directions', 'A starting point for students and recent graduates'),
    ('professional', 'Build skills or explore a career change', 'Grow in your current role or move into a new field'),
    ('team', 'Develop team capabilities', 'Employee training, talent development or team planning'),
)


def render_onboarding(st: Any) -> bool:
    """Return True only when the existing personal workflow should render."""
    state = st.session_state
    state.setdefault('onboarding_scenario', None)
    state.setdefault('onboarding_choose', state['onboarding_scenario'] is None)
    if state['onboarding_choose']:
        st.header(tr("Let's get started"))
        st.write(tr('Choose the direction that best fits your current needs.'))
        for code, title, description in SCENARIOS:
            if st.button(tr(title), key=f'scenario_{code}'):
                state['onboarding_scenario'] = code
                state['onboarding_choose'] = False
                st.rerun()
            st.caption(tr(description))
        return False
    if st.button(tr('Back to use cases'), key='onboarding_back'):
        state['onboarding_choose'] = True
        st.rerun()
    scenario = state['onboarding_scenario']
    if scenario == 'explore':
        return True
    if scenario == 'professional':
        st.header(tr('Build skills or explore a career change'))
        st.write(tr('Grow in your current role or move into a new field'))
        entries = ('Professional profile questionnaire', 'Upload a PDF CV', 'Try a professional sample profile')
    else:
        st.header(tr('Develop team capabilities'))
        st.write(tr('Employee training, talent development or team planning'))
        entries = ('Enter team development needs', 'Batch upload')
    st.info(tr('Coming soon'))
    for index, title in enumerate(entries):
        st.button(tr(title) + ' · ' + tr('Coming soon'),
                  key=f'planned_{scenario}_{index}', disabled=True)
    return False
