import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta

import pytz
from PIL import Image

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.google_calendar.calendar_api import (
    AuthRequired,
    CalendarClient,
    DATE_ROW,
    GoogleAuth,
    INKY_COLORS,
    SetupRequired,
    chosen_calendar_colors,
    color_guide,
    fetch_events,
    ink_colors,
    palette_name_for_hex,
    panel_color,
    should_warn,
    split_date_row,
    view_range,
    warning_message,
    week_start,
)
from plugins.google_calendar.constants import FONT_SIZES, LOCALE_MAP
from plugins.google_calendar.panel_warning import add_warning_banner
from utils.app_utils import get_font, resolve_path

logger = logging.getLogger(__name__)

VIEWS = ("timeGridDay", "timeGridWeek", "timeGrid2Week", "dayGridMonth", "listMonth")


class GoogleCalendar(BasePlugin):
    def _auth(self):
        # Kept outside the plugin folder, which `inkypi plugin install` deletes on reinstall.
        return GoogleAuth(resolve_path(os.path.join("config", "google_calendar")))

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        template_params["locale_map"] = LOCALE_MAP
        template_params["color_guide"] = color_guide()

        auth = self._auth()
        signed_in = auth.is_signed_in()
        calendars = []
        calendar_error = None
        if signed_in:
            try:
                calendars = CalendarClient(auth).list_calendars()
            except AuthRequired:
                signed_in = False
            except RuntimeError as error:
                calendar_error = str(error)
        for calendar in calendars:
            calendar["panel"] = panel_color(palette_name_for_hex(calendar.get("backgroundColor")))

        template_params["has_client"] = auth.has_client()
        template_params["signed_in"] = signed_in
        template_params["available_calendars"] = calendars
        template_params["calendar_error"] = calendar_error
        template_params["auth_url"] = auth.authorization_url() if auth.has_client() and not signed_in else None
        return template_params

    def generate_image(self, settings, device_config):
        auth = self._auth()

        if not _is_saved_instance(settings, device_config):
            # Update Now: problems go to the web UI, and sign-in steps happen here because
            # plugins can't add their own web routes. Raising shows the message and leaves
            # the panel as it is.
            if settings.get("credentialsContent"):
                auth.save_client(settings["credentialsContent"])
                raise RuntimeError("Credentials saved. Reload this page for the next step.")
            if settings.get("authResponse"):
                auth.complete_sign_in(settings["authResponse"])
                raise RuntimeError("Signed in to Google. Reload this page to choose your calendars.")
            return self._render_calendar(settings, device_config, auth)

        # A scheduled refresh has no one watching, so a failure must never just leave
        # the panel looking current. That's why this catches everything.
        try:
            return self._render_calendar(settings, device_config, auth)
        except Exception as error:
            logger.exception("Google Calendar refresh failed")
            return self._image_after_failure(error, device_config, auth)

    def _render_calendar(self, settings, device_config, auth):
        calendar_ids = settings.get("calendarIds[]")
        if not calendar_ids:
            raise SetupRequired("No calendars are selected. Open this entry under Playlists and choose some.")

        view = settings.get("viewMode") or "timeGrid2Week"
        if view not in VIEWS:
            raise RuntimeError("Invalid view")

        dimensions = _dimensions(device_config)
        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)

        first_day = int(settings.get("weekStartDay") or 0)
        previous_days = settings.get("displayPreviousDays") == "true"
        start, end = view_range(view, now, tz, first_day, previous_days)
        chosen_colors = chosen_calendar_colors(settings)
        events, failed_calendars = fetch_events(
            CalendarClient(auth), calendar_ids, tz, start, end, chosen_colors, _palette(device_config)
        )
        logger.info(f"Rendering Google Calendar: view={view}, events={len(events)}")

        render_view = view
        if view == "timeGridWeek" and not previous_days:
            render_view = "timeGrid"

        # Whole hours only, because anything finer would redraw the panel more often than
        # the calendar changes. Views with no current-time line only depend on the date.
        current_hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
        shows_time_line = render_view in ("timeGridDay", "timeGridWeek", "timeGrid")
        content_key = self._content_key(
            settings, events, failed_calendars, dimensions, time_format,
            current_hour if shows_time_line else now.date(),
        )
        # With nothing changed, the last image is still right, including its "Updated" time.
        # That saves a Chromium render, and it means InkyPi won't redraw the panel.
        unchanged_image = self._reuse_image(auth, content_key, dimensions)
        if unchanged_image:
            logger.info("Google Calendar unchanged, reusing the last image")
            return unchanged_image

        updated = _format_moment(now, time_format)
        if failed_calendars:
            updated += f" ({failed_calendars} of {len(calendar_ids)} calendars failed)"

        # Only the two-week view has this row. Other views show these events as normal.
        date_row = None
        if view == "timeGrid2Week" and any(chosen_colors.get(calendar_id) == DATE_ROW for calendar_id in calendar_ids):
            events, date_row = split_date_row(events)

        first_week = week_start(now.date(), first_day)
        template_params = {
            "view": render_view,
            "events": events,
            "current_dt": current_hour.isoformat(),
            "first_day": first_day,
            "week_starts": [first_week.isoformat(), (first_week + timedelta(days=7)).isoformat()],
            "date_row": date_row,
            "updated": updated,
            "time_format": time_format,
            "plugin_settings": settings,
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal"), 1),
            "panel_scale": _panel_scale(dimensions),
        }

        image = self.render_image(dimensions, "google_calendar.html", "google_calendar.css", template_params)
        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        self._remember_image(auth, image, content_key)
        return image

    def _last_image_path(self, auth):
        return os.path.join(auth.state_dir, "last_image.png")

    def _last_key_path(self, auth):
        return os.path.join(auth.state_dir, "last_image.json")

    def _content_key(self, settings, events, failed_calendars, dimensions, time_format, moment):
        """A fingerprint of everything that affects the image, apart from the "Updated" time."""
        template_times = [
            os.path.getmtime(self.get_plugin_dir(os.path.join("render", name)))
            for name in ("google_calendar.html", "google_calendar.css")
        ]
        content = json.dumps(
            [settings, events, failed_calendars, list(dimensions), time_format, moment, template_times],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _reuse_image(self, auth, content_key, dimensions):
        path = self._last_image_path(auth)
        try:
            with open(self._last_key_path(auth), encoding="utf-8") as file:
                if json.load(file).get("key") != content_key:
                    return None
            with Image.open(path) as saved:
                if saved.size != tuple(dimensions):
                    return None
                image = saved.convert("RGB")
            # The file's time is when a refresh last succeeded, which failure warnings rely on.
            os.utime(path)
            return image
        except (OSError, ValueError):
            return None

    def _remember_image(self, auth, image, content_key):
        path = self._last_image_path(auth)
        temporary = path + ".tmp"
        try:
            os.makedirs(auth.state_dir, mode=0o700, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                image.save(file, "PNG")
            os.replace(temporary, path)
            descriptor = os.open(self._last_key_path(auth), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump({"key": content_key}, file)
        except OSError as error:
            logger.warning(f"Could not save the last calendar image: {error}")

    def _image_after_failure(self, error, device_config, auth):
        """Keeps the last good calendar, adding a warning once the failure is worth reporting."""
        dimensions = _dimensions(device_config)
        path = self._last_image_path(auth)
        last_image = None
        seconds_since_success = None
        last_updated = None
        try:
            modified = os.path.getmtime(path)
            with Image.open(path) as saved:
                if saved.size == tuple(dimensions):
                    last_image = saved.convert("RGB")
                    seconds_since_success = time.time() - modified
                    last_updated = _format_time(modified, device_config)
        except OSError:
            pass

        if last_image and not should_warn(error, seconds_since_success):
            return last_image
        base = last_image or Image.new("RGB", tuple(dimensions), "white")
        font = get_font("Jost", max(20, dimensions[0] // 50), "bold")
        return add_warning_banner(base, warning_message(error), last_updated, font)


def _is_saved_instance(settings, device_config):
    # InkyPi passes a saved playlist entry its own settings object, and Update Now a new one
    # built from the form. If that ever changes, this returns False and errors just raise.
    manager = device_config.get_playlist_manager()
    return any(entry.settings is settings for playlist in manager.playlists for entry in playlist.plugins)


# Inky Impression sizes whose only driver blends the same measured inks as the 13.3", so
# ink_colors prints as solid ink: 13.3", 4" Spectra, 5.7" and the older 4". The 7.3" isn't
# here because two drivers share 800x480, and the older one's inks would speckle.
MATCHED_INK_SIZES = {(1200, 1600), (400, 600), (448, 600), (400, 640)}


def _palette(device_config):
    """The driver's own ink colors on panels known to use them, and pure colors elsewhere."""
    is_inky = device_config.get_config("display_type", default="inky") == "inky"
    if not is_inky or tuple(sorted(device_config.get_resolution())) not in MATCHED_INK_SIZES:
        return INKY_COLORS
    image_settings = device_config.get_config("image_settings") or {}
    return ink_colors(image_settings.get("inky_saturation", 0.5))


def _panel_scale(dimensions):
    """How much smaller this panel is than the 13.3" one the two-week view was sized for.
    The tighter of its two sides decides, in either orientation, and it never enlarges."""
    long_side, short_side = max(dimensions), min(dimensions)
    return min(long_side / 1600, short_side / 1200, 1)


def _dimensions(device_config):
    dimensions = device_config.get_resolution()
    if device_config.get_config("orientation") == "vertical":
        dimensions = dimensions[::-1]
    return dimensions


def _format_time(timestamp, device_config):
    tz = pytz.timezone(device_config.get_config("timezone", default="America/New_York"))
    moment = datetime.fromtimestamp(timestamp, tz)
    return _format_moment(moment, device_config.get_config("time_format", default="12h"))


def _format_moment(moment, time_format):
    if time_format == "24h":
        clock = moment.strftime("%H:%M")
    else:
        clock = moment.strftime("%I:%M %p").lstrip("0").lower().replace(" ", "")
    return f"{moment:%b} {moment.day}, {clock}"
