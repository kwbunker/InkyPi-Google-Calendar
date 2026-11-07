# Full setup: Pi Zero 2 W and 13.3" Inky Impression

This guide goes from a blank SD card to a Google Calendar on the panel, including the awkward parts that cost the most time. It was written from a real rebuild in November 2026, on Raspberry Pi OS Lite 64-bit (Trixie) with a UniFi Wi-Fi network. Details will drift over time, especially the Wi-Fi fix.

**Hardware:** a Pi Zero 2 W, not the original Zero or Zero W, which [InkyPi's maintainers consider unsupported](https://github.com/fatihak/InkyPi/issues/784) because Chromium no longer runs on them. You also need a 5V 2.5A power supply and a microSD card.

## 1. Flash the card

1. In Raspberry Pi Imager, choose **Raspberry Pi Zero 2 W** and **Raspberry Pi OS Lite (64-bit)**, found under **Raspberry Pi OS (other)**. Lite leaves more of the Pi's 512 MB free.
2. Set a hostname, a username, your time zone, your Wi-Fi and SSH access. A public key is the simplest choice for SSH. The Zero 2 W only supports 2.4 GHz Wi-Fi.
3. Optional but worthwhile: turn on **Enable USB Gadget Mode** under **Interfaces & Features**. It gives you SSH over a USB cable if Wi-Fi fails. See [Getting in over USB](#getting-in-over-usb).
4. **Add the Wi-Fi fix before the first boot** if your network offers mixed WPA2/WPA3. See the next section.

### The Wi-Fi fix

On this OS, a Zero 2 W [can't join a mixed WPA2/WPA3 network](https://github.com/raspberrypi/linux/issues/7634). It tries WPA3, its Wi-Fi chip never completes it, and it never falls back to WPA2. The Pi doesn't appear in your router's client list at all, and it looks like a wrong password or a failed boot, but it's neither.

After flashing, put the card back in your computer and open the boot partition (`bootfs`). Add this to the end of the existing single line in `cmdline.txt`, with a space before it and no new line:

```text
brcmfmac.feature_disable=0x2282000
```

- **A reflash loses this,** so add it again every time.
- **Setting WPA2 on the Pi doesn't help,** because the Pi's network software adds WPA3 back anyway.
- **The alternative** is to set your Wi-Fi network to WPA2-only.
- **This flag was tested with hand-written first-boot settings,** using the same mechanism as Imager's. Imager's own settings should behave the same, but that exact combination wasn't tested.
- **Recheck the bug report after major kernel updates,** because the meaning of this number can change between kernels.

If your log shows this, it's this bug:

```text
Config: added 'key_mgmt' value 'WPA-PSK WPA-PSK-SHA256 FT-PSK SAE FT-SAE'
wlan0: Authentication with <bssid> timed out.
device (wlan0): state change: need-auth -> failed (reason 'no-secrets')
```

The `no-secrets` part is misleading: the password was never checked.

## 2. First boot

1. Keep the panel off for now. It's one less thing to rule out if something goes wrong.
2. Use wall power in the port marked `PWR IN`. If you're using USB gadget mode instead, use one cable from your computer to the port marked `USB`, and leave `PWR IN` empty. Nothing official confirms that using both ports at once is safe.
3. **Leave it alone for 10 minutes.** First boot resizes the card and sets up the system. [Cutting power during this can damage the install](https://github.com/raspberrypi/rpi-imager/issues/1543).

Then connect with `ssh <username>@<hostname>.local`.

A mostly steady green LED with occasional flickers is normal, so it won't tell you whether Wi-Fi worked. If `.local` names don't resolve, look for the Pi's address in your router's client list. Separate Wi-Fi networks or VLANs often block `.local` names.

### Getting in over USB

1. On Windows, first install `rpi-usb-gadget-driver-setup.exe` from the [rpi-usb-gadget releases](https://github.com/raspberrypi/rpi-usb-gadget/releases).
2. Use a cable that carries data. Many micro-USB cables only charge.
3. **Gadget mode doesn't start on the first boot.** Its setting takes effect after a restart, so unplug the Pi once first boot has finished, then plug it back in.
4. Connect with `ssh <username>@10.12.194.1`.

During setup the log may show `TimeoutExpired` for `rpi-usb-gadget`, and `cloud-init status` may report an error. On this rebuild, gadget mode still worked after the restart.

## 3. Install InkyPi

1. Shut down with `sudo shutdown -h now`, then unplug the Pi.
2. Press the Pi firmly and evenly onto the panel's header. Many upstream reports of detection errors and half-frozen screens came down to a poorly seated header.
3. Peel off the panel's protective film if it's still on.
4. Switch to wall power in `PWR IN`.
5. **Connect with a normal interactive SSH session,** then run the commands below. Allow about half an hour.

```bash
sudo apt-get update && sudo apt-get install -y git tmux
```

```bash
tmux
```

```bash
git clone https://github.com/fatihak/InkyPi.git && cd InkyPi && sudo bash install/install.sh
```

Answer **Y** to the reboot. If SSH drops, reconnect and run `tmux attach`.

**Don't run the installer without a terminal,** such as through `nohup` or `ssh host command`. Its progress spinner checks `ps a`, which only lists processes attached to a terminal, so without one it moves on immediately and reports success while apt and pip are still running in the background. Signs of this include `Could not get lock /var/lib/dpkg/lock-frontend` and `Unit earlyoom.service does not exist`. To recover, wait until `pgrep -x apt-get` finds nothing, then run this from the `InkyPi` folder:

```bash
sudo bash install/update.sh
```

`update.sh` runs its steps in order and is safe without a terminal. Run it from the top of the `InkyPi` folder, not from inside `install`, because some of its downloads use relative paths.

After the reboot, the panel shows a splash screen and the web UI is at `http://<hostname>.local`. If you use gadget mode, the installer may suggest the USB address `10.12.194.1` instead of your Wi-Fi address.

In **Settings**, set your time zone.

## 4. Upgrade the panel driver

InkyPi pins Inky 2.4.0, but [2.6.0](https://github.com/pimoroni/inky/releases) fixes how the 13.3" panel waits for a refresh to finish. Its notes warn that getting this wrong can latch a fault that only full power removal clears, which may explain reports of half-frozen screens, though that link is unconfirmed.

```bash
sudo /usr/local/inkypi/venv_inkypi/bin/python -m pip install inky==2.6.0
```

```bash
sudo systemctl restart inkypi
```

**InkyPi's `update.sh` puts 2.4.0 back,** so repeat this after every update.

**Inky Driver Saturation** in **Settings** changes how colours are dithered. Upstream's docs suggest trying 0, but on this panel 0.5 looked better to my eye, so compare both on your own panel. Higher values bring the web preview closer to the panel's real colours, but in simulation thin black lines and text start to speckle above about 0.6.

## 5. Install this plugin

```bash
inkypi plugin install google_calendar https://github.com/kwbunker/InkyPi-Google-Calendar
```

### Google Cloud Console

Google's menus change, so these names may differ a little.

1. Create a project and enable the **Google Calendar API**.
2. Set up the consent screen as an External app. **Publishing needs more than the fields marked as required:** the Branding page also needs a home page link and a privacy policy link, or **Publish app** stays greyed out.
   - You can use this repo's page and [PRIVACY.md](../PRIVACY.md), or your own copies.
   - If Google asks you to add `github.com` under **Authorized domains**, do that.
   - **Don't upload a logo.** That requires Google's verification.
3. Under **Audience**, click **Publish app**. **This step matters:** in Testing mode, Google ends your sign-in every 7 days. Skip the offer to submit for verification, which personal use doesn't need.
4. Under **Clients**, create a **new** client of type **Desktop app**, and **download its JSON file right away**. Google may not offer the secret again, so an old client is usually no use without its original file. New clients can take from a few minutes to a few hours to start working.

### Sign in

Do this on the plugin's page in InkyPi's web UI. Keep the credentials file and the `localhost` address private, because both contain secrets.

1. Choose the JSON file, click **Update Now**, then reload the page. **The message starts with "Error!" even though it worked,** because that's the only way a plugin can show a message there.
2. Open the sign-in link. If Google warns that the app isn't verified, choose **Advanced** and continue.
3. Your browser ends up on a page saying **localhost refused to connect**. That's expected. Don't reload it.
4. Copy the whole address from the address bar, paste it into the field, and click **Update Now**. Again, the "Error!" message says it worked.
5. Reload the page and check your calendars.

The code in that address works once and expires quickly. If it's rejected, reload the settings page and use the sign-in link again.

Your sign-in files are in `src/config/google_calendar/` and survive reinstalling the plugin.

## 6. Add it to a playlist

Clicking **Update Now** is a one-off. For automatic updates:

1. Check your calendars and choose a layout, then click **Update Now** and compare the panel with Google Calendar.
2. Click **Add to Playlist**, give it a name using only letters, numbers and spaces, and choose a refresh interval.

**To change your settings later, open the entry from Playlists.** Opening Google Calendar from the plugin list gives you a blank form instead, with only your primary calendar ticked. It's easy to mistake for your saved settings, so the page now says so. Your saved entry isn't affected unless you click **Save** on the entry itself. On the blank form, **Update Now** shows those choices until the next scheduled refresh, and **Add to Playlist** creates a second entry.

**The instance interval can't beat the system interval.** InkyPi only wakes up at the **Plugin Cycle Interval** in **Settings**, an hour by default, so a 15-minute instance interval still refreshes hourly unless you lower that too. Hourly suits this plugin, and each refresh on a Zero 2 W also means rendering with Chromium.

**If the playlist entry never updates,** open it from **Playlists** and check that your calendars are still selected. InkyPi resets the form after **Add to Playlist**, even when adding failed. Plugin versions before this guide let a retry save no calendars, Afrikaans as the language, and the smallest font. This is fixed now, but entries saved that way need fixing and saving again.

## Choosing colours

The panel has six inks plus a mixed orange, and the plugin's settings page shows what's available:

- **Beside each calendar** is the panel colour its events get when they have no colour of their own. It's suggested from the calendar's Google colour, and you can choose a different one from the list. That only affects the panel, not your Google Calendar. On a saved entry, click **Save** afterwards.
- **Under the date**, at the bottom of that list, shows a calendar's event titles in a plain row under each date instead of boxes, which suits something like a dinner plan. It only applies to the 2 Weeks layout, and other layouts show those events as normal.
- **Panel colours** lists which Google event colours produce each panel colour. For example, Tangerine becomes orange, and both Tomato and Flamingo become red.

- **The note beside each panel colour** is a reminder for you, such as who that colour is for. Notes are saved with the entry and don't appear on the panel.

Pale or grey calendar colours are worth checking. A grey calendar is suggested as white, so its events show as plain white boxes unless you choose something else. An event's own colour always wins over its calendar's.

**Colour-coding by person or category:** events can only get a colour through Google's event colours, which give six distinct results on the panel: red, orange, yellow, green, blue and white. Black can only be a calendar's colour. Several Google colours share one panel colour, so pick one Google colour per person. For example, Tomato and Flamingo look different in Google Calendar but are both red on the panel. If yellow is your calendar's default, that leaves five for people.

## What to watch afterwards

- **A red warning across the bottom** means a scheduled refresh failed and the panel is showing your last good calendar. It appears straight away for problems that need you, and after 3 hours for passing ones like a Wi-Fi drop.
- **The "Updated" stamp on the panel** is your health check when no warning can appear, because the panel keeps its last image even if the Pi has crashed or lost power. It shows when the calendar last changed, not when it last checked Google, so an old time on today's date is normal. It's a problem if the date is earlier than today, because the plugin redraws at least once a day, so the Pi itself has probably stopped.
- **Freezes:** the Zero 2 W has a history of locking up after hours or days, with the green LED blinking nonstop or SSH not answering. Upstream's memory fixes and `earlyoom` improved this, but watch it for the first few days.
- **Part of the panel not updating:** one user fixed this by unplugging it for about 10 minutes. Also check that the header is seated.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Pi never appears on the router | [The Wi-Fi bug](#the-wi-fi-fix) | Add the flag to `cmdline.txt`, or set Wi-Fi to WPA2-only |
| `Authentication with ... timed out`, then `no-secrets` | The same bug, not your password | The same fix |
| Nothing appears over USB | Charge-only cable, wrong port, first boot, or no driver | Use a data cable in `USB`, restart once, install the driver |
| Installer says it finished but packages are missing | It ran without a terminal | Wait for apt, then run `install/update.sh` |
| `Can't find a driver` or `No EEPROM detected` | Poorly seated header, or a board that doesn't auto-detect | Reseat first. If that fails, edit `src/display/inky_display.py` to use `from inky.inky_el133uf1 import Inky` and `Inky()`. Upstream's docs name an outdated file |
| Panel stopped changing after an update | `update.sh` restored Inky 2.4.0, or a real fault | Reinstall Inky 2.6.0, and check `journalctl -u inkypi` |
| **Publish app** is greyed out | The home page or privacy policy link is missing | Fill them in on the Branding page |
| Signed out after about a week | The app is still in Testing mode | Publish to Production, then sign in again |
| Sign-in link shows `invalid_client` | The new client hasn't taken effect yet | Wait a while and try again |
| Red warning says no calendars are selected | Entry saved before the form-reset fix | Open it under **Playlists**, reselect your calendars, check the language and font, and save |
| Red warning says Google sign-in has expired | The app is in Testing mode, or access was revoked | Publish to Production if needed, then sign in again on the plugin's settings page |
| Red warning says it can't get new events | Wi-Fi or Google has been unreachable for over 3 hours, or something else failed | Check the Wi-Fi and `journalctl -u inkypi` |
| "Updated" text says some calendars failed | One calendar can't be read, for example it was deleted or unshared | Check the log, and update your selection |
