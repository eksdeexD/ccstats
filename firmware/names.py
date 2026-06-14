# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Single source of truth for identifiers used across the firmware.
# Screen ids are device-config-referenced (boot_screen, hidden_screens) —
# keep them stable once shipped.
#
# One id per screen in the /viewscreens SCREENS registry (screens.js). The
# navigable registry itself (which of these are ported, their categories and
# draw functions) lives in screen_registry.py.

SCREEN_AVATAR = "avatar"  # the live CLAUDE CODE avatar / status face
SCREEN_USAGE_LIMITS = "usage_limits"  # session (5h) + weekly (7d) limit bars
SCREEN_TODAY = "today"  # today's numbers vs the daily average
SCREEN_TOKEN_USAGE = "tokens"  # all-time token total + trend + cost/cache cards
SCREEN_PROMPTS = "prompts"  # prompts by window + prompts/day trend
SCREEN_PROJECTS = "projects"  # per-project token bars
SCREEN_ACTIVITY = "activity"  # daily activity heatmap
SCREEN_CALENDAR = "calendar"  # zoomed calendar view
SCREEN_RHYTHM = "rhythm"  # hour/weekday bar charts
SCREEN_RHYTHM_MATRIX = "rhythm_matrix"  # weekday x hour heat matrix
SCREEN_WORDS = "words"  # human input: words/characters typed
SCREEN_TOOLS = "tools"  # tool-usage toplist
SCREEN_MODELS = "models"  # model share + turns
SCREEN_VERSUS = "versus"  # head-to-head token race
SCREEN_VERSUS_HUMAN = "versus_human"  # effort comparison
SCREEN_VERSUS_HUMAN_BEST = "versus_human_best"  # single-day records comparison
SCREEN_VERSUS_RECORDS = "versus_records"  # personal bests comparison
SCREEN_VERSUS_AWARDS = "versus_awards"  # trophies comparison
SCREEN_VERSUS_PROJECTS = "versus_projects"  # rival's project breakdown
SCREEN_TROPHIES = "trophies"  # trophy families + tiers
SCREEN_NEXT_UP = "next_up"  # closest upcoming trophies
SCREEN_OPTIONS_DISPLAY = "options_display"  # display prefs editor
SCREEN_OPTIONS_SCREENS = "options_screens"  # per-screen show/hide editor
SCREEN_OPTIONS_PALETTES = "options_palettes"  # palette preset picker
SCREEN_OPTIONS_AVATAR = "options_avatar"  # avatar sprite picker
SCREEN_OPTIONS_WIFI = "options_wifi"  # WiFi join/config flow
SCREEN_FONT_TEST = "font_test"  # DEV: the font sheet
