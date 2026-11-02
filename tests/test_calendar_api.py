"""Run from the repo root with: python -m unittest discover -s tests

Needs requests and pytz, which InkyPi already installs. No network or InkyPi needed.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "google_calendar"))

import calendar_api  # noqa: E402
from calendar_api import (  # noqa: E402
    AuthRequired,
    CalendarClient,
    GoogleAuth,
    contrast_color,
    fetch_events,
    palette_name_for_hex,
    to_fullcalendar_event,
    view_range,
)

DENVER = pytz.timezone("America/Denver")
CLIENT_FILE = json.dumps({"installed": {"client_id": "id-1", "client_secret": "secret-1"}})


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.body = body if body is not None else {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self.body


class ViewRangeTests(unittest.TestCase):
    def test_every_view_returns_offsets_google_accepts(self):
        # Sending times with no offset is what made Google reject the old plugin's requests.
        now = DENVER.localize(datetime(2026, 11, 4, 15, 30))
        for view in ("timeGridDay", "timeGridWeek", "timeGrid2Week", "dayGridMonth", "listMonth"):
            for previous_days in (True, False):
                start, end = view_range(view, now, DENVER, 0, previous_days)
                self.assertIsNotNone(start.utcoffset(), view)
                self.assertRegex(start.isoformat(), r"[+-]\d\d:\d\d$", view)
                self.assertRegex(end.isoformat(), r"[+-]\d\d:\d\d$", view)

    def test_two_weeks_starts_on_sunday_by_default(self):
        now = DENVER.localize(datetime(2025, 10, 14, 9))
        start, end = view_range("timeGrid2Week", now, DENVER)
        self.assertEqual(start.date().isoformat(), "2025-10-12")
        self.assertEqual(end.date().isoformat(), "2025-10-26")

    def test_two_weeks_honours_a_monday_start(self):
        now = DENVER.localize(datetime(2025, 10, 12, 9))
        start, _ = view_range("timeGrid2Week", now, DENVER, first_day=1)
        self.assertEqual(start.date().isoformat(), "2025-10-06")

    def test_on_the_first_day_of_the_week_the_week_starts_today(self):
        now = DENVER.localize(datetime(2025, 10, 12, 23, 59))
        start, _ = view_range("timeGrid2Week", now, DENVER)
        self.assertEqual(start.date().isoformat(), "2025-10-12")

    def test_range_keeps_correct_offsets_across_a_clock_change(self):
        # US clocks went back on 2026-11-01, inside this range.
        now = DENVER.localize(datetime(2026, 10, 30, 12))
        start, end = view_range("timeGrid2Week", now, DENVER)
        self.assertEqual(start.isoformat(), "2026-10-25T00:00:00-06:00")
        self.assertEqual(end.isoformat(), "2026-11-08T00:00:00-07:00")

    def test_week_without_previous_days_starts_today(self):
        now = DENVER.localize(datetime(2025, 10, 15, 9))
        start, end = view_range("timeGridWeek", now, DENVER, 0, previous_days=False)
        self.assertEqual(start.date().isoformat(), "2025-10-15")
        self.assertEqual(end.date().isoformat(), "2025-10-22")

    def test_unknown_view_is_rejected(self):
        with self.assertRaises(ValueError):
            view_range("nonsense", DENVER.localize(datetime(2025, 10, 15)), DENVER)


class EventConversionTests(unittest.TestCase):
    def test_timed_event_converts_to_device_time_with_no_offset(self):
        event = to_fullcalendar_event({
            "summary": "Flight",
            "start": {"dateTime": "2025-10-12T16:45:00Z"},
            "end": {"dateTime": "2025-10-12T20:00:00Z"},
        }, "blue", DENVER)
        self.assertEqual(event["start"], "2025-10-12T10:45:00")
        self.assertEqual(event["end"], "2025-10-12T14:00:00")
        self.assertFalse(event["allDay"])

    def test_multi_day_all_day_event_keeps_its_end_date(self):
        # The old plugin dropped this, so a trip showed only on its first day.
        event = to_fullcalendar_event({
            "summary": "Trip",
            "start": {"date": "2025-10-21"},
            "end": {"date": "2025-10-26"},
        }, "blue", DENVER)
        self.assertTrue(event["allDay"])
        self.assertEqual((event["start"], event["end"]), ("2025-10-21", "2025-10-26"))

    def test_event_colour_wins_over_calendar_colour(self):
        event = to_fullcalendar_event({
            "colorId": "6",
            "start": {"date": "2025-10-21"},
            "end": {"date": "2025-10-22"},
        }, "blue", DENVER)
        self.assertEqual(event["backgroundColor"], "#FF8000")
        self.assertEqual(event["textColor"], "#000000")

    def test_event_without_a_colour_uses_the_calendar_colour(self):
        event = to_fullcalendar_event({
            "start": {"date": "2025-10-21"},
            "end": {"date": "2025-10-22"},
        }, "green", DENVER)
        self.assertEqual(event["backgroundColor"], "#00FF00")

    def test_unknown_colour_id_falls_back_to_the_calendar_colour(self):
        event = to_fullcalendar_event({
            "colorId": "99",
            "start": {"date": "2025-10-21"},
            "end": {"date": "2025-10-22"},
        }, "red", DENVER)
        self.assertEqual(event["backgroundColor"], "#FF0000")

    def test_missing_title_gets_a_placeholder(self):
        event = to_fullcalendar_event({"start": {"date": "2025-10-21"}, "end": {"date": "2025-10-22"}}, "blue", DENVER)
        self.assertEqual(event["title"], "(No title)")


class ColourTests(unittest.TestCase):
    def test_hue_mapping_agrees_with_every_google_event_colour(self):
        for color_id, color in calendar_api.EVENT_COLORS.items():
            self.assertEqual(palette_name_for_hex(color["hex"]), color["panel"], color_id)

    def test_guide_lists_every_panel_colour_and_every_google_colour_once(self):
        guide = calendar_api.color_guide()
        self.assertEqual({row["name"].lower() for row in guide}, set(calendar_api.INKY_COLORS))
        listed = [google["name"] for row in guide for google in row["google"]]
        self.assertEqual(sorted(listed), sorted(color["name"] for color in calendar_api.EVENT_COLORS.values()))

    def test_guide_matches_the_colour_events_actually_get(self):
        for row in calendar_api.color_guide():
            for color_id, color in calendar_api.EVENT_COLORS.items():
                if color in row["google"]:
                    event = to_fullcalendar_event({
                        "colorId": color_id,
                        "start": {"date": "2025-10-21"},
                        "end": {"date": "2025-10-22"},
                    }, "blue", DENVER)
                    self.assertEqual(event["backgroundColor"], row["hex"], color["name"])
                    self.assertEqual(event["textColor"], row["text"], color["name"])

    def test_ink_colours_are_the_drivers_exact_palette(self):
        # From _palette_blend in Pimoroni's inky_el133uf1 driver, at saturation 0.5.
        colors = calendar_api.ink_colors(0.5)
        self.assertEqual(colors["red"], "#cd2425")
        self.assertEqual(colors["yellow"], "#e7de23")
        self.assertEqual(colors["blue"], "#1e1dae")
        self.assertEqual(colors["green"], "#1dad23")

    def test_ink_colours_run_from_pure_to_measured(self):
        for name in ("red", "yellow", "green", "blue", "orange"):
            self.assertEqual(calendar_api.ink_colors(0)[name], calendar_api.INKY_COLORS[name].lower(), name)
            self.assertEqual(calendar_api.ink_colors(1)[name], calendar_api.PANEL_APPEARANCE[name], name)

    def test_orange_stays_halfway_between_red_and_yellow_inks(self):
        colors = calendar_api.ink_colors(0.5)
        red, yellow, orange = (calendar_api._rgb(colors[name]) for name in ("red", "yellow", "orange"))
        for low, high, middle in zip(red, yellow, orange):
            self.assertAlmostEqual(middle, (low + high) / 2, delta=1)

    def test_black_and_white_stay_pure_at_every_saturation(self):
        for saturation in (0, 0.5, 1):
            colors = calendar_api.ink_colors(saturation)
            self.assertEqual(colors["white"], "#FFFFFF")
            self.assertEqual(colors["black"], "#000000")

    def test_palette_changes_the_background_but_not_the_text_colour(self):
        event = to_fullcalendar_event(
            {"start": {"date": "2025-10-21"}, "end": {"date": "2025-10-22"}},
            "yellow", DENVER, calendar_api.ink_colors(1),
        )
        self.assertEqual(event["backgroundColor"], calendar_api.PANEL_APPEARANCE["yellow"])
        self.assertEqual(event["textColor"], contrast_color(calendar_api.INKY_COLORS["yellow"]))

    def test_guide_explains_the_colours_with_no_simple_match(self):
        notes = {row["name"]: row["note"] for row in calendar_api.color_guide()}
        self.assertIn("grainy", notes["Orange"])
        self.assertIn("No Google", notes["Black"])

    def test_pale_calendar_colours_keep_their_hue(self):
        self.assertEqual(palette_name_for_hex("#9a9cff"), "blue")
        self.assertEqual(palette_name_for_hex("#f691b2"), "red")

    def test_greys_become_black_or_white(self):
        self.assertEqual(palette_name_for_hex("#202124"), "black")
        self.assertEqual(palette_name_for_hex("#f1f3f4"), "white")

    def test_bad_or_missing_colour_uses_the_fallback(self):
        self.assertEqual(palette_name_for_hex(None), "blue")
        self.assertEqual(palette_name_for_hex("not-a-colour"), "blue")

    def test_text_colours_match_what_worked_on_the_panel(self):
        expected = {"red": "#ffffff", "yellow": "#000000", "orange": "#000000", "green": "#ffffff", "blue": "#ffffff"}
        for name, text in expected.items():
            self.assertEqual(contrast_color(calendar_api.INKY_COLORS[name]), text, name)


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.auth = GoogleAuth(os.path.join(self.folder.name, "state"))

    def sign_in(self):
        self.auth.save_client(CLIENT_FILE)
        with patch("calendar_api.requests.request", return_value=FakeResponse(200, {
            "access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600,
        })):
            self.auth.complete_sign_in("a-bare-code")


class SignInTests(AuthTestCase):
    def test_rejects_non_desktop_credentials(self):
        for bad in ('{"web": {"client_id": "x"}}', "not json", "[]", '{"installed": {"client_id": "x"}}'):
            with self.assertRaises(RuntimeError):
                self.auth.save_client(bad)
        self.assertFalse(self.auth.has_client())

    def test_sign_in_link_requests_a_long_lived_token_without_out_of_band(self):
        self.auth.save_client(CLIENT_FILE)
        query = parse_qs(urlparse(self.auth.authorization_url()).query)
        self.assertEqual(query["redirect_uri"], ["http://localhost"])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["scope"], [calendar_api.SCOPE])
        self.assertTrue(query["state"][0])

    def test_sign_in_link_stays_the_same_until_used(self):
        self.auth.save_client(CLIENT_FILE)
        self.assertEqual(self.auth.authorization_url(), self.auth.authorization_url())

    def test_completes_from_the_pasted_address(self):
        self.auth.save_client(CLIENT_FILE)
        state = parse_qs(urlparse(self.auth.authorization_url()).query)["state"][0]
        with patch("calendar_api.requests.request", return_value=FakeResponse(200, {
            "access_token": "a", "refresh_token": "r", "expires_in": 3600,
        })) as request:
            self.auth.complete_sign_in(f"  http://localhost/?state={state}&code=the-code&scope=x  ")
        sent = request.call_args.kwargs["data"]
        self.assertEqual(sent["code"], "the-code")
        self.assertEqual(sent["redirect_uri"], "http://localhost")
        self.assertTrue(self.auth.is_signed_in())
        self.assertFalse(os.path.exists(self.auth.state_path))

    def test_rejects_an_address_from_a_different_sign_in(self):
        self.auth.save_client(CLIENT_FILE)
        self.auth.authorization_url()
        with patch("calendar_api.requests.request") as request:
            with self.assertRaisesRegex(RuntimeError, "older sign-in"):
                self.auth.complete_sign_in("http://localhost/?state=wrong&code=the-code")
        request.assert_not_called()

    def test_reports_a_denied_sign_in(self):
        self.auth.save_client(CLIENT_FILE)
        self.auth.authorization_url()
        with self.assertRaisesRegex(RuntimeError, "access_denied"):
            self.auth.complete_sign_in("http://localhost/?error=access_denied")

    def test_refuses_a_sign_in_with_no_long_lived_token(self):
        self.auth.save_client(CLIENT_FILE)
        with patch("calendar_api.requests.request", return_value=FakeResponse(200, {"access_token": "a", "expires_in": 3600})):
            with self.assertRaisesRegex(RuntimeError, "long-lived"):
                self.auth.complete_sign_in("a-code")
        self.assertFalse(self.auth.is_signed_in())

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_secret_files_are_private(self):
        self.sign_in()
        for path in (self.auth.client_path, self.auth.token_path):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.auth.state_dir).st_mode), 0o700)


class TokenTests(AuthTestCase):
    def test_uses_the_current_token_without_a_network_call(self):
        self.sign_in()
        with patch("calendar_api.requests.request") as request:
            self.assertEqual(self.auth.access_token(), "access-1")
        request.assert_not_called()

    def test_renews_an_expired_token_and_keeps_the_refresh_token(self):
        self.sign_in()
        self.auth.expire_access_token()
        with patch("calendar_api.requests.request", return_value=FakeResponse(200, {"access_token": "access-2", "expires_in": 3600})) as request:
            self.assertEqual(self.auth.access_token(), "access-2")
        self.assertEqual(request.call_args.kwargs["data"]["refresh_token"], "refresh-1")
        with open(self.auth.token_path, encoding="utf-8") as file:
            self.assertEqual(json.load(file)["refresh_token"], "refresh-1")

    def test_revoked_sign_in_asks_the_user_to_sign_in_again(self):
        self.sign_in()
        self.auth.expire_access_token()
        with patch("calendar_api.requests.request", return_value=FakeResponse(400, {"error": "invalid_grant"})):
            with self.assertRaisesRegex(AuthRequired, "Testing mode"):
                self.auth.access_token()
        self.assertFalse(self.auth.is_signed_in())

    def test_a_network_failure_keeps_the_sign_in(self):
        self.sign_in()
        self.auth.expire_access_token()
        error = calendar_api.requests.ConnectionError("down")
        with patch("calendar_api.requests.request", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                self.auth.access_token()
        self.assertNotIsInstance(caught.exception, AuthRequired)
        self.assertTrue(self.auth.is_signed_in())

    def test_a_google_outage_keeps_the_sign_in(self):
        self.sign_in()
        self.auth.expire_access_token()
        with patch("calendar_api.requests.request", return_value=FakeResponse(503, {"error": "backendError"})):
            with self.assertRaises(RuntimeError):
                self.auth.access_token()
        self.assertTrue(self.auth.is_signed_in())


class CalendarClientTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        self.client = CalendarClient(self.auth)
        self.start, self.end = view_range("timeGrid2Week", DENVER.localize(datetime(2025, 10, 14)), DENVER)

    def test_event_request_is_filtered_by_time_with_offsets(self):
        with patch("calendar_api.requests.request", return_value=FakeResponse(200, {"items": []})) as request:
            self.client.list_events("me@gmail.com", self.start, self.end)
        params = request.call_args.kwargs["params"]
        self.assertEqual(params["timeMin"], "2025-10-12T00:00:00-06:00")
        self.assertEqual(params["timeMax"], "2025-10-26T00:00:00-06:00")
        self.assertEqual(params["singleEvents"], "true")

    def test_calendar_ids_are_url_encoded(self):
        with patch("calendar_api.requests.request", return_value=FakeResponse(200, {"items": []})) as request:
            self.client.list_events("en.usa#holiday@group.v.calendar.google.com", self.start, self.end)
        self.assertIn("/calendars/en.usa%23holiday%40group.v.calendar.google.com/events", request.call_args.args[1])

    def test_follows_every_page(self):
        pages = [
            FakeResponse(200, {"items": [{"id": "1"}], "nextPageToken": "next"}),
            FakeResponse(200, {"items": [{"id": "2"}]}),
        ]
        with patch("calendar_api.requests.request", side_effect=pages) as request:
            items = self.client.list_events("me", self.start, self.end)
        self.assertEqual([item["id"] for item in items], ["1", "2"])
        self.assertEqual(request.call_args_list[1].kwargs["params"]["pageToken"], "next")

    def test_retries_once_after_an_expired_token(self):
        responses = [
            FakeResponse(401, {"error": {"message": "expired"}}),
            FakeResponse(200, {"access_token": "access-2", "expires_in": 3600}),
            FakeResponse(200, {"items": [{"id": "1"}]}),
        ]
        with patch("calendar_api.requests.request", side_effect=responses):
            items = self.client.list_events("me", self.start, self.end)
        self.assertEqual(len(items), 1)

    def test_google_errors_are_reported(self):
        with patch("calendar_api.requests.request", return_value=FakeResponse(403, {"error": {"message": "Calendar API has not been used"}})):
            with self.assertRaisesRegex(RuntimeError, "has not been used"):
                self.client.list_calendars()


class FetchEventsTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        self.start, self.end = view_range("timeGrid2Week", DENVER.localize(datetime(2025, 10, 14)), DENVER)
        self.event = {"summary": "E", "start": {"date": "2025-10-14"}, "end": {"date": "2025-10-15"}}

    def respond(self, url_map):
        def fake(method, url, **kwargs):
            for fragment, response in url_map.items():
                if fragment in url:
                    return response
            raise AssertionError(url)
        return fake

    def test_uses_each_calendars_own_colour(self):
        routes = {
            "calendarList": FakeResponse(200, {"items": [
                {"id": "green-cal", "backgroundColor": "#51b749"},
                {"id": "red-cal", "backgroundColor": "#dc2127"},
            ]}),
            "green-cal": FakeResponse(200, {"items": [self.event]}),
            "red-cal": FakeResponse(200, {"items": [self.event]}),
        }
        with patch("calendar_api.requests.request", side_effect=self.respond(routes)):
            events, failures = fetch_events(CalendarClient(self.auth), ["green-cal", "red-cal"], DENVER, self.start, self.end)
        self.assertEqual([event["backgroundColor"] for event in events], ["#00FF00", "#FF0000"])
        self.assertEqual(failures, 0)

    def test_one_failing_calendar_doesnt_lose_the_others(self):
        routes = {
            "calendarList": FakeResponse(200, {"items": []}),
            "good-cal": FakeResponse(200, {"items": [self.event]}),
            "bad-cal": FakeResponse(404, {"error": {"message": "Not Found"}}),
        }
        with patch("calendar_api.requests.request", side_effect=self.respond(routes)):
            events, failures = fetch_events(CalendarClient(self.auth), ["bad-cal", "good-cal"], DENVER, self.start, self.end)
        self.assertEqual(len(events), 1)
        self.assertEqual(failures, 1)

    def test_all_calendars_failing_raises(self):
        routes = {
            "calendarList": FakeResponse(200, {"items": []}),
            "bad-cal": FakeResponse(404, {"error": {"message": "Not Found"}}),
        }
        with patch("calendar_api.requests.request", side_effect=self.respond(routes)):
            with self.assertRaisesRegex(RuntimeError, "any of the selected"):
                fetch_events(CalendarClient(self.auth), ["bad-cal"], DENVER, self.start, self.end)

    def test_cancelled_events_are_skipped(self):
        routes = {
            "calendarList": FakeResponse(200, {"items": []}),
            "cal": FakeResponse(200, {"items": [dict(self.event, status="cancelled"), self.event]}),
        }
        with patch("calendar_api.requests.request", side_effect=self.respond(routes)):
            events, _ = fetch_events(CalendarClient(self.auth), ["cal"], DENVER, self.start, self.end)
        self.assertEqual(len(events), 1)


class ChosenColourTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        self.start, self.end = view_range("timeGrid2Week", DENVER.localize(datetime(2025, 10, 14)), DENVER)
        self.plain = {"summary": "E", "start": {"date": "2025-10-14"}, "end": {"date": "2025-10-15"}}

    def fetch(self, items, chosen):
        def fake(method, url, **kwargs):
            if "calendarList" in url:
                return FakeResponse(200, {"items": [{"id": "cal", "backgroundColor": "#cabdbf"}]})
            return FakeResponse(200, {"items": items})
        with patch("calendar_api.requests.request", side_effect=fake):
            events, _ = fetch_events(CalendarClient(self.auth), ["cal"], DENVER, self.start, self.end, chosen)
        return events

    def test_reads_only_valid_choices_from_the_settings(self):
        chosen = calendar_api.chosen_calendar_colors({
            "calendarColor:a@b.com": "green",
            "calendarColor:suggested": "",
            "calendarColor:bad": "purple",
            "viewMode": "green",
        })
        self.assertEqual(chosen, {"a@b.com": "green"})

    def test_a_grey_calendar_is_white_until_a_colour_is_chosen(self):
        self.assertEqual(self.fetch([self.plain], {})[0]["backgroundColor"], "#FFFFFF")
        self.assertEqual(self.fetch([self.plain], {"cal": "green"})[0]["backgroundColor"], "#00FF00")

    def test_chosen_colour_sets_readable_text(self):
        self.assertEqual(self.fetch([self.plain], {"cal": "yellow"})[0]["textColor"], "#000000")
        self.assertEqual(self.fetch([self.plain], {"cal": "black"})[0]["textColor"], "#ffffff")

    def test_an_events_own_colour_still_wins(self):
        coloured = dict(self.plain, colorId="11")
        self.assertEqual(self.fetch([coloured], {"cal": "green"})[0]["backgroundColor"], "#FF0000")

    def test_a_choice_only_affects_its_own_calendar(self):
        self.assertEqual(self.fetch([self.plain], {"other": "green"})[0]["backgroundColor"], "#FFFFFF")

    def test_the_date_row_is_a_valid_choice(self):
        chosen = calendar_api.chosen_calendar_colors({"calendarColor:meals": calendar_api.DATE_ROW})
        self.assertEqual(chosen, {"meals": calendar_api.DATE_ROW})

    def test_only_date_row_calendars_are_marked(self):
        self.assertTrue(self.fetch([self.plain], {"cal": calendar_api.DATE_ROW})[0]["dateRow"])
        self.assertFalse(self.fetch([self.plain], {"cal": "green"})[0]["dateRow"])
        self.assertFalse(self.fetch([self.plain], {})[0]["dateRow"])

    def test_a_date_row_calendar_keeps_a_colour_for_layouts_without_the_row(self):
        self.assertEqual(self.fetch([self.plain], {"cal": calendar_api.DATE_ROW})[0]["backgroundColor"], "#FFFFFF")


class DateRowTests(unittest.TestCase):
    def row_event(self, title, start, end, all_day=True, in_row=True):
        return {"title": title, "start": start, "end": end, "allDay": all_day, "dateRow": in_row}

    def test_boxes_and_titles_are_separated(self):
        box = self.row_event("Dentist", "2026-11-03T10:00:00", "2026-11-03T11:00:00", all_day=False, in_row=False)
        dinner = self.row_event("Tacos", "2026-11-03", "2026-11-04")
        boxes, titles = calendar_api.split_date_row([box, dinner])
        self.assertEqual(boxes, [box])
        self.assertEqual(titles, {"2026-11-03": ["Tacos"]})

    def test_all_day_events_appear_on_each_day_but_not_their_exclusive_end(self):
        _, titles = calendar_api.split_date_row([self.row_event("Camping", "2026-11-07", "2026-11-10")])
        self.assertEqual(titles, {day: ["Camping"] for day in ("2026-11-07", "2026-11-08", "2026-11-09")})

    def test_a_month_boundary_is_handled(self):
        _, titles = calendar_api.split_date_row([self.row_event("Trip", "2026-11-30", "2026-12-02")])
        self.assertEqual(sorted(titles), ["2026-11-30", "2026-12-01"])

    def test_timed_events_only_appear_on_the_day_they_start(self):
        late = self.row_event("Late Dinner", "2026-11-03T22:00:00", "2026-11-04T01:00:00", all_day=False)
        _, titles = calendar_api.split_date_row([late])
        self.assertEqual(titles, {"2026-11-03": ["Late Dinner"]})

    def test_several_titles_on_a_day_keep_their_order(self):
        _, titles = calendar_api.split_date_row([
            self.row_event("Soup", "2026-11-05", "2026-11-06"),
            self.row_event("Bread", "2026-11-05", "2026-11-06"),
        ])
        self.assertEqual(titles, {"2026-11-05": ["Soup", "Bread"]})

    def test_events_with_no_mark_stay_boxes(self):
        plain = {"title": "E", "start": "2026-11-03", "end": "2026-11-04", "allDay": True}
        self.assertEqual(calendar_api.split_date_row([plain]), ([plain], {}))


class FailureDecisionTests(unittest.TestCase):
    def test_a_passing_failure_waits_out_the_grace_period(self):
        error = RuntimeError("Could not reach Google")
        self.assertFalse(calendar_api.should_warn(error, 0))
        self.assertFalse(calendar_api.should_warn(error, calendar_api.WARNING_GRACE_SECONDS - 1))
        self.assertTrue(calendar_api.should_warn(error, calendar_api.WARNING_GRACE_SECONDS))

    def test_a_failure_that_needs_a_person_warns_straight_away(self):
        self.assertTrue(calendar_api.should_warn(calendar_api.SetupRequired("No calendars"), 0))
        self.assertTrue(calendar_api.should_warn(AuthRequired("Sign in again"), 0))

    def test_with_no_earlier_success_there_is_nothing_to_keep_showing(self):
        self.assertTrue(calendar_api.should_warn(RuntimeError("Could not reach Google"), None))

    def test_messages_are_short_and_say_what_to_do(self):
        expired = AuthRequired("A long message about Testing mode and 7 days.")
        self.assertIn("Sign in again", calendar_api.warning_message(expired))
        self.assertNotIn("Testing mode", calendar_api.warning_message(expired))
        self.assertEqual(calendar_api.warning_message(calendar_api.SetupRequired("Choose some.")), "Choose some.")
        self.assertIn("Wi-Fi", calendar_api.warning_message(RuntimeError("HTTP 500 with secrets?")))
        self.assertNotIn("secrets", calendar_api.warning_message(RuntimeError("HTTP 500 with secrets?")))


if __name__ == "__main__":
    unittest.main()
