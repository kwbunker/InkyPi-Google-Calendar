"""Google sign-in, Calendar API calls, and the date and colour logic.

Uses plain HTTP so the plugin adds no packages and stays light on a 512 MB Pi.
Nothing here imports InkyPi, so it can be tested on its own.
"""
import colorsys
import json
import logging
import os
import secrets
import time
from datetime import datetime, time as day_start, timedelta
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
REDIRECT_URI = "http://localhost"
TIMEOUT_SECONDS = 30

# The panel's six inks, plus orange, which it mixes from red and yellow.
INKY_COLORS = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "yellow": "#FFFF00",
    "green": "#00FF00",
    "blue": "#0000FF",
    "orange": "#FF8000",
}

# Google's fixed per-event colours (colorId), mapped to the panel's colours.
EVENT_COLORS = {
    "1": "blue",     # Lavender
    "2": "green",    # Sage
    "3": "blue",     # Grape
    "4": "red",      # Flamingo
    "5": "yellow",   # Banana
    "6": "orange",   # Tangerine
    "7": "blue",     # Peacock
    "8": "white",    # Graphite
    "9": "blue",     # Blueberry
    "10": "green",   # Basil
    "11": "red",     # Tomato
}


class AuthRequired(RuntimeError):
    """The user needs to sign in, or sign in again, from the plugin's settings page."""


def _send(method, url, **kwargs):
    try:
        return requests.request(method, url, timeout=TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as error:
        raise RuntimeError(f"Could not reach Google: {type(error).__name__}") from error


def _google_error(response):
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error")
    if isinstance(error, dict):
        return error.get("message") or f"HTTP {response.status_code}"
    return body.get("error_description") or error or f"HTTP {response.status_code}"


class GoogleAuth:
    """Handles Google sign-in and keeps its files in state_dir, readable only by the service."""

    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.client_path = os.path.join(state_dir, "client.json")
        self.token_path = os.path.join(state_dir, "token.json")
        self.state_path = os.path.join(state_dir, "auth_state.json")

    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as file:
                return json.load(file)
        except (FileNotFoundError, ValueError):
            return None

    def _write(self, path, data):
        os.makedirs(self.state_dir, mode=0o700, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file)

    def _remove(self, path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    def has_client(self):
        return self._read(self.client_path) is not None

    def is_signed_in(self):
        return self._read(self.token_path) is not None

    def save_client(self, credentials_json):
        """Stores the OAuth client from the JSON file Google Cloud Console provides."""
        try:
            installed = json.loads(credentials_json).get("installed")
        except (ValueError, AttributeError):
            raise RuntimeError("That file isn't valid JSON. Download it again from Google Cloud Console.") from None
        if not installed or not installed.get("client_id") or not installed.get("client_secret"):
            raise RuntimeError("That isn't a Desktop app credentials file. Create an OAuth client of type 'Desktop app'.")
        self._write(self.client_path, {
            "client_id": installed["client_id"],
            "client_secret": installed["client_secret"],
        })
        self._remove(self.token_path)
        self._remove(self.state_path)

    def authorization_url(self):
        client = self._read(self.client_path)
        if not client:
            raise AuthRequired("Upload your Google credentials file first.")
        saved = self._read(self.state_path)
        state = saved["state"] if saved else secrets.token_urlsafe(24)
        if not saved:
            self._write(self.state_path, {"state": state})
        return AUTH_URI + "?" + urlencode({
            "client_id": client["client_id"],
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })

    def complete_sign_in(self, pasted):
        """Finishes sign-in from the localhost address Google redirected to, or from a bare code."""
        client = self._read(self.client_path)
        if not client:
            raise AuthRequired("Upload your Google credentials file first.")
        code = self._code_from(pasted)
        response = _send("POST", TOKEN_URI, data={
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if not response.ok:
            raise RuntimeError(f"Google refused the sign-in: {_google_error(response)}")
        token = response.json()
        if not token.get("refresh_token"):
            raise RuntimeError("Google didn't provide a long-lived token. Remove this app's access in your Google account, then sign in again.")
        self._save_token(token, token["refresh_token"])
        self._remove(self.state_path)

    def _code_from(self, pasted):
        pasted = (pasted or "").strip()
        if not pasted:
            raise RuntimeError("Paste the address from your browser first.")
        if "code=" not in pasted and "error=" not in pasted:
            return pasted
        query = parse_qs(urlparse(pasted).query)
        if query.get("error"):
            raise RuntimeError(f"Google reported: {query['error'][0]}")
        saved = self._read(self.state_path)
        if not saved or query.get("state", [None])[0] != saved["state"]:
            raise RuntimeError("That address came from an older sign-in link. Reload this page and use the current link.")
        if not query.get("code"):
            raise RuntimeError("That address has no sign-in code in it.")
        return query["code"][0]

    def _save_token(self, token, refresh_token):
        self._write(self.token_path, {
            "access_token": token["access_token"],
            "refresh_token": refresh_token,
            "expires_at": time.time() + int(token.get("expires_in", 3600)),
        })

    def access_token(self):
        token = self._read(self.token_path)
        if not token:
            raise AuthRequired("Sign in to Google from this plugin's settings page.")
        if token["expires_at"] - 60 > time.time():
            return token["access_token"]
        client = self._read(self.client_path)
        if not client:
            raise AuthRequired("Upload your Google credentials file again.")
        response = _send("POST", TOKEN_URI, data={
            "refresh_token": token["refresh_token"],
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "grant_type": "refresh_token",
        })
        if response.status_code in (400, 401) and _google_error_code(response) in ("invalid_grant", "unauthorized_client"):
            self._remove(self.token_path)
            raise AuthRequired(
                "Google sign-in has expired. Sign in again from this plugin's settings page. "
                "If this happens every 7 days, your Google Cloud app is still in Testing mode: publish it to Production."
            )
        if not response.ok:
            raise RuntimeError(f"Could not renew Google sign-in: {_google_error(response)}")
        refreshed = response.json()
        self._save_token(refreshed, refreshed.get("refresh_token") or token["refresh_token"])
        return refreshed["access_token"]

    def expire_access_token(self):
        token = self._read(self.token_path)
        if token:
            token["expires_at"] = 0
            self._write(self.token_path, token)


def _google_error_code(response):
    try:
        return response.json().get("error")
    except ValueError:
        return None


class CalendarClient:
    def __init__(self, auth):
        self.auth = auth

    def _get(self, path, params=None):
        response = None
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
            response = _send("GET", API_BASE + path, headers=headers, params=params)
            if response.status_code != 401 or attempt == 2:
                break
            self.auth.expire_access_token()
        if not response.ok:
            raise RuntimeError(f"Google Calendar returned an error: {_google_error(response)}")
        return response.json()

    def _get_all_pages(self, path, params):
        params = dict(params)
        items = []
        while True:
            page = self._get(path, params)
            items.extend(page.get("items", []))
            if not page.get("nextPageToken"):
                return items
            params["pageToken"] = page["nextPageToken"]

    def list_calendars(self):
        return self._get_all_pages("/users/me/calendarList", {"minAccessRole": "reader"})

    def list_events(self, calendar_id, start, end):
        return self._get_all_pages(f"/calendars/{quote(calendar_id, safe='')}/events", {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
        })


def fetch_events(client, calendar_ids, tz, start, end):
    """Returns events for FullCalendar. One failing calendar is logged; all failing raises."""
    calendars = {calendar["id"]: calendar for calendar in client.list_calendars()}
    events = []
    failures = 0
    for calendar_id in calendar_ids:
        default_color = palette_name_for_hex(calendars.get(calendar_id, {}).get("backgroundColor"))
        try:
            items = client.list_events(calendar_id, start, end)
        except AuthRequired:
            raise
        except RuntimeError as error:
            logger.warning(f"Could not read a calendar: {error}")
            failures += 1
            continue
        events.extend(
            to_fullcalendar_event(item, default_color, tz)
            for item in items
            if item.get("status") != "cancelled"
        )
    if failures and failures == len(calendar_ids):
        raise RuntimeError("Could not read any of the selected calendars. Check the logs.")
    return events


def to_fullcalendar_event(item, default_color, tz):
    background = INKY_COLORS[EVENT_COLORS.get(item.get("colorId"), default_color)]
    all_day = "date" in item["start"]
    if all_day:
        # Google and FullCalendar both treat an all-day event's end date as exclusive.
        start, end = item["start"]["date"], item["end"]["date"]
    else:
        start = _local_time_string(item["start"]["dateTime"], tz)
        end = _local_time_string(item["end"]["dateTime"], tz)
    return {
        "title": item.get("summary") or "(No title)",
        "start": start,
        "end": end,
        "allDay": all_day,
        "backgroundColor": background,
        "textColor": contrast_color(background),
        "description": item.get("description", ""),
        "location": item.get("location", ""),
    }


def _local_time_string(value, tz):
    # The page renders in UTC with no offsets, so times show exactly as written here.
    return datetime.fromisoformat(value).astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")


def palette_name_for_hex(hex_color, fallback="blue"):
    """Maps a calendar's colour to the panel by hue, so pale colours don't all become white."""
    try:
        value = hex_color.lstrip("#")
        red, green, blue = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (AttributeError, ValueError):
        return fallback
    hue, saturation, brightness = colorsys.rgb_to_hsv(red, green, blue)
    if saturation < 0.15:
        return "white" if brightness >= 0.5 else "black"
    degrees = hue * 360
    if degrees < 15 or degrees >= 320:
        return "red"
    if degrees < 45:
        return "orange"
    if degrees < 70:
        return "yellow"
    if degrees < 170:
        return "green"
    return "blue"


def contrast_color(hex_color):
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return "#000000" if (red * 299 + green * 587 + blue * 114) / 1000 >= 150 else "#ffffff"


def week_start(today, first_day):
    """first_day uses FullCalendar's numbering, where Sunday is 0."""
    return today - timedelta(days=(today.isoweekday() % 7 - first_day) % 7)


def view_range(view, now, tz, first_day=0, previous_days=True):
    """Returns the time-zone-aware range to fetch. Google rejects times with no offset."""
    today = now.date()

    def midnight(day):
        return tz.localize(datetime.combine(day, day_start.min))

    if view == "timeGridDay":
        first, days = today, 1
    elif view == "timeGridWeek":
        first, days = (week_start(today, first_day) if previous_days else today), 7
    elif view == "timeGrid2Week":
        first, days = week_start(today, first_day), 14
    elif view == "dayGridMonth":
        first, days = today.replace(day=1) - timedelta(days=7), 49
    elif view == "listMonth":
        first, days = today, 35
    else:
        raise ValueError(f"Unknown view: {view}")
    return midnight(first), midnight(first + timedelta(days=days))
