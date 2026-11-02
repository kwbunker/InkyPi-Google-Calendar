import logging
import os
from datetime import datetime, timedelta

import pytz

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.google_calendar.calendar_api import (
    AuthRequired,
    CalendarClient,
    GoogleAuth,
    fetch_events,
    view_range,
    week_start,
)
from plugins.google_calendar.constants import FONT_SIZES, LOCALE_MAP
from utils.app_utils import resolve_path

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

        template_params["has_client"] = auth.has_client()
        template_params["signed_in"] = signed_in
        template_params["available_calendars"] = calendars
        template_params["calendar_error"] = calendar_error
        template_params["auth_url"] = auth.authorization_url() if auth.has_client() and not signed_in else None
        return template_params

    def generate_image(self, settings, device_config):
        auth = self._auth()

        # Sign-in steps use "Update Now" because plugins can't add their own web routes.
        # Raising shows the message in the web UI and leaves the panel as it is.
        if settings.get("credentialsContent"):
            auth.save_client(settings["credentialsContent"])
            raise RuntimeError("Credentials saved. Reload this page for the next step.")
        if settings.get("authResponse"):
            auth.complete_sign_in(settings["authResponse"])
            raise RuntimeError("Signed in to Google. Reload this page to choose your calendars.")

        calendar_ids = settings.get("calendarIds[]")
        if not calendar_ids:
            raise RuntimeError("Select at least one calendar.")

        view = settings.get("viewMode") or "timeGrid2Week"
        if view not in VIEWS:
            raise RuntimeError("Invalid view")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)

        first_day = int(settings.get("weekStartDay") or 0)
        previous_days = settings.get("displayPreviousDays") == "true"
        start, end = view_range(view, now, tz, first_day, previous_days)
        events = fetch_events(CalendarClient(auth), calendar_ids, tz, start, end)
        logger.info(f"Rendering Google Calendar: view={view}, events={len(events)}")

        render_view = view
        if view == "timeGridWeek" and not previous_days:
            render_view = "timeGrid"

        first_week = week_start(now.date(), first_day)
        template_params = {
            "view": render_view,
            "events": events,
            # Whole hours only: InkyPi skips the panel refresh when the image is unchanged,
            # so anything finer would refresh the panel more often than the calendar changes.
            "current_dt": now.replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat(),
            "first_day": first_day,
            "week_starts": [first_week.isoformat(), (first_week + timedelta(days=7)).isoformat()],
            "updated": f"{now:%b} {now.day}",
            "time_format": time_format,
            "plugin_settings": settings,
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal"), 1),
        }

        image = self.render_image(dimensions, "google_calendar.html", "google_calendar.css", template_params)
        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image
