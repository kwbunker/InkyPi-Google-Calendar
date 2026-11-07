"""Renders the settings page in each sign-in state. Needs jinja2, which InkyPi installs."""
import os
import sys
import unittest

from jinja2 import Environment, FileSystemLoader, select_autoescape

PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "..", "google_calendar")
sys.path.insert(0, PLUGIN_DIR)

import calendar_api  # noqa: E402


def render(**params):
    env = Environment(loader=FileSystemLoader(PLUGIN_DIR), autoescape=select_autoescape(["html"]))
    defaults = {
        "signed_in": False,
        "has_client": False,
        "auth_url": None,
        "available_calendars": [],
        "calendar_error": None,
        "locale_map": {"en": "English"},
        "color_guide": calendar_api.color_guide(),
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

    def test_each_calendar_shows_its_panel_color(self):
        html = render(signed_in=True, has_client=True, available_calendars=[
            {"id": "a", "summary": "Meals", "backgroundColor": "#cabdbf", "panel": calendar_api.panel_color("white")},
            {"id": "b", "summary": "Home", "backgroundColor": "#ffad46", "panel": calendar_api.panel_color("orange")},
        ])
        self.assertIn('background-color: #f0f0f0; color: #000000" title="Panel color', html)
        self.assertIn('background-color: #b68349; color: #000000" title="Panel color', html)

    def test_color_guide_lists_each_panel_color_and_its_google_colors(self):
        html = render(signed_in=True, has_client=True)
        for name in ("Red", "Orange", "Yellow", "Green", "Blue", "White", "Black", "Tomato", "Tangerine", "Graphite"):
            self.assertIn(name, html)
        self.assertIn("looks grainy", html)
        self.assertLess(html.index(">Tomato") if ">Tomato" in html else html.index("Tomato"), html.index("Banana"))

    def test_each_calendar_can_choose_a_panel_color(self):
        html = render(signed_in=True, has_client=True, available_calendars=[
            {"id": "a@b", "summary": "<Meals>", "backgroundColor": "#cabdbf", "panel": calendar_api.panel_color("white")},
        ])
        self.assertIn('name="calendarColor:a@b"', html)
        self.assertIn(">Suggested (White)</option>", html)
        self.assertIn('aria-label="Panel color for &lt;Meals&gt;"', html)
        for key in calendar_api.INKY_COLORS:
            self.assertIn(f'<option value="{key}"', html)
        self.assertTrue(f'name="{calendar_api.CALENDAR_COLOR_PREFIX}a@b"' in html)

    def test_each_calendar_can_choose_the_row_under_the_date(self):
        html = render(signed_in=True, has_client=True, available_calendars=[
            {"id": "a", "summary": "Meals", "backgroundColor": "#cabdbf", "panel": calendar_api.panel_color("white")},
        ])
        self.assertIn(f'<option value="{calendar_api.DATE_ROW}" data-name="Under date"', html)
        self.assertIn("Under the date (titles only)</option>", html)
        self.assertIn("only applies to the 2 Weeks layout", html)

    def test_each_panel_color_has_a_note_field(self):
        html = render(signed_in=True, has_client=True)
        for key in calendar_api.INKY_COLORS:
            self.assertIn(f'name="colorNote:{key}"', html)
        self.assertIn('aria-label="Note for Orange"', html)
        self.assertIn("don't appear on the panel", html)

    def test_notes_are_restored_and_survive_the_form_reset(self):
        html = render(signed_in=True, has_client=True)
        self.assertIn("input.value = saved[input.name] || '';", html)
        self.assertIn('input[type="color"], .gcal-color-note', html)

    def test_saved_colors_are_restored_on_the_page(self):
        html = render(signed_in=True, has_client=True)
        self.assertIn("select.value = saved[select.name] || '';", html)
        self.assertIn("showChosenColor(select);", html)

    def test_blank_form_says_it_isnt_your_saved_settings(self):
        html = render(signed_in=True, has_client=True)
        self.assertIn("This is a blank form", html)
        self.assertIn('href="/playlist"', html)

    def test_a_saved_entry_doesnt_show_the_blank_form_note(self):
        html = render(signed_in=True, has_client=True, plugin_instance="Kitchen")
        self.assertNotIn("This is a blank form", html)

    def test_first_time_setup_doesnt_show_the_blank_form_note(self):
        self.assertNotIn("This is a blank form", render())
        self.assertNotIn("This is a blank form", render(has_client=True, auth_url="https://example.com"))

    def test_color_guide_waits_until_signed_in(self):
        self.assertNotIn("Panel colors:", render())

    def test_page_text_follows_the_dark_mode_theme(self):
        html = render(signed_in=True, has_client=True)
        self.assertIn("#gcalSettings summary", html)
        self.assertIn("color: var(--text-primary);", html)
        self.assertNotIn("currentColor", html)

    def test_signed_in_lists_calendars_with_names_escaped(self):
        html = render(signed_in=True, has_client=True, available_calendars=[
            {"id": "a@b", "summary": "<Family> & Co", "backgroundColor": "#123456", "primary": True, "panel": calendar_api.panel_color("blue")},
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
