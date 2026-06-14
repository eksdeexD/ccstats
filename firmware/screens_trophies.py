# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# TROPHIES category + the trophy engine — 1:1 ports of TROPHY_GLYPHS /
# TROPHY_FAMILIES / trophyEval() / peerTotals() / trophyCell() /
# drawTrophies() / drawNextUp() from viewscreens/screens.js. VERSUS - TROPHIES
# (screens_versus) evaluates the rival through the same engine.

import badgeware  # noqa: F401 -- badge/button globals for TrophyExplainFlow

from formatters import (
    format_compact,
    format_duration,
    format_integer_grouped,
    format_minutes,
    format_tokens,
    format_usd,
)
from screen_shared import (
    SECTION_LABEL_Y,
    distribute_columns,
    draw_bar,
    draw_chrome,
    draw_section_label,
)

# Glyphs as (x, y, w, h) rects in a 12x12 box (ported from /view's SVGs).
TROPHY_GLYPHS = {
    "titan": ((3, 2, 6, 2), (2, 4, 8, 2), (3, 6, 6, 2), (2, 8, 8, 2)),
    "prompter": ((1, 2, 10, 6), (3, 8, 3, 2), (3, 4, 2, 2), (6, 4, 2, 2)),
    "novelist": ((8, 1, 2, 2), (6, 3, 2, 2), (4, 5, 2, 2), (3, 7, 2, 2), (2, 9, 4, 1)),
    "flame": ((5, 1, 2, 2), (4, 3, 4, 2), (3, 5, 6, 3), (3, 8, 6, 2), (4, 10, 4, 1)),
    "calendar": ((3, 1, 1, 2), (8, 1, 1, 2), (2, 2, 8, 2), (2, 4, 8, 6), (4, 6, 2, 2)),
    "flag": ((3, 1, 1, 10), (4, 2, 6, 4)),
    "gear": ((4, 4, 4, 4), (5, 1, 2, 2), (5, 9, 2, 2), (1, 5, 2, 2), (9, 5, 2, 2)),
    "moon": ((3, 2, 6, 2), (2, 4, 4, 2), (2, 6, 4, 2), (3, 8, 6, 2), (9, 3, 1, 1)),
    "wrench": ((2, 8, 2, 2), (3, 6, 2, 2), (5, 4, 2, 2), (7, 2, 3, 3)),
    "star": ((5, 0, 2, 12), (0, 5, 12, 2), (2, 2, 2, 2), (8, 2, 2, 2), (2, 8, 2, 2), (8, 8, 2, 2)),
    "robot": ((5, 1, 2, 1), (3, 2, 6, 1), (2, 3, 8, 7)),
    "chars": ((5, 2, 2, 1), (4, 3, 1, 7), (7, 3, 1, 7), (5, 6, 2, 1), (3, 10, 6, 1)),
    "gauge": ((2, 9, 8, 1), (2, 7, 1, 2), (9, 7, 1, 2), (3, 5, 2, 1), (7, 5, 2, 1), (5, 4, 2, 1), (6, 6, 1, 3)),
    "meter": ((1, 3, 10, 6), (2, 4, 2, 4), (5, 4, 2, 4), (8, 4, 1, 4)),
}

TIER_NAMES = ("LOCKED", "COMMON", "RARE", "EPIC", "LEGENDARY")


def _value_peak_day_io(totals, me):
    return ((me.get("metrics") or {}).get("peak_day_io") or {}).get("tokens", 0)


def _value_bottleneck(totals, me):
    return (me.get("metrics") or {}).get("bottleneck_sec_total", 0)


def _value_session_hits(totals, me):
    return (me.get("limits") or {}).get("session_limit_hits", 0)


def _value_weekly_hits(totals, me):
    return (me.get("limits") or {}).get("weekly_limit_hits", 0)


# 14 families: (name, glyph, format kind, thresholds COMMON..LEGENDARY,
# value function over (totals, competition.me), peer-eligible)
TROPHY_FAMILIES = (
    ("TOKENS", "titan", "tokens", (1e6, 1e7, 2.5e7, 1e8),
     lambda t, me: t.get("tokens_input", 0) + t.get("tokens_output", 0), True),
    ("PROMPTS", "prompter", "int", (100, 1000, 2500, 10000),
     lambda t, me: t.get("user_prompts", 0), True),
    ("WORDS", "novelist", "compact", (10000, 50000, 250000, 500000),
     lambda t, me: t.get("user_words", 0), True),
    ("CHARS", "chars", "compact", (50000, 250000, 500000, 2000000),
     lambda t, me: t.get("user_chars_typed", 0), True),
    ("STREAK", "flame", "day", (3, 14, 30, 60),
     lambda t, me: t.get("longest_streak", 0), True),
    ("ACTIVE", "calendar", "day", (7, 30, 120, 270),
     lambda t, me: t.get("active_days", 0), True),
    ("MARATHON", "flag", "min", (60, 180, 360, 540),
     lambda t, me: t.get("longest_session_min", 0), True),
    ("GRIND", "gear", "min", (480, 4800, 24000, 48000),
     lambda t, me: t.get("total_active_min", 0), True),
    ("NIGHTOWL", "moon", "min", (300, 1500, 6000, 15000),
     lambda t, me: t.get("nightowl_active_min", 0), True),
    ("TOOLS", "wrench", "compact", (1000, 10000, 50000, 100000),
     lambda t, me: t.get("tool_uses", 0), False),  # peers don't ship tool_uses
    ("BIGBANG", "star", "tokens", (100000, 500000, 1000000, 2000000),
     _value_peak_day_io, True),
    ("BOTTLE", "robot", "dur", (900, 3600, 18000, 54000),
     _value_bottleneck, True),
    ("SESSION", "gauge", "int", (1, 6, 30, 60),
     _value_session_hits, True),
    ("WEEKLY", "meter", "int", (1, 3, 10, 25),
     _value_weekly_hits, True),
)


# One-line explanations for EXPLAIN mode (B on TROPHIES). These live ONLY in
# the old /view's screens.js TROPHY_FAMILIES `desc` field — they are not in the
# JSON feed, so the firmware carries the text over verbatim (keyed by name).
TROPHY_DESCRIPTIONS = {
    "TOKENS": "Total input+output tokens (cache-free).",
    "PROMPTS": "Prompts you have sent.",
    "WORDS": "Words you have typed in prompts.",
    "CHARS": "Characters you have typed (code-stripped).",
    "STREAK": "Longest consecutive-day streak.",
    "ACTIVE": "Distinct days you were active.",
    "MARATHON": "Longest single work session.",
    "GRIND": "Total active time (concurrent sessions count once).",
    "NIGHTOWL": "Total active time during 00:00-06:00.",
    "TOOLS": "Total tool calls Claude has run.",
    "BIGBANG": "Most input+output tokens in one day (no cache).",
    "BOTTLE": "Total time Claude waited on you. For laughs.",
    "SESSION": "Times you hit 67%+ of the 5-hour session limit.",
    "WEEKLY": "Times you hit 67%+ of the 7-day weekly limit.",
}


def evaluate_trophies(totals, me):
    # trophyEval(): -> [{name, glyph, format, tier 0..4, value, next, desc}]
    totals = totals or {}
    me = me or {}
    evaluated = []
    for name, glyph, format_kind, thresholds, value_function, _ in TROPHY_FAMILIES:
        value = value_function(totals, me) or 0
        tier = 0
        for index, threshold in enumerate(thresholds):
            if value >= threshold:
                tier = index + 1
        evaluated.append({
            "name": name, "glyph": glyph, "format": format_kind, "tier": tier,
            "value": value, "next": thresholds[tier] if tier < len(thresholds) else None,
            "desc": TROPHY_DESCRIPTIONS.get(name, ""),
        })
    return evaluated


def peer_totals(peer):
    # peerTotals(): a competition peer payload -> a totals-like dict so
    # evaluate_trophies() works on the rival too
    metrics = (peer or {}).get("metrics") or {}
    window_all = ((peer or {}).get("windows") or {}).get("all") or {}
    return {
        "tokens_input": window_all.get("tokens_input", 0),
        "tokens_output": window_all.get("tokens_output", 0),
        "user_prompts": metrics.get("prompts_total", 0),
        "user_words": metrics.get("words_typed_total", 0),
        "user_chars_typed": metrics.get("user_chars_typed", 0),
        "longest_streak": metrics.get("longest_streak", 0),
        "active_days": metrics.get("active_days", 0),
        "total_active_min": metrics.get("total_active_min", 0),
        "nightowl_active_min": metrics.get("nightowl_active_min", 0),
        "longest_session_min": metrics.get("endurance_longest_session_min", 0),
        "tool_uses": metrics.get("tool_uses", 0),
    }


def tier_pens(C):
    # LOCKED / COMMON / RARE / EPIC / LEGENDARY
    return (C.edge, C.accent_secondary_dark, C.accent_secondary,
            C.accent_primary_dark, C.accent_primary)


def trophy_format(format_kind, value):
    # tfmt(): per-family value formatting
    if format_kind == "tokens":
        return format_tokens(value)
    if format_kind == "int":
        return format_integer_grouped(value)
    if format_kind == "compact":
        return format_compact(value)
    if format_kind == "min":
        return format_minutes(value)
    if format_kind == "dur":
        return format_duration(value)
    if format_kind == "day":
        return "%dD" % (value or 0)
    if format_kind == "pct":
        return "%d%%" % round(value)
    if format_kind == "usd":
        return format_usd(value)
    return str(value)


def draw_glyph(P, rects, x, y, scale, pen):
    for rect_x, rect_y, rect_width, rect_height in rects or ():
        P.rect(x + rect_x * scale, y + rect_y * scale,
               rect_width * scale, rect_height * scale, pen)


def _trophy_cell(P, cell_x, cell_y, cell_width, trophy, selected=False):
    C = P.palette
    pen = tier_pens(C)[trophy["tier"]]
    if selected:  # EXPLAIN cursor: an accent box framing the tile content
        P.border(cell_x - 2, cell_y - 4, cell_width + 4, 45, C.accent_primary, 1)
    glyph_scale = 2
    glyph_width = 12 * glyph_scale
    draw_glyph(P, TROPHY_GLYPHS[trophy["glyph"]],
               cell_x + round((cell_width - glyph_width) / 2), cell_y, glyph_scale, pen)
    P.text(trophy["name"], cell_x + round(cell_width / 2), cell_y + 26,
           C.text if trophy["tier"] else C.text_dark, "tag", align="c")
    pip_width = 4
    pip_gap = 2
    pips_width = 4 * pip_width + 3 * pip_gap
    pips_x = cell_x + round((cell_width - pips_width) / 2)
    for index in range(4):
        P.rect(pips_x + index * (pip_width + pip_gap), cell_y + 34, pip_width, 3,
               pen if index < trophy["tier"] else C.edge)


def draw_trophies(P, stats_payload, cursor_index=None):
    # cursor_index highlights one tile (EXPLAIN mode, see TrophyExplainFlow).
    # Returns the evaluated trophies so the caption can reuse them.
    me = (stats_payload.get("competition") or {}).get("me") or {}
    trophies = evaluate_trophies(stats_payload.get("totals") or {}, me)
    level = sum(trophy["tier"] for trophy in trophies)
    draw_chrome(P, "TROPHIES", "%d/%d" % (level, len(trophies) * 4))
    columns = distribute_columns(6, 308, 5, 4)  # 5 trophies per row
    rows_y = 36
    row_pitch = 53  # tightened from 58 to free a caption band for EXPLAIN mode
    for index, trophy in enumerate(trophies):
        column_x, column_width = columns[index % 5]
        _trophy_cell(P, column_x, rows_y + (index // 5) * row_pitch, column_width, trophy,
                     selected=index == cursor_index)
    return trophies


def draw_next_up(P, stats_payload):
    C = P.palette
    me = (stats_payload.get("competition") or {}).get("me") or {}
    trophies = evaluate_trophies(stats_payload.get("totals") or {}, me)
    draw_chrome(P, "NEXT UP", "TROPHIES")
    draw_section_label(P, "CLOSEST TO NEXT TIER", SECTION_LABEL_Y)
    nearest = sorted(
        (dict(trophy, progress=trophy["value"] / trophy["next"])
         for trophy in trophies if trophy["next"]),
        key=lambda trophy: trophy["progress"], reverse=True,
    )[:4]
    list_y = 50
    row_pitch = 42
    for index, trophy in enumerate(nearest):
        y = list_y + index * row_pitch
        # '>' stands in for the spec's '→' (none of the pixel fonts carry U+2192)
        P.text("%s > %s" % (trophy["name"], TIER_NAMES[trophy["tier"] + 1]), 6, y,
               C.text, "row_label", letter_spacing=1)
        P.text("%s / %s" % (trophy_format(trophy["format"], trophy["value"]),
                            trophy_format(trophy["format"], trophy["next"])),
               314, y, C.text_dark, "caption", letter_spacing=1, align="r")
        draw_bar(P, 6, y + 12, 308, 9, max(0, min(1, trophy["progress"])), 1)


# ---- TROPHIES EXPLAIN mode (B-flow) -----------------------------------------
# The tightened grid (row_pitch 53) frees a band below the bottom row for a
# caption strip describing the hovered trophy.
TROPHY_CAPTION_TOP = 183


def draw_trophy_caption(P, trophy):
    # Hovered trophy: name + tier (line 1), one-line desc (line 2), and exact
    # progress (line 3) — 'value / next > NEXTTIER', or 'MAXED  value' at the top.
    C = P.palette
    P.hline(6, TROPHY_CAPTION_TOP, 308, C.edge)
    tier = trophy["tier"]
    P.text(trophy["name"], 6, TROPHY_CAPTION_TOP + 5, C.text, "row_label", letter_spacing=1)
    P.text(TIER_NAMES[tier], 314, TROPHY_CAPTION_TOP + 5, tier_pens(C)[tier],
           "caption", letter_spacing=1, align="r")
    P.text(trophy["desc"], 6, TROPHY_CAPTION_TOP + 19, C.text_dark, "caption", letter_spacing=1)
    if trophy["next"] is not None:
        # '>' stands in for the spec's '→' (none of the pixel fonts carry U+2192)
        progress = "%s / %s > %s" % (
            trophy_format(trophy["format"], trophy["value"]),
            trophy_format(trophy["format"], trophy["next"]),
            TIER_NAMES[min(4, tier + 1)],
        )
    else:
        progress = "MAXED  %s" % trophy_format(trophy["format"], trophy["value"])
    P.text(progress, 6, TROPHY_CAPTION_TOP + 31, C.text, "caption", letter_spacing=1)


class TrophyExplainFlow:
    # B on TROPHIES enters EXPLAIN: A/C move the cursor +/-1, UP/DOWN +/-5 (a
    # row) over the 5-wide grid, the caption strip shows the hovered trophy,
    # B exits. Ported from the old /view explainPress(); registered in
    # screens_options.B_FLOWS so navigation drives it like the other B-flows.
    footer_label = "EXIT"

    def __init__(self, navigation):
        self.navigation = navigation
        self.cursor_index = 0
        self.finished = False

    def handle_buttons(self):
        count = len(TROPHY_FAMILIES)
        columns = 5
        changed = False
        if badge.pressed(BUTTON_A):
            self.cursor_index = (self.cursor_index - 1) % count
            changed = True
        if badge.pressed(BUTTON_C):
            self.cursor_index = (self.cursor_index + 1) % count
            changed = True
        if badge.pressed(BUTTON_UP):
            self.cursor_index = (self.cursor_index - columns) % count
            changed = True
        if badge.pressed(BUTTON_DOWN):
            self.cursor_index = (self.cursor_index + columns) % count
            changed = True
        if badge.pressed(BUTTON_B):
            self.finished = True
            changed = True
        return changed

    def draw(self, P, stats_payload):
        trophies = draw_trophies(P, stats_payload, cursor_index=self.cursor_index)
        draw_trophy_caption(P, trophies[self.cursor_index])
