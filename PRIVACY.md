# Privacy Policy

This policy covers the InkyPi Google Calendar plugin, which appears on Google's sign-in screen as "InkyPi Calendar". It's a personal, open-source project with no company or server behind it. It runs only on the Raspberry Pi of the person who installed it.

## What it accesses

With your permission, the plugin reads your Google Calendar through Google's read-only calendar scope (`calendar.readonly`). That covers your list of calendars and the events on the calendars you select, including their titles, times, colours, locations and descriptions. It can't create, change or delete anything.

## How that data is used

The plugin uses calendar data only to draw your calendar on your display. It isn't used for anything else, and it isn't sold, shared, or used for advertising or analytics.

## Where data goes and stays

The plugin talks only to Google. It sends your data to no other server, and the author can't see it.

These stay on your Pi:

- Your Google credentials file and sign-in token, in `src/config/google_calendar/`, readable only by the InkyPi service.
- A copy of the last calendar image, in that same folder, so the display can keep showing your calendar with a warning if an update fails.
- The images InkyPi saves of what it displays, which show your events. Anyone on your local network who can open InkyPi's web page can view them.
- InkyPi's logs, which record how many events were drawn but not their contents.

Event data isn't otherwise saved. It's fetched again at each refresh.

## Removing access

You can revoke access at any time from your [Google Account permissions page](https://myaccount.google.com/permissions). Uninstalling the plugin doesn't delete `src/config/google_calendar/`, so delete that folder as well to remove the stored credentials, token and image.

## Questions

Please [open an issue](https://github.com/kwbunker/InkyPi-Google-Calendar/issues) on this repository.
