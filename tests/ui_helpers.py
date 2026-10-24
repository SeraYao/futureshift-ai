"""Navigate the public scenario picker before exercising existing student workflows."""
def open_personal_profile(page, entry=None):
    page.button(key='scenario_explore').click().run()
    if entry:
        page.button(key='profile_' + entry).click().run()
    return page
