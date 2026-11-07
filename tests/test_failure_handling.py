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
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
class PaletteTests(unittest.TestCase):
    def palette(self, resolution=(1600, 1200), **config):
        device = SimpleNamespace(
            get_resolution=lambda: list(resolution),
            get_config=lambda key, default=None: config.get(key, default),
        )
        return plugin_module._palette(device)

    def test_follows_the_devices_saturation_on_the_measured_panel(self):
        palette = self.palette(image_settings={"inky_saturation": 1.0})
        self.assertEqual(palette, plugin_module.ink_colors(1.0))

    def test_saturation_defaults_to_the_drivers_default(self):
        self.assertEqual(self.palette(), plugin_module.ink_colors(0.5))

    def test_portrait_panel_counts_as_the_same_panel(self):
        self.assertEqual(self.palette(resolution=(1200, 1600)), plugin_module.ink_colors(0.5))

    def test_other_panels_keep_pure_colors(self):
        self.assertEqual(self.palette(resolution=(800, 480)), plugin_module.INKY_COLORS)
        self.assertEqual(self.palette(resolution=(400, 300)), plugin_module.INKY_COLORS)
        self.assertEqual(self.palette(display_type="epd7in3e"), plugin_module.INKY_COLORS)

    def test_smaller_inky_impressions_with_the_same_inks_match_them(self):
        for size in ((600, 400), (400, 600), (600, 448), (640, 400)):
            self.assertEqual(self.palette(resolution=size), plugin_module.ink_colors(0.5), size)


@unittest.skipIf(plugin_module is None, "needs InkyPi on the Python path")
class PanelScaleTests(unittest.TestCase):
    def test_the_13_inch_panel_is_full_size_either_way_round(self):
        self.assertEqual(plugin_module._panel_scale((1600, 1200)), 1)
        self.assertEqual(plugin_module._panel_scale((1200, 1600)), 1)

    def test_a_smaller_panel_scales_by_its_tighter_side(self):
        self.assertAlmostEqual(plugin_module._panel_scale((800, 480)), 0.4)
        self.assertAlmostEqual(plugin_module._panel_scale((480, 800)), 0.4)
        self.assertAlmostEqual(plugin_module._panel_scale((640, 400)), 1 / 3)

    def test_a_larger_screen_is_never_enlarged(self):
        self.assertEqual(plugin_module._panel_scale((3840, 2160)), 1)

    def test_the_scale_reaches_the_template(self):
        params = {}
        device = SimpleNamespace(
            get_resolution=lambda: [800, 480],
            get_config=lambda key, default=None: {"timezone": "America/Denver"}.get(key, default),
            get_playlist_manager=lambda: SimpleNamespace(playlists=[]),
        )
        plugin = plugin_module.GoogleCalendar({"id": "google_calendar"})
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        auth = GoogleAuth(os.path.join(folder.name, "state"))
        with patch.object(plugin_module.GoogleCalendar, "_auth", return_value=auth), \
                patch.object(plugin_module, "fetch_events", return_value=([], 0)), \
                patch.object(plugin, "render_image", side_effect=lambda *args: params.update(args[3]) or Image.new("RGB", (800, 480))):
            plugin.generate_image({"calendarIds[]": ["cal"], "viewMode": "timeGrid2Week"}, device)
        self.assertAlmostEqual(params["panel_scale"], 0.4)


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
        # New events, because an unchanged calendar wouldn't render at all.
        with patch.object(plugin_module, "fetch_events", return_value=([{"title": "New"}], 0)), \
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

    def refresh(self, events=(), settings=None, now=None):
        """Runs a scheduled refresh and returns whether it rendered a new image."""
        settings = settings if settings is not None else self.saved_settings
        moment = now or plugin_module.pytz.timezone("America/Denver").localize(datetime(2026, 11, 2, 7, 14))
        clock = MagicMock(wraps=datetime)
        clock.now.return_value = moment
        with patch.object(plugin_module, "fetch_events", return_value=(list(events), 0)), \
                patch.object(plugin_module, "datetime", clock), \
                patch.object(self.plugin, "render_image", return_value=self.calendar_image) as render:
            self.last_result = self.plugin.generate_image(settings, self.device)
        self.last_render = render
        return render.called

    def date_row_events(self):
        return [
            {"title": "Dentist", "start": "2026-11-03T10:00:00", "end": "2026-11-03T11:00:00", "allDay": False, "dateRow": False},
            {"title": "Tacos", "start": "2026-11-03", "end": "2026-11-04", "allDay": True, "dateRow": True},
        ]

    def test_a_date_row_calendar_becomes_titles_in_the_two_week_view(self):
        settings = {"calendarIds[]": ["cal", "meals"], "viewMode": "timeGrid2Week", "calendarColor:meals": "dateRow"}
        self.refresh(events=self.date_row_events(), settings=settings)
        params = self.last_render.call_args.args[3]
        self.assertEqual(params["date_row"], {"2026-11-03": ["Tacos"]})
        self.assertEqual([event["title"] for event in params["events"]], ["Dentist"])

    def test_other_views_show_date_row_events_as_normal(self):
        settings = {"calendarIds[]": ["cal", "meals"], "viewMode": "dayGridMonth", "calendarColor:meals": "dateRow"}
        self.refresh(events=self.date_row_events(), settings=settings)
        params = self.last_render.call_args.args[3]
        self.assertIsNone(params["date_row"])
        self.assertEqual(len(params["events"]), 2)

    def test_no_date_row_calendar_means_no_row(self):
        self.refresh(events=[self.date_row_events()[0]])
        self.assertIsNone(self.last_render.call_args.args[3]["date_row"])

    def test_a_date_row_calendar_thats_no_longer_selected_means_no_row(self):
        settings = {"calendarIds[]": ["cal"], "viewMode": "timeGrid2Week", "calendarColor:meals": "dateRow"}
        self.refresh(settings=settings)
        self.assertIsNone(self.last_render.call_args.args[3]["date_row"])

    def test_a_new_dinner_renders_again(self):
        settings = {"calendarIds[]": ["cal", "meals"], "viewMode": "timeGrid2Week", "calendarColor:meals": "dateRow"}
        events = self.date_row_events()
        self.assertTrue(self.refresh(events=events, settings=settings))
        self.assertFalse(self.refresh(events=events, settings=settings))
        changed = [events[0], dict(events[1], title="Pizza")]
        self.assertTrue(self.refresh(events=changed, settings=settings))

    def test_the_stamp_includes_the_date_and_time(self):
        self.refresh()
        self.assertEqual(self.last_render.call_args.args[3]["updated"], "Nov 2, 7:14am")

    def test_a_24_hour_device_shows_a_24_hour_stamp(self):
        config = {"timezone": "America/Denver", "time_format": "24h"}
        self.device.get_config = lambda key, default=None: config.get(key, default)
        moment = plugin_module.pytz.timezone("America/Denver").localize(datetime(2026, 11, 2, 19, 5))
        self.refresh(now=moment)
        self.assertEqual(self.last_render.call_args.args[3]["updated"], "Nov 2, 19:05")

    def test_unchanged_calendar_reuses_the_image_so_the_panel_wont_redraw(self):
        tz = plugin_module.pytz.timezone("America/Denver")
        self.assertTrue(self.refresh(events=[{"title": "A"}]))
        first = digest(self.last_result)
        self.assertFalse(self.refresh(events=[{"title": "A"}], now=tz.localize(datetime(2026, 11, 2, 7, 29))))
        self.assertEqual(digest(self.last_result), first)
        self.assertFalse(self.refresh(events=[{"title": "A"}], now=tz.localize(datetime(2026, 11, 2, 23, 59))))

    def test_changed_events_render_again(self):
        self.refresh(events=[{"title": "A"}])
        self.assertTrue(self.refresh(events=[{"title": "B"}]))

    def test_a_new_day_renders_again(self):
        tz = plugin_module.pytz.timezone("America/Denver")
        self.refresh()
        self.assertTrue(self.refresh(now=tz.localize(datetime(2026, 11, 3, 0, 5))))

    def test_changed_settings_render_again(self):
        self.refresh()
        self.saved_settings["calendarColor:cal"] = "green"
        self.assertTrue(self.refresh())

    def test_changing_the_template_renders_again(self):
        original = self.plugin.get_plugin_dir
        self.refresh()
        with patch.object(self.plugin, "get_plugin_dir", side_effect=lambda path: original(path if "html" not in path else "plugin-info.json")):
            self.assertTrue(self.refresh())

    def test_a_view_with_a_time_line_renders_again_each_hour(self):
        tz = plugin_module.pytz.timezone("America/Denver")
        settings = self.saved_settings
        settings["viewMode"] = "timeGridDay"
        self.refresh()
        self.assertFalse(self.refresh(now=tz.localize(datetime(2026, 11, 2, 7, 45))))
        self.assertTrue(self.refresh(now=tz.localize(datetime(2026, 11, 2, 8, 0))))

    def test_reusing_the_image_counts_as_a_successful_refresh(self):
        # Otherwise a calendar that rarely changes would look like a long outage.
        self.refresh()
        self.age_last_image(4 * 60 * 60)
        self.refresh()
        result = self.fail_with(RuntimeError("Could not reach Google"))
        self.assertFalse(self.has_banner(result))

    def test_a_missing_or_corrupt_saved_image_renders_again(self):
        self.refresh()
        with open(os.path.join(self.auth.state_dir, "last_image.png"), "wb") as file:
            file.write(b"not an image")
        self.assertTrue(self.refresh())

    def test_a_corrupt_saved_key_renders_again(self):
        self.refresh()
        with open(os.path.join(self.auth.state_dir, "last_image.json"), "w", encoding="utf-8") as file:
            file.write("not json")
        self.assertTrue(self.refresh())

    def test_chosen_calendar_colors_reach_the_fetch(self):
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
