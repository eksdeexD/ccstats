# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Screen registry — the firmware counterpart of SCREENS/CATEGORY_ORDER in
# screens.js, holding ONLY the screens that are actually ported (no
# placeholders: navigation shows what exists, and new screens appear here as
# they land). Categories follow the spec's order; UP/DOWN skips categories
# with no ported screens. Collapsing related screens into a B-toggle later is
# a registry change, not a navigation change.

import screens_activity
import screens_breakdown
import screens_live
import screens_options
import screens_tokens
import screens_trophies
import screens_versus

CATEGORY_ORDER = (
    "LIVE",
    "TOKENS",
    "ACTIVITY",
    "BREAKDOWN",
    "VERSUS",
    "TROPHIES",
    "OPTIONS",
    "DEV",
)

# (screen_id, category, draw_function) — draw functions take (P, stats_payload)
PORTED_SCREENS = (
    ("avatar", "LIVE", screens_live.draw_avatar),
    ("usage", "LIVE", screens_live.draw_usage),
    # PROJECTS lives in LIVE (3rd, after USAGE LIMITS) though its draw fn stays
    # in screens_tokens; TODAY moved to BREAKDOWN (between WORDS and TOOLS).
    ("projects", "LIVE", screens_tokens.draw_projects),
    ("tokens", "TOKENS", screens_tokens.draw_tokens),
    ("prompts", "TOKENS", screens_tokens.draw_prompts),
    ("activity", "ACTIVITY", screens_activity.draw_activity),
    ("calendar", "ACTIVITY", screens_activity.draw_calendar),
    ("rhythm", "ACTIVITY", screens_activity.draw_rhythm),
    ("rhythm_matrix", "ACTIVITY", screens_activity.draw_rhythm_matrix),
    ("words", "BREAKDOWN", screens_breakdown.draw_words),
    ("today", "BREAKDOWN", screens_live.draw_today),
    ("tools", "BREAKDOWN", screens_breakdown.draw_tools),
    ("models", "BREAKDOWN", screens_breakdown.draw_models),
    ("versus", "VERSUS", screens_versus.draw_versus),
    ("versus_human", "VERSUS", screens_versus.draw_versus_human),
    ("versus_human_best", "VERSUS", screens_versus.draw_versus_human_best),
    ("versus_records", "VERSUS", screens_versus.draw_versus_records),
    ("versus_awards", "VERSUS", screens_versus.draw_versus_awards),
    ("versus_projects", "VERSUS", screens_versus.draw_versus_projects),
    ("trophies", "TROPHIES", screens_trophies.draw_trophies),
    ("next_up", "TROPHIES", screens_trophies.draw_next_up),
    ("options_display", "OPTIONS", screens_options.draw_options_display),
    ("options_screens", "OPTIONS", screens_options.draw_options_screens),
    ("options_palettes", "OPTIONS", screens_options.draw_options_palettes),
    ("options_avatar", "OPTIONS", screens_options.draw_options_avatar),
    ("options_wifi", "OPTIONS", screens_options.draw_options_wifi),
)

# Display titles (SCREENS[slug].title in screens.js) — the SCREENS show/hide
# editor and the boot-screen picker render these as data.
SCREEN_TITLES = {
    "avatar": "CLAUDE CODE",
    "usage": "USAGE LIMITS",
    "today": "TODAY",
    "tokens": "TOKEN USAGE",
    "prompts": "PROMPTS",
    "projects": "PROJECTS",
    "activity": "ACTIVITY",
    "calendar": "CALENDAR",
    "rhythm": "RHYTHM",
    "rhythm_matrix": "RHYTHM MATRIX",
    "words": "WORDS",
    "tools": "TOOLS",
    "models": "MODELS",
    "versus": "VERSUS",
    "versus_human": "VERSUS - HUMAN",
    "versus_human_best": "VERSUS - BEST DAY",
    "versus_records": "VERSUS - RECORDS",
    "versus_awards": "VERSUS - TROPHIES",
    "versus_projects": "VERSUS - PROJECTS",
    "trophies": "TROPHIES",
    "next_up": "NEXT UP",
    "options_display": "DISPLAY",
    "options_screens": "SCREENS",
    "options_palettes": "PALETTES",
    "options_avatar": "AVATAR",
    "options_wifi": "WIFI",
}

# Screens with periodic on-screen behaviour: screen_id -> (interval_ms, tick
# function or None for a pure repaint). The navigation loop runs these while
# the screen is visible: the WORDS book line rotates every 10 s, USAGE LIMITS
# repaints every second so the reset countdowns tick.
SCREEN_TICKS = {
    "words": (screens_breakdown.BOOK_CYCLE_MILLISECONDS, screens_breakdown.cycle_book),
    "usage": (1000, None),
}

# Which screens draw each OPTIONAL feed — a refresh of that feed only
# repaints the visible screen when it is listed here (the primary stats
# payload feeds every screen and always repaints). Keep in sync when a
# newly ported screen reads one of these payload keys.
FEED_SCREEN_DEPENDENCIES = {
    # live_status is NOT listed: its body changes every poll (timestamps), and
    # the avatar animator consumes status EDGES itself — a full repaint every
    # 2 s would fight the partial-region animation.
    "live_status": (),
    "limits": ("avatar", "usage"),
    "competition": (
        "usage", "words",
        "versus", "versus_human", "versus_human_best",
        "versus_records", "versus_awards", "versus_projects",
        "trophies", "next_up",
    ),
}


def categories_with_screens():
    """Ordered [(category_name, [(screen_id, draw_function), ...]), ...] of
    categories that have at least one ported, non-hidden screen. A hidden
    list that would leave NOTHING navigable is ignored outright (a corrupt
    settings file must not brick navigation)."""
    import settings

    hidden_screens = settings.get("hidden_screens")
    if all(screen_id in hidden_screens for screen_id, _, _ in PORTED_SCREENS):
        hidden_screens = ()
    grouped = []
    for category_name in CATEGORY_ORDER:
        screens_in_category = [
            (screen_id, draw_function)
            for screen_id, category, draw_function in PORTED_SCREENS
            if category == category_name and screen_id not in hidden_screens
        ]
        if screens_in_category:
            grouped.append((category_name, screens_in_category))
    return grouped
