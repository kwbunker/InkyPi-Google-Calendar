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
        # Hex values from Google's colors.get endpoint.
        google_event_hex = {
            "1": "#a4bdfc", "2": "#7ae7bf", "3": "#dbadff", "4": "#ff887c", "5": "#fbd75b", "6": "#ffb878",
            "7": "#46d6db", "8": "#e1e1e1", "9": "#5484ed", "10": "#51b749", "11": "#dc2127",
        }
        for color_id, hex_color in google_event_hex.items():
            self.assertEqual(palette_name_for_hex(hex_color), calendar_api.EVENT_COLORS[color_id], color_id)

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
            events = fetch_events(CalendarClient(self.auth), ["green-cal", "red-cal"], DENVER, self.start, self.end)
        self.assertEqual([event["backgroundColor"] for event in events], ["#00FF00", "#FF0000"])

    def test_one_failing_calendar_doesnt_lose_the_others(self):
        routes = {
            "calendarList": FakeResponse(200, {"items": []}),
            "good-cal": FakeResponse(200, {"items": [self.event]}),
            "bad-cal": FakeResponse(404, {"error": {"message": "Not Found"}}),
        }
        with patch("calendar_api.requests.request", side_effect=self.respond(routes)):
            events = fetch_events(CalendarClient(self.auth), ["bad-cal", "good-cal"], DENVER, self.start, self.end)
        self.assertEqual(len(events), 1)

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
            events = fetch_events(CalendarClient(self.auth), ["cal"], DENVER, self.start, self.end)
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
