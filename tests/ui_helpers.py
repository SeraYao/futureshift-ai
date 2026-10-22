"""Navigate the public scenario picker before exercising existing student workflows."""
def open_personal_profile(page):
    page.button(key='scenario_explore').click().run()
    return page
