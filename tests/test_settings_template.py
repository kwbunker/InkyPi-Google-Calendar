"""Renders the settings page in each sign-in state. Needs jinja2, which InkyPi installs."""
import os
import unittest

from jinja2 import Environment, FileSystemLoader, select_autoescape

PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "..", "google_calendar")


def render(**params):
    env = Environment(loader=FileSystemLoader(PLUGIN_DIR), autoescape=select_autoescape(["html"]))
    defaults = {
        "signed_in": False,
        "has_client": False,
        "auth_url": None,
        "available_calendars": [],
        "calendar_error": None,
        "locale_map": {"en": "English"},
    }
    return env.get_template("settings.html").render({**defaults, **params})


class SettingsTemplateTests(unittest.TestCase):
    def test_first_step_asks_for_the_credentials_file(self):
        html = render()
        self.assertIn('id="credentialsFile"', html)
        self.assertIn("publish the app to Production", html)
        self.assertNotIn("authResponse", html)
        self.assertNotIn("<details>", html)

    def test_second_step_shows_the_sign_in_link(self):
        html = render(has_client=True, auth_url="https://accounts.google.com/o?a=1&b=2")
        self.assertIn('href="https://accounts.google.com/o?a=1&amp;b=2"', html)
        self.assertIn('name="authResponse"', html)
        self.assertIn("Use a different credentials file", html)

    def test_signed_in_lists_calendars_with_names_escaped(self):
        html = render(signed_in=True, has_client=True, available_calendars=[
            {"id": "a@b", "summary": "<Family> & Co", "backgroundColor": "#123456", "primary": True},
        ])
        self.assertIn("Signed in to Google Calendar", html)
        self.assertIn("&lt;Family&gt; &amp; Co", html)
        self.assertIn('name="calendarIds[]" value="a@b"', html)
        self.assertIn('data-primary="true"', html)
        self.assertNotIn("authResponse", html)

    def test_only_one_credentials_field_in_every_state(self):
        for params in ({}, {"has_client": True, "auth_url": "x"}, {"signed_in": True, "has_client": True}):
            self.assertEqual(render(**params).count('name="credentialsContent"'), 1, params)

    def test_choices_are_protected_from_the_form_reset(self):
        # InkyPi resets the form after Add to Playlist, which once saved an instance with no calendars.
        html = render(signed_in=True, has_client=True)
        self.assertIn('id="gcalSettings"', html)
        self.assertIn("keepChoicesThroughReset();", html)
        self.assertIn('id="gcalNoneSelected"', html)
        self.assertLess(html.index('name="fontSize"'), html.index("</div>\n</div>\n</div>\n\n<style>"))

    def test_a_calendar_error_is_shown(self):
        html = render(signed_in=True, has_client=True, calendar_error="Could not reach Google")
        self.assertIn("Could not reach Google", html)


if __name__ == "__main__":
    unittest.main()
