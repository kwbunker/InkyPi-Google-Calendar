"""Renders made-up events through the real template, with no Google account needed.

Run on a Pi with the plugin installed, from ~/InkyPi/src:
    PYTHONPATH=. /usr/local/inkypi/venv_inkypi/bin/python render_sample.py out.png [view] [YYYY-MM-DD]
Writes a PNG only. It doesn't touch the panel or the running service.
"""
import sys
from datetime import date, datetime, timedelta

import pytz

from plugins.google_calendar.calendar_api import palette_name_for_hex, to_fullcalendar_event, view_range, week_start
from plugins.google_calendar.google_calendar import GoogleCalendar

output = sys.argv[1]
view = sys.argv[2] if len(sys.argv) > 2 else "timeGrid2Week"
today = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date.today()
tz = pytz.timezone("America/Denver")
sunday = week_start(today, 0)


def day(offset):
    return (sunday + timedelta(days=offset)).isoformat()


def timed(title, offset, start, end, color=None):
    item = {
        "summary": title,
        "start": {"dateTime": f"{day(offset)}T{start}:00-07:00"},
        "end": {"dateTime": f"{day(offset)}T{end}:00-07:00"},
    }
    if color:
        item["colorId"] = color
    return item


def all_day(title, first, last, color=None):
    item = {"summary": title, "start": {"date": day(first)}, "end": {"date": day(last + 1)}}
    if color:
        item["colorId"] = color
    return item


items = [
    timed("Dentist Appointment", 0, "10:45", "12:00", "11"),
    all_day("Public Holiday", 1, 1, "5"),
    timed("Cooking Class", 1, "19:00", "20:30", "6"),
    all_day("Field Trip", 2, 2, "10"),
    timed("Team Meeting", 3, "19:00", "19:45", "6"),
    timed("Project Review 4:10-4:30", 4, "16:00", "16:30"),
    all_day("Beach Vacation", 9, 12, "6"),
    timed("Tom & Jerry <Film>", 9, "15:10", "17:35", "6"),
    all_day("Conference", 5, 8, "9"),
    all_day("Grey Event", 13, 13, "8"),
]
default_color = palette_name_for_hex("#3788d8")
events = [to_fullcalendar_event(item, default_color, tz) for item in items]

now = tz.localize(datetime.combine(today, datetime.min.time()).replace(hour=9))
view_range(view, now, tz)
settings = {
    "viewMode": view,
    "displayWeekends": "true",
    "displayEventTime": "true",
    "displayTitle": "true",
    "displayNowIndicator": "true",
    "fontSize": "normal",
}
plugin = GoogleCalendar({"id": "google_calendar"})
image = plugin.render_image((1600, 1200), "google_calendar.html", "google_calendar.css", {
    "view": view,
    "events": events,
    "current_dt": now.replace(tzinfo=None).isoformat(),
    "first_day": 0,
    "week_starts": [sunday.isoformat(), (sunday + timedelta(days=7)).isoformat()],
    "updated": f"{now:%b} {now.day}",
    "time_format": "12h",
    "plugin_settings": settings,
    "font_scale": 1,
})
if not image:
    sys.exit("Rendering failed; check the output above.")
image.save(output)
print(f"Wrote {output}: {image.size}")
