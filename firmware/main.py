# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# ccstats firmware — boot flow.
#
# Boots the display, joins WiFi from secrets, syncs the clock, fetches the
# feeds over verified HTTPS (feeds.py), then hands over to the navigation
# loop (two-axis nav across the screen registry).
#
# Entry points: the launcher app wrapper (__init__.py) and the host dev loop
# (dev_run.py) both call run_firmware().

import time

import badgeware  # injects the drawing globals (screen, display, badge, color, ...) into builtins
import network
import ntptime

import feeds
import http_client
import navigation
import secrets  # device /secrets.py or the mounted firmware/secrets.py (gitignored)
import settings
import theme
import version
from design_fonts import PRESS_START_2P, SILKSCREEN, effective_text_size

WIFI_JOIN_TIMEOUT_SECONDS = 30  # total budget with a single configured network
WIFI_CANDIDATE_TIMEOUT_SECONDS = 15  # per network when several are configured

# The panel backlight is OFF below ~0.45 PWM duty (hardware floor, measured
# on the LCD 2026-06-13) — the UI's 0-100% brightness spans the USABLE range
# instead (settled with the user), so every step visibly changes something.
BACKLIGHT_FLOOR = 0.45


def apply_brightness(ui_fraction, dimmed=False):
    """Map the stored 0..1 brightness onto the usable backlight range;
    dimmed (battery) pins the dimmest readable level instead."""
    if dimmed:
        badgeware.set_brightness(BACKLIGHT_FLOOR)
        return
    fraction = max(0.0, min(1.0, ui_fraction))
    badgeware.set_brightness(BACKLIGHT_FLOOR + fraction * (1.0 - BACKLIGHT_FLOOR))

# The splash: a CROPPED logo (not full-screen — images decode to 4 bytes/px,
# and a small logo decodes in a fraction of the time), centred 18 px from
# the top over a fixed #1c1c21 fill (the logo art's own background; settled
# 2026-06-13, replacing the hue cycle with a static look). Loads from device
# FLASH only — image.load through the mpremote mount bridge would crash the
# host-side server (same pitfall as the fonts). Installed runs use the app
# copy; dev runs use the root copy the dev loop put there
# (mpremote cp firmware/splash.png :/splash.png, once).
SPLASH_LOCATIONS = ("/system/apps/ccstats/splash.png", "/splash.png")
SPLASH_LOGO_TOP_Y = 18
SPLASH_STATUS_TOP_Y = 150  # free space under the logo artwork
SPLASH_STATUS_LINE_PITCH = 13
SPLASH_STATUS_VISIBLE_LINES = 5

boot_theme = theme.Theme()  # re-applied from the saved palette in run_firmware
boot_status_lines = []  # (text, pen) pairs; the whole boot screen is redrawn per line
splash_image = None  # held only during boot; released before navigation starts
_splash_background_pen = None  # built lazily (color needs the badgeware globals live)


def _get_splash_background_pen():
    global _splash_background_pen
    if _splash_background_pen is None:
        _splash_background_pen = color.rgb(0x1C, 0x1C, 0x21)
    return _splash_background_pen


def _load_splash():
    global splash_image
    splash_image = None
    for splash_path in SPLASH_LOCATIONS:
        try:
            splash_image = image.load(splash_path)
            break
        except OSError:
            continue


def draw_boot_screen():
    # native-px discipline: Press Start 2P (native 8) at x2, Silkscreen at x1,
    # via the grid-exact effective sizes (design_fonts.effective_text_size)
    screen.antialias = image.OFF
    if splash_image:
        screen.pen = _get_splash_background_pen()
        screen.clear()
        screen.blit(splash_image,  # this build's blit wants a vec2
                    vec2((screen.width - splash_image.width) // 2, SPLASH_LOGO_TOP_Y))
        line_y = SPLASH_STATUS_TOP_Y
        line_pitch = SPLASH_STATUS_LINE_PITCH
    else:
        screen.pen = boot_theme.background
        screen.clear()
        screen.font = PRESS_START_2P
        screen.pen = boot_theme.accent_primary
        screen.text("ccstats", 12, 12, effective_text_size("pico", 16))
        line_y = 40
        line_pitch = 14
    screen.font = SILKSCREEN
    for line_text, line_pen in boot_status_lines[-SPLASH_STATUS_VISIBLE_LINES:]:
        screen.pen = line_pen
        screen.text(line_text, 12, line_y, effective_text_size("silk", 8))
        line_y += line_pitch
    screen.pen = boot_theme.text_dark
    screen.text("V" + version.APP_VERSION, 4, 228, effective_text_size("silk", 8))
    display.update()


def report(line_text, line_pen=None):
    # One line, on the LCD and over serial, so host logs mirror the screen.
    print(line_text)
    boot_status_lines.append((line_text, line_pen or boot_theme.text))
    if len(boot_status_lines) > SPLASH_STATUS_VISIBLE_LINES:
        del boot_status_lines[0]  # retry loops must not grow the list forever
    draw_boot_screen()


def _boot_wait(wait_milliseconds):
    # a boot-retry pause; the splash is static now, nothing to animate
    time.sleep_ms(wait_milliseconds)


def fail(line_text):
    report(line_text, boot_theme.accent_primary)
    raise SystemExit


# The disk-mode WiFi file (settled 2026-06-13): /system is what MSC disk
# mode exposes to a PC (double-press RESET), so networks added there need no
# tooling. Two lines per network (SSID, then password), # comments and blank
# lines skipped, priority = file order. The installer seeds a commented
# template ONCE (never overwrites). Read-only /system is fine — boot only
# reads it.
WIFI_FILE_PATH = "/system/wifi.txt"


def parse_wifi_lines(lines):
    entries = [line.strip() for line in lines]
    entries = [line for line in entries if line and not line.startswith("#")]
    return [(entries[index], entries[index + 1]) for index in range(0, len(entries) - 1, 2)]


def _read_wifi_file():
    try:
        with open(WIFI_FILE_PATH) as wifi_file:
            return parse_wifi_lines(wifi_file.readlines())
    except OSError:
        return []


def _stock_system_secrets_pair():
    """The badgeware-STOCK /system/secrets.py (WIFI_SSID/WIFI_PASSWORD —
    the file the badge's own setup edits in disk mode). Parsed, not
    imported: `import secrets` is already bound to the littlefs ccstats
    one. Lets a badge with working stock WiFi run ccstats with no extra
    WiFi step."""
    try:
        namespace = {}
        with open("/system/secrets.py") as stock_file:
            exec(stock_file.read(), namespace)  # noqa: S102 -- device-local config
        ssid = namespace.get("WIFI_SSID")
        if ssid:
            return ((ssid, namespace.get("WIFI_PASSWORD", "")),)
    except Exception:  # unparsable/absent stock file — just no fallback
        pass
    return ()


def _wifi_candidates():
    # wifi.txt (disk-mode editable) wins; then secrets.WIFI_NETWORKS
    # (priority-ordered pairs); then the classic single secrets pair;
    # finally the badgeware-stock /system/secrets.py
    file_networks = _read_wifi_file()
    if file_networks:
        return file_networks
    networks = getattr(secrets, "WIFI_NETWORKS", None)
    if networks:
        return tuple(networks)
    ssid = getattr(secrets, "WIFI_SSID", None)
    if ssid:
        return ((ssid, secrets.WIFI_PASSWORD),)
    return _stock_system_secrets_pair()


def wifi_config_source():
    """Which config the join chain would use right now (the WIFI screen
    shows this)."""
    file_networks = _read_wifi_file()
    if file_networks:
        return "WIFI.TXT • %d NETWORKS" % len(file_networks)
    networks = getattr(secrets, "WIFI_NETWORKS", None)
    if networks:
        return "SECRETS.PY • %d NETWORKS" % len(networks)
    if getattr(secrets, "WIFI_SSID", None):
        return "SECRETS.PY"
    if _stock_system_secrets_pair():
        return "SYSTEM SECRETS.PY"
    return "NONE CONFIGURED"


def _order_by_visibility(wlan, candidates):
    """Candidates that a scan can see first (still in priority order), the
    rest after — absent networks should not burn their timeout before a
    visible one gets a chance, but hidden SSIDs still get theirs."""
    report("wifi: scanning...")
    try:
        visible_names = set()
        for scan_entry in wlan.scan():
            try:
                visible_names.add(scan_entry[0].decode())
            except (UnicodeError, AttributeError):
                continue
    except OSError as error:
        report("wifi: scan failed (%s), trying all" % error)
        return candidates
    in_sight = [entry for entry in candidates if entry[0] in visible_names]
    out_of_sight = [entry for entry in candidates if entry[0] not in visible_names]
    report("wifi: %d of %d networks in sight" % (len(in_sight), len(candidates)))
    return in_sight + out_of_sight


def _join_one(wlan, ssid, password, timeout_seconds):
    report("wifi: joining " + ssid + "...")
    wlan.connect(ssid, password)
    join_started_ms = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), join_started_ms) > timeout_seconds * 1000:
            report("wifi: %s timed out (status %d)" % (ssid, wlan.status()),
                   boot_theme.accent_primary)
            wlan.disconnect()  # clean slate before the next candidate
            return False
        time.sleep_ms(150)
    return True


def join_wifi():
    """Joins a configured network, retrying FOREVER (a badge that powers up
    before the router must not die on its error screen — AP-loss findings
    2026-06-13). Only a missing config is fatal: that needs the user."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        # possibly STALE right after an AP loss (isconnected() lies) — the
        # boot-fetch retry loop forces a rejoin if the network proves dead
        report("wifi: already connected " + wlan.ifconfig()[0], boot_theme.status)
        return
    candidates = _wifi_candidates()
    if not candidates:
        fail("wifi: no network configured (wifi.txt / secrets.py)")
    attempt = 1
    while True:
        ordered = candidates
        if len(candidates) > 1:
            ordered = _order_by_visibility(wlan, candidates)
            timeout_seconds = WIFI_CANDIDATE_TIMEOUT_SECONDS
        else:
            timeout_seconds = WIFI_JOIN_TIMEOUT_SECONDS
        for ssid, password in ordered:
            if _join_one(wlan, ssid, password, timeout_seconds):
                report("wifi: OK " + wlan.ifconfig()[0], boot_theme.status)
                return
        attempt += 1
        report("wifi: nothing joined - retry %d..." % attempt, boot_theme.accent_primary)
        _boot_wait(5000)


def sync_clock():
    # The RTC is set to UTC. Certificate validity checking needs a roughly
    # correct clock, so a failure is reported prominently — the fetch is still
    # attempted; mbedTLS rejects invalid chains itself.
    try:
        ntptime.settime()
        now = time.gmtime()
        report("clock: %04d-%02d-%02d %02d:%02d UTC" % now[0:5], boot_theme.status)
    except OSError as error:
        report("clock: NTP failed (%s), continuing" % error, boot_theme.accent_primary)


fetch_stats = feeds.fetch_everything  # the boot-time full fetch (one handshake, four GETs)

BOOT_FETCH_RETRY_SECONDS = 8


def fetch_stats_with_boot_report():
    """The boot fetch, retrying FOREVER. mbedTLS failures still fail closed
    on the DATA (nothing renders until a verified fetch succeeds), but the
    badge stays alive: the AP may just be rebooting — observed 2026-06-13:
    wlan.isconnected() stayed True through an AP restart, so boot sailed
    into a dead network. Every second failure forces a clean rejoin + NTP
    re-sync (a cold boot during an outage has an unset RTC, and certificate
    validity needs a roughly right clock)."""
    attempt = 1
    while True:
        report("feed: fetching claude-stats.json...")
        fetch_started_ms = time.ticks_ms()
        try:
            stats_payload = fetch_stats()
        except (http_client.HttpError, OSError) as error:
            report("feed: " + str(error), boot_theme.accent_primary)
            report("feed: retry %d in %d s..." % (attempt + 1, BOOT_FETCH_RETRY_SECONDS))
            _boot_wait(BOOT_FETCH_RETRY_SECONDS * 1000)
            if attempt % 2 == 0:
                wlan = network.WLAN(network.STA_IF)
                wlan.disconnect()
                join_wifi()
                sync_clock()
            attempt += 1
            continue
        fetch_elapsed_ms = time.ticks_diff(time.ticks_ms(), fetch_started_ms)
        report("feed: 200 OK in %d ms, TLS verified" % fetch_elapsed_ms, boot_theme.status)
        return stats_payload


def run_firmware():
    global splash_image
    settings.load()  # before anything reads a setting (theme, brightness, ...)
    badge.mode(HIRES | VSYNC)
    apply_brightness(settings.get("brightness"),
                     dimmed=settings.get("dim_on_battery") and not badge.usb_connected())
    boot_theme.apply(theme.preset_slots(settings.get("palette")))
    boot_status_lines.clear()
    _load_splash()
    draw_boot_screen()
    join_wifi()
    sync_clock()
    stats_payload = fetch_stats_with_boot_report()
    splash_image = None  # boot is over — the logo buffer goes back to the heap
    navigation.start(boot_theme, stats_payload)
