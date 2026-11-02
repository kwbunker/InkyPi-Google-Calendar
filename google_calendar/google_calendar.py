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
    GoogleAuth,
    SetupRequired,
    chosen_calendar_colors,
    color_guide,
    fetch_events,
    palette_name_for_hex,
    panel_color,
    should_warn,
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
            image = self._render_calendar(settings, device_config, auth)
            self._remember_image(auth, image)
            return image

        # A scheduled refresh has no one watching, so a failure must never just leave
        # the panel looking current. That's why this catches everything.
        try:
            image = self._render_calendar(settings, device_config, auth)
        except Exception as error:
            logger.exception("Google Calendar refresh failed")
            return self._image_after_failure(error, device_config, auth)
        self._remember_image(auth, image)
        return image

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
        events, failed_calendars = fetch_events(
            CalendarClient(auth), calendar_ids, tz, start, end, chosen_calendar_colors(settings)
        )
        logger.info(f"Rendering Google Calendar: view={view}, events={len(events)}")

        render_view = view
        if view == "timeGridWeek" and not previous_days:
            render_view = "timeGrid"

        updated = f"{now:%b} {now.day}"
        if failed_calendars:
            updated += f" ({failed_calendars} of {len(calendar_ids)} calendars failed)"

        first_week = week_start(now.date(), first_day)
        template_params = {
            "view": render_view,
            "events": events,
            # Whole hours only: InkyPi skips the panel refresh when the image is unchanged,
            # so anything finer would refresh the panel more often than the calendar changes.
            "current_dt": now.replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat(),
            "first_day": first_day,
            "week_starts": [first_week.isoformat(), (first_week + timedelta(days=7)).isoformat()],
            "updated": updated,
            "time_format": time_format,
            "plugin_settings": settings,
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal"), 1),
        }

        image = self.render_image(dimensions, "google_calendar.html", "google_calendar.css", template_params)
        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    def _last_image_path(self, auth):
        return os.path.join(auth.state_dir, "last_image.png")

    def _remember_image(self, auth, image):
        path = self._last_image_path(auth)
        temporary = path + ".tmp"
        try:
            os.makedirs(auth.state_dir, mode=0o700, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                image.save(file, "PNG")
            os.replace(temporary, path)
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


def _dimensions(device_config):
    dimensions = device_config.get_resolution()
    if device_config.get_config("orientation") == "vertical":
        dimensions = dimensions[::-1]
    return dimensions


def _format_time(timestamp, device_config):
    tz = pytz.timezone(device_config.get_config("timezone", default="America/New_York"))
    moment = datetime.fromtimestamp(timestamp, tz)
    if device_config.get_config("time_format", default="12h") == "24h":
        clock = moment.strftime("%H:%M")
    else:
        clock = moment.strftime("%I:%M %p").lstrip("0").lower().replace(" ", "")
    return f"{moment:%b} {moment.day}, {clock}"
