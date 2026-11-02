"""What the plugin does when a refresh fails. Needs Pillow, and for the plugin-level tests,
InkyPi on the Python path. On a Pi, run from the repo root with:

PYTHONPATH=~/InkyPi/src /usr/local/inkypi/venv_inkypi/bin/python -m unittest discover -s tests
"""
import hashlib
import os
import stat
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "google_calendar"))

from panel_warning import add_warning_banner  # noqa: E402

try:
    import plugins.google_calendar.google_calendar as plugin_module
    from plugins.google_calendar.calendar_api import AuthRequired, GoogleAuth
except ImportError:
    plugin_module = None

SIZE = (800, 600)
RED = (255, 0, 0)


def digest(image):
    return hashlib.md5(image.tobytes()).hexdigest()


class WarningBannerTests(unittest.TestCase):
    def setUp(self):
        self.font = ImageFont.load_default(size=24)
        self.base = Image.new("RGB", SIZE, (0, 0, 255))

    def test_draws_along_the_bottom_and_keeps_the_rest(self):
        result = add_warning_banner(self.base, "Short message.", "Nov 1, 5:00pm", self.font)
        self.assertEqual(result.size, SIZE)
        self.assertEqual(result.getpixel((5, 0)), (0, 0, 255))
        self.assertEqual(result.getpixel((5, SIZE[1] - 2)), RED)

    def test_leaves_the_original_image_alone(self):
        before = digest(self.base)
        add_warning_banner(self.base, "Short message.", None, self.font)
        self.assertEqual(digest(self.base), before)

    def test_long_messages_wrap_instead_of_running_off_the_edge(self):
        short = add_warning_banner(self.base, "Short.", None, self.font)
        long = add_warning_banner(self.base, "word " * 60, None, self.font)

        def banner_height(image):
            return sum(1 for y in range(SIZE[1]) if image.getpixel((1, y)) == RED)

        self.assertGreater(banner_height(long), banner_height(short) * 3)
        rightmost_column = [long.getpixel((SIZE[0] - 2, y)) for y in range(SIZE[1])]
        self.assertTrue(all(pixel != (255, 255, 255) for pixel in rightmost_column))

    def test_same_failure_draws_the_same_image_so_the_panel_only_redraws_once(self):
        first = add_warning_banner(self.base, "Same.", "Nov 1, 5:00pm", self.font)
        second = add_warning_banner(self.base, "Same.", "Nov 1, 5:00pm", self.font)
        self.assertEqual(digest(first), digest(second))


@unittest.skipIf(plugin_module is None, "needs InkyPi on the Python path")
class PluginFailureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.auth = GoogleAuth(os.path.join(self.folder.name, "state"))
        patcher = patch.object(plugin_module.GoogleCalendar, "_auth", return_value=self.auth)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plugin = plugin_module.GoogleCalendar({"id": "google_calendar"})

        self.saved_settings = {"calendarIds[]": ["cal"], "viewMode": "timeGrid2Week"}
        self.no_calendars = {"viewMode": "timeGrid2Week"}
        playlist = SimpleNamespace(plugins=[
            SimpleNamespace(settings=self.saved_settings),
            SimpleNamespace(settings=self.no_calendars),
        ])
        config = {"timezone": "America/Denver", "time_format": "12h", "orientation": "horizontal"}
        self.device = SimpleNamespace(
            get_resolution=lambda: list(SIZE),
            get_config=lambda key, default=None: config.get(key, default),
            get_playlist_manager=lambda: SimpleNamespace(playlists=[playlist]),
        )
        self.calendar_image = Image.new("RGB", SIZE, (0, 255, 0))

    def succeed(self):
        with patch.object(plugin_module, "fetch_events", return_value=([], 0)), \
                patch.object(self.plugin, "render_image", return_value=self.calendar_image):
            return self.plugin.generate_image(self.saved_settings, self.device)

    def fail_with(self, error, settings=None):
        with patch.object(plugin_module, "fetch_events", side_effect=error):
            return self.plugin.generate_image(settings or self.saved_settings, self.device)

    def age_last_image(self, seconds):
        path = os.path.join(self.auth.state_dir, "last_image.png")
        moment = time.time() - seconds
        os.utime(path, (moment, moment))

    def has_banner(self, image):
        return image.getpixel((1, image.height - 2)) == RED

    def test_success_returns_the_calendar_and_remembers_it_privately(self):
        result = self.succeed()
        self.assertEqual(digest(result), digest(self.calendar_image))
        path = os.path.join(self.auth.state_dir, "last_image.png")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.auth.state_dir).st_mode), 0o700)

    def test_a_brief_outage_keeps_the_calendar_unchanged(self):
        self.succeed()
        result = self.fail_with(RuntimeError("Could not reach Google"))
        self.assertEqual(digest(result), digest(self.calendar_image))

    def test_a_long_outage_keeps_the_calendar_and_adds_a_warning(self):
        self.succeed()
        self.age_last_image(4 * 60 * 60)
        result = self.fail_with(RuntimeError("Could not reach Google"))
        self.assertTrue(self.has_banner(result))
        self.assertEqual(result.getpixel((5, 5)), (0, 255, 0))

    def test_an_expired_sign_in_warns_straight_away(self):
        self.succeed()
        self.assertTrue(self.has_banner(self.fail_with(AuthRequired("Sign in again"))))

    def test_a_saved_entry_with_no_calendars_warns_straight_away(self):
        # This is the failure that froze the panel overnight with no sign of a problem.
        self.succeed()
        result = self.plugin.generate_image(self.no_calendars, self.device)
        self.assertTrue(self.has_banner(result))
        self.assertEqual(result.getpixel((5, 5)), (0, 255, 0))

    def test_with_nothing_to_keep_showing_it_warns_on_a_blank_page(self):
        result = self.plugin.generate_image(self.no_calendars, self.device)
        self.assertTrue(self.has_banner(result))
        self.assertEqual(result.getpixel((5, 5)), (255, 255, 255))

    def test_a_rendering_failure_still_warns(self):
        self.succeed()
        self.age_last_image(4 * 60 * 60)
        with patch.object(plugin_module, "fetch_events", return_value=([], 0)), \
                patch.object(self.plugin, "render_image", return_value=None):
            result = self.plugin.generate_image(self.saved_settings, self.device)
        self.assertTrue(self.has_banner(result))

    def test_an_unexpected_error_still_warns(self):
        self.succeed()
        self.age_last_image(4 * 60 * 60)
        self.assertTrue(self.has_banner(self.fail_with(KeyError("surprise"))))

    def test_recovery_returns_to_the_normal_calendar(self):
        self.succeed()
        self.fail_with(AuthRequired("Sign in again"))
        self.assertFalse(self.has_banner(self.succeed()))

    def test_a_wrong_size_last_image_isnt_reused(self):
        self.succeed()
        Image.new("RGB", (10, 10), (0, 255, 0)).save(os.path.join(self.auth.state_dir, "last_image.png"))
        result = self.fail_with(AuthRequired("Sign in again"))
        self.assertEqual(result.size, SIZE)
        self.assertEqual(result.getpixel((5, 5)), (255, 255, 255))

    def test_update_now_still_shows_errors_in_the_web_ui(self):
        with self.assertRaisesRegex(RuntimeError, "No calendars"):
            self.plugin.generate_image({"viewMode": "timeGrid2Week"}, self.device)
        with patch.object(plugin_module, "fetch_events", side_effect=RuntimeError("Could not reach Google")):
            with self.assertRaisesRegex(RuntimeError, "Could not reach"):
                self.plugin.generate_image({"calendarIds[]": ["cal"]}, self.device)

    def test_sign_in_steps_only_run_from_update_now(self):
        settings = {"credentialsContent": "not json", "calendarIds[]": ["cal"]}
        with self.assertRaisesRegex(RuntimeError, "valid JSON"):
            self.plugin.generate_image(settings, self.device)
        self.saved_settings["credentialsContent"] = "not json"
        self.succeed()
        self.assertFalse(self.auth.has_client())

    def test_chosen_calendar_colours_reach_the_fetch(self):
        settings = {"calendarIds[]": ["a@b"], "calendarColor:a@b": "green", "calendarColor:c@d": "bogus"}
        with patch.object(plugin_module, "fetch_events", return_value=([], 0)) as fetch, \
                patch.object(self.plugin, "render_image", return_value=self.calendar_image):
            self.plugin.generate_image(settings, self.device)
        self.assertEqual(fetch.call_args.args[5], {"a@b": "green"})

    def test_one_failed_calendar_is_noted_beside_the_updated_date(self):
        with patch.object(plugin_module, "fetch_events", return_value=([], 1)), \
                patch.object(self.plugin, "render_image", return_value=self.calendar_image) as render:
            self.plugin.generate_image({**self.saved_settings, "calendarIds[]": ["a", "b"]}, self.device)
        self.assertIn("1 of 2 calendars failed", render.call_args.args[3]["updated"])


if __name__ == "__main__":
    unittest.main()
