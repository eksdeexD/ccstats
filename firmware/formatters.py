# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Number/text formatters — verbatim ports of the spec's formatters in
# screens.js, so figures on the badge read identically to /viewscreens.

import time

MONTH_NAMES = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _trim_trailing_zero(text):
    # "26.0" -> "26" (the spec's trim())
    return text[:-2] if text.endswith(".0") else text


def _scaled(value, unit, suffix):
    # value/unit with one decimal, EXCEPT >= 100 of the unit drops the decimal so
    # the label stays ~4 chars (110.3M -> "110M", 107.3K -> "107K"), keeping big
    # values off the PROJECTS/TOOLS bars. "26.3M" / "75.9K" keep their decimal.
    scaled = value / unit
    if scaled >= 100:
        return "%d%s" % (round(scaled), suffix)
    return _trim_trailing_zero("%.1f" % scaled) + suffix


def format_tokens(value):
    # 26345678 -> "26.3M"; thousands round to whole K (fmtTokens)
    value = value or 0
    if value >= 1e9:
        return _trim_trailing_zero("%.1f" % (value / 1e9)) + "B"
    if value >= 1e6:
        return _scaled(value, 1e6, "M")
    if value >= 1e3:
        return "%d" % round(value / 1e3) + "K"
    return "%d" % round(value)


def format_compact(value):
    # like format_tokens but K keeps one decimal under 100K: 75949 -> "75.9K",
    # 107300 -> "107K" (fmtCompact)
    value = value or 0
    if value >= 1e9:
        return _trim_trailing_zero("%.1f" % (value / 1e9)) + "B"
    if value >= 1e6:
        return _scaled(value, 1e6, "M")
    if value >= 1e3:
        return _scaled(value, 1e3, "K")
    return "%d" % round(value)


def format_integer_grouped(value):
    # 1234567 -> "1,234,567" (fmtInt; MicroPython has no ',' format specifier)
    digits = "%d" % round(value or 0)
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return ",".join(groups)


def format_usd(value):
    # whole dollars, thousands-grouped, NEVER a K suffix: 2812.4 -> "$2,812"
    # (user decision 2026-06-12, deliberately diverging from /viewscreens's fmtUSD,
    # which compacts >= $1000 to "$2.8K" — the server side should follow)
    return "$" + format_integer_grouped(round(value or 0))


def format_duration(seconds):
    # seconds -> "1H 42M" / "37M 10S" / "12S" (fmtDur)
    seconds = max(0, round(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, leftover_seconds = divmod(remainder, 60)
    if hours > 0:
        return "%dH %02dM" % (hours, minutes)
    if minutes > 0:
        return "%dM %02dS" % (minutes, leftover_seconds)
    return "%dS" % leftover_seconds


def format_minutes(minutes):
    # 174 -> "2H 54M"; 47 -> "47M" (fmtMin)
    minutes = max(0, round(minutes or 0))
    hours, remainder = divmod(minutes, 60)
    if hours > 0:
        return "%dH %02dM" % (hours, remainder)
    return "%dM" % remainder


def parse_iso_to_epoch(iso_timestamp):
    # "2026-06-12T01:23:45+02:00" -> device epoch seconds (UTC). Handles a
    # trailing 'Z', '+-HH:MM' offsets, or no offset (treated as UTC). The
    # device RTC runs UTC (NTP), so comparisons against time.time() are exact.
    if not iso_timestamp or len(iso_timestamp) < 19:
        return None
    try:
        year = int(iso_timestamp[0:4])
        month = int(iso_timestamp[5:7])
        day = int(iso_timestamp[8:10])
        hour = int(iso_timestamp[11:13])
        minute = int(iso_timestamp[14:16])
        second = int(iso_timestamp[17:19])
    except ValueError:
        return None
    offset_minutes = 0
    tail = iso_timestamp[19:]
    if len(tail) >= 6 and tail[-6] in "+-" and tail[-3] == ":":
        sign = -1 if tail[-6] == "-" else 1
        offset_minutes = sign * (int(tail[-5:-3]) * 60 + int(tail[-2:]))
    return time.mktime((year, month, day, hour, minute, second, 0, 0)) - offset_minutes * 60


def seconds_until_reset(limit_block):
    # secFrom(): seconds until reset from the absolute resets_at (exact
    # regardless of feed age), falling back to resets_in_sec.
    if not limit_block or not limit_block.get("resets_at"):
        if limit_block and limit_block.get("resets_in_sec") is not None:
            return limit_block["resets_in_sec"]
        return None
    reset_epoch = parse_iso_to_epoch(limit_block["resets_at"])
    if reset_epoch is None:
        return None
    return max(0, round(reset_epoch - time.time()))


def format_reset(seconds):
    # fmtReset(): None -> '-', elapsed -> 'NOW', then "3D 5H" / "2H 14M" / "<1M"
    if seconds is None:
        return "-"
    if seconds <= 0:
        return "NOW"
    days = seconds // 86400
    hours = seconds % 86400 // 3600
    minutes = seconds % 3600 // 60
    if days > 0:
        return "%dD %dH" % (days, hours)
    if hours > 0:
        return "%dH %dM" % (hours, minutes)
    return ("%dM" % minutes) if minutes else "<1M"


def format_percent_one_decimal(value):
    # pct1(): one-decimal percent — "58.6%" / "27%"; None -> '-'
    if value is None:
        return "-"
    rounded = round(value * 10) / 10
    return _trim_trailing_zero("%.1f" % rounded) + "%"


def format_record_date(date_text):
    # fmtRecDate(): "2026-05-09" -> "MAY 9"
    if not date_text or len(date_text) < 10:
        return ""
    try:
        return "%s %d" % (MONTH_NAMES[int(date_text[5:7]) - 1], int(date_text[8:10]))
    except ValueError:
        return ""
