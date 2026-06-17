# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Footer WiFi signal indicator. Reads the joined network's RSSI and maps it to a
# 0..4 bar count for the little glyph the footer draws left of the battery icon.
# RSSI is re-read on the SAME ~15 s cadence as the battery gauge (NOT per frame —
# screen_shared.draw_wifi_icon just paints the cached count), and smoothed over a
# short window so a noisy reading doesn't make the glyph flicker bar-to-bar.
#
# bars_for_rssi() is the single source of the dBm->bars breakpoints: the WIFI
# options screen glyph (screens_options) maps the same way, so the footer and
# that screen never disagree about how many bars a given signal is worth.

import network  # the joined STA interface; RSSI comes from wlan.status('rssi')
import badgeware  # noqa: F401 -- injects the `badge` global (badge.ticks)

_SAMPLE_MILLISECONDS = 15000  # mirror battery_gauge's read cadence
_WINDOW = 4  # bar-count samples kept for the median (~1 min at 15 s) — de-flicker

_samples = []  # recent bar counts (0..4); 0 == disconnected / no signal
_last_sample_ticks = None
_bars = 0  # smoothed displayed bar count, 0 until the first sample primes it


def bars_for_rssi(rssi):
    """Map an RSSI in dBm (or None when disconnected) to 0..4 signal bars.

    Breakpoints are deliberately generous (shifted ~10 dB vs a textbook scale):
    the Tufty's WiFi front-end reads low even right next to a strong AP, so we
    bias the whole range up so a good signal shows as a good signal. -75 dBm is
    the floor for 3 bars, so a typical -70 dBm sits comfortably inside 3 bars."""
    if rssi is None:
        return 0
    if rssi >= -65:
        return 4
    if rssi >= -75:
        return 3
    if rssi >= -85:
        return 2
    return 1


def _read_rssi():
    """The joined network's RSSI in dBm, or None when not connected / on error."""
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        return None
    try:
        return wlan.status("rssi")
    except (OSError, ValueError):
        return None


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2  # bar counts are ints


def sample_if_due():
    """Call every loop pass: re-reads RSSI on its own ~15 s cadence and updates
    the smoothed bar count. Cheap between samples (just a ticks comparison)."""
    global _last_sample_ticks, _bars
    now = badge.ticks
    if _last_sample_ticks is not None and now - _last_sample_ticks < _SAMPLE_MILLISECONDS:
        return
    _last_sample_ticks = now
    _samples.append(bars_for_rssi(_read_rssi()))
    if len(_samples) > _WINDOW:
        _samples.pop(0)
    _bars = _median(_samples)


def prime():
    """Seed the indicator with one immediate reading before the first paint."""
    sample_if_due()


def bars():
    """Smoothed bar count 0..4 (0 until primed, or when disconnected)."""
    return _bars
