"""Renders made-up events through the real template, with no Google account needed.

Run on a Pi with the plugin installed, from ~/InkyPi/src:
    PYTHONPATH=. /usr/local/inkypi/venv_inkypi/bin/python render_sample.py out.png [options]
Writes a PNG only. It doesn't touch the panel or the running service. Run with --help for
the options, which choose the view, date, panel size, crowding and Inky Driver Saturation.
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytz

from plugins.google_calendar.calendar_api import (
    palette_name_for_hex,
    split_date_row,
    to_fullcalendar_event,
    view_range,
    week_start,
)
from plugins.google_calendar.google_calendar import VIEWS, GoogleCalendar, _palette, _panel_scale

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("output", help="PNG file to write")
parser.add_argument("--view", default="timeGrid2Week", choices=VIEWS)
parser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="today's date, as YYYY-MM-DD")
parser.add_argument("--size", default="1600x1200", help="panel size as WIDTHxHEIGHT, such as 800x480 or 1200x1600")
parser.add_argument("--busy", choices=("slight", "lopsided", "heavy", "extreme"), help="crowd some days to test how a week fits")
parser.add_argument("--saturation", type=float, default=0.5, help="Inky Driver Saturation to draw for, on the 13.3-inch panel")
parser.add_argument("--no-dinners", action="store_true", help="leave out the row of titles under each date")
args = parser.parse_args()

output = args.output
view = args.view
today = args.date
size = tuple(int(part) for part in args.size.lower().split("x"))
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


# A family's two weeks, using every panel color. Offsets count days from the first Sunday.
items = [
    timed("Soccer Game", 0, "09:00", "10:30", "10"),
    timed("Dentist", 1, "15:30", "16:30", "11"),
    timed("Piano Lesson", 1, "17:00", "17:45", "6"),
    all_day("Picture Day", 2, 2, "5"),
    timed("Book Club", 2, "19:00", "20:30", "6"),
    timed("Parent-Teacher Conferences", 3, "18:00", "19:00"),
    all_day("Library Books Due", 4, 4, "8"),
    timed("Swim Practice", 4, "16:00", "17:00", "10"),
    all_day("Grandparents Visiting", 5, 7, "9"),
    timed("Birthday Party", 6, "14:00", "16:00", "6"),
    timed("Soccer Game", 7, "09:00", "10:30", "10"),
    timed("Orthodontist", 8, "15:30", "16:15", "11"),
    timed("Piano Lesson", 9, "17:00", "17:45", "6"),
    all_day("Veterans Day: No School", 10, 10, "5"),
    timed("Swim Practice", 11, "16:00", "17:00", "10"),
    timed("Movie Night", 12, "19:00", "21:00"),
    all_day("Thanksgiving Potluck Signup", 12, 12, "5"),
    timed("Yard Cleanup", 13, "09:00", "12:00", "8"),
]
busy = args.busy
for index in range({"slight": 3, "lopsided": 6, "heavy": 8, "extreme": 30}.get(busy, 0)):
    hour = 8 + index % 12
    items.append(timed(f"Extra Event {index + 1}", 6, f"{hour:02d}:00", f"{hour:02d}:30", "9"))
    if busy in ("heavy", "extreme"):
        items.append(timed(f"Another Event {index + 1}", 10, f"{hour:02d}:00", f"{hour:02d}:30", "10"))

default_color = palette_name_for_hex("#3788d8")
# The same colors the plugin would use on a panel of this size.
device = SimpleNamespace(
    get_resolution=lambda: list(size),
    get_config=lambda key, default=None: {"image_settings": {"inky_saturation": args.saturation}}.get(key, default),
)
palette = _palette(device)
events =[to_fullcalendar_event(item, default_color, tz, palette) for item in items]

# One night has two entries, one title wraps, one is timed, and the last day is unplanned.
dinners = [
    all_day("Roast Chicken", 0, 0),
    all_day("Tacos", 1, 1),
    all_day("Leftovers", 2, 2),
    timed("Pizza Night", 3, "18:00", "19:00"),
    all_day("Slow Cooker Chili", 4, 4),
    all_day("Grandma's Lasagna", 5, 5),
    all_day("Date Night", 6, 6),
    all_day("Kids: Mac & Cheese", 6, 6),
    all_day("Pot Roast", 7, 7),
    all_day("Stir-Fry", 8, 8),
    all_day("Sheet Pan Chicken Fajitas", 9, 9),
    all_day("Breakfast for Dinner", 10, 10),
    all_day("Soup & Grilled Cheese", 11, 11),
    all_day("Takeout", 12, 12),
]
date_row = None
if not args.no_dinners:
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
image = plugin.render_image(size, "google_calendar.html", "google_calendar.css", {
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
    "panel_scale": _panel_scale(size),
})
if not image:
    sys.exit("Rendering failed; check the output above.")
image.save(output)
print(f"Wrote {output}: {image.size}")
