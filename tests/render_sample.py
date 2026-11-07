"""Renders made-up events through the real template, with no Google account needed.

Run on a Pi with the plugin installed, from ~/InkyPi/src:
    PYTHONPATH=. /usr/local/inkypi/venv_inkypi/bin/python render_sample.py out.png [view] [YYYY-MM-DD] [busy] [saturation] [nodinners]
Writes a PNG only. It doesn't touch the panel or the running service.
Add "slight", "lopsided", "heavy" or "extreme" as busy to test how a crowded week fits, or
"none" to skip that. Saturation is the Inky Driver Saturation to draw for, 0.5 by default.
Add "nodinners" to leave out the row of titles under each date.
"""
import sys
from datetime import date, datetime, timedelta

import pytz

from plugins.google_calendar.calendar_api import (
    ink_colors,
    palette_name_for_hex,
    split_date_row,
    to_fullcalendar_event,
    view_range,
    week_start,
)
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
    all_day("Gray Event", 13, 13, "8"),
]
busy = sys.argv[4] if len(sys.argv) > 4 else ""
for index in range({"slight": 3, "lopsided": 6, "heavy": 8, "extreme": 30}.get(busy, 0)):
    hour = 8 + index % 12
    items.append(timed(f"Extra Event {index + 1}", 6, f"{hour:02d}:00", f"{hour:02d}:30", "9"))
    if busy in ("heavy", "extreme"):
        items.append(timed(f"Another Event {index + 1}", 10, f"{hour:02d}:00", f"{hour:02d}:30", "10"))

default_color = palette_name_for_hex("#3788d8")
palette = ink_colors(sys.argv[5] if len(sys.argv) > 5 else 0.5)
events = [to_fullcalendar_event(item, default_color, tz, palette) for item in items]

dinners = [
    all_day("Tacos", 0, 0),
    all_day("Slow Cooker Chicken Tikka Masala", 1, 1),
    all_day("Leftovers", 2, 2),
    timed("Pizza Night", 3, "18:00", "19:00"),
    all_day("Soup", 4, 4),
    all_day("Grandma's House", 4, 4),
    all_day("Camping Food", 7, 9),
    all_day("Pasta", 11, 11),
]
date_row = None
if not (len(sys.argv) > 6 and sys.argv[6] == "nodinners"):
    _, date_row = split_date_row([
        {**to_fullcalendar_event(item, "white", tz), "dateRow": True} for item in dinners
    ])

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
    "date_row": date_row,
    "updated": f"{now:%b} {now.day}, 9:00am",
    "time_format": "12h",
    "plugin_settings": settings,
    "font_scale": 1,
})
if not image:
    sys.exit("Rendering failed; check the output above.")
image.save(output)
print(f"Wrote {output}: {image.size}")
