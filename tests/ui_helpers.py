"""Navigate the public scenario picker before exercising existing student workflows."""
def open_personal_profile(page, entry=None):
    # Existing workflow tests explicitly exercise the preserved synthetic demo.
    page.session_state['career_catalog_mode'] = 'Synthetic demo'
    page.button(key='scenario_explore').click().run()
    if entry:
        page.button(key='profile_' + entry).click().run()
    return page
