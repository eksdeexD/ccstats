# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# LIVE category — 1:1 ports of drawAvatar()/drawUsage()/drawToday() from
# viewscreens/screens.js. AVATAR delegates the mascot (sprite frames, word ticker)
# to avatar_animation, which also repaints those bands at animation cadence
# between full redraws. USAGE LIMITS countdowns derive from absolute
# resets_at at paint time; the navigation tick repaints every second while
# that screen is visible.

import avatar_animation
from formatters import (
    format_compact,
    format_integer_grouped,
    format_minutes,
    format_reset,
    format_tokens,
    seconds_until_reset,
)
from options import (
    avatar_line,
    day_metric_key,
    token_value,
)
from screens_trophies import draw_glyph
from screen_shared import (
    ROW_BAR_HEIGHT,
    ROW_BAR_WIDTH,
    ROW_BAR_X,
    ROW_NAME_X,
    ROW_VALUE_RIGHT,
    SECTION_LABEL_Y,
    distribute_columns,
    draw_bar,
    draw_bar_row,
    draw_card,
    draw_chrome,
    draw_section_label,
)


def _draw_up_down_arrow(P, x, y, pointing_up, pen):
    # 5x3 pixel arrow (the spec's arrowUD)
    if pointing_up:
        P.rect(x + 2, y, 1, 1, pen)
        P.rect(x + 1, y + 1, 3, 1, pen)
        P.rect(x, y + 2, 5, 1, pen)
    else:
        P.rect(x, y, 5, 1, pen)
        P.rect(x + 1, y + 1, 3, 1, pen)
        P.rect(x + 2, y + 2, 1, 1, pen)


def _draw_today_row(P, y, label, today_value, average_value, format_value, accent_number):
    # LABEL + today value + right-aligned "AVG x" with an up/down arrow
    C = P.palette
    accent, _, _, accent_shadow = C.accent_pens(accent_number)
    is_up = today_value >= average_value
    comparison_pen = C.status if is_up else C.text_dark
    P.text(label, 6, y, C.text, "row_label", letter_spacing=1)
    P.text(format_value(today_value), 88, y, accent, "row_value",
           letter_spacing=1, shadow=(1, 1, accent_shadow))
    arrow_x = 314 - 5
    _draw_up_down_arrow(P, arrow_x, y + 2, is_up, comparison_pen)
    P.text("AVG " + format_value(average_value), arrow_x - 4, y, comparison_pen,
           "caption", letter_spacing=1, align="r")


def draw_today(P, stats_payload):
    totals = stats_payload.get("totals") or {}
    daily_activity = stats_payload.get("daily_activity") or []
    today = daily_activity[-1] if daily_activity else {}
    active_days = max(1, totals.get("active_days", 0))

    draw_chrome(P, "TODAY", "VS AVG")
    draw_section_label(P, "TODAY VS DAILY AVERAGE", SECTION_LABEL_Y)

    rows_y = 54
    row_pitch = 26
    _draw_today_row(P, rows_y, "TOKENS", today.get(day_metric_key(), 0),
                    token_value(totals) / active_days, format_tokens, 1)
    _draw_today_row(P, rows_y + row_pitch, "PROMPTS", today.get("prompts", 0),
                    totals.get("user_prompts", 0) / active_days,
                    lambda value: format_integer_grouped(round(value)), 2)
    _draw_today_row(P, rows_y + 2 * row_pitch, "SESSIONS", today.get("sessions", 0),
                    totals.get("sessions", 0) / active_days,
                    lambda value: str(round(value)), 1)
    _draw_today_row(P, rows_y + 3 * row_pitch, "ACTIVE", today.get("active_min", 0),
                    totals.get("total_active_min", 0) / active_days, format_minutes, 2)
    # (SERVERS count now lives in the PROJECTS header)


# The GLOOM ghost sprite, idle frame — (x, y, w, h) rects in a 16x16 box
# (fill / shade / highlight / eye whites / pupils), from screens.js GHOST.
GHOST_FILL = ((5, 2, 5, 1), (4, 3, 7, 1), (3, 4, 9, 1), (2, 5, 11, 1), (2, 6, 11, 1),
              (2, 7, 11, 1), (2, 8, 11, 1), (2, 9, 11, 1), (2, 10, 11, 1), (2, 11, 11, 1),
              (2, 12, 2, 2), (5, 12, 2, 2), (8, 12, 2, 2), (11, 12, 2, 2))
GHOST_SHADE = ((12, 5, 1, 7), (11, 12, 2, 2))
GHOST_HIGHLIGHT = ((4, 3, 2, 1), (3, 4, 1, 2))
GHOST_EYE_WHITES = ((4, 5, 2, 3), (9, 5, 2, 3))
GHOST_PUPILS = ((5, 6, 1, 2), (9, 6, 1, 2))


def _draw_ghost_sprite(P, x, y, scale):
    # neutral GLOOM at an arbitrary cell scale — the animated AVATAR uses the
    # pre-squashed scale-7 frames instead; this stays for the M5 OPTIONS
    # sprite preview (drawn at x4 in the spec)
    C = P.palette
    draw_glyph(P, GHOST_FILL, x, y, scale, C.avatar_color)
    draw_glyph(P, GHOST_SHADE, x, y, scale, C.avatar_dark)
    draw_glyph(P, GHOST_HIGHLIGHT, x, y, scale, C.avatar_light)
    draw_glyph(P, GHOST_EYE_WHITES, x, y, scale, C.eye_white)
    draw_glyph(P, GHOST_PUPILS, x, y, scale, C.background)


# the two AVATAR info-line row anchors (no labels; bars are centred 38..282
# around x=160 with the percent at the right margin — user-tuned 2026-06-12).
# The defaults (my_session, daily_stats) reproduce the pre-modular layout
# pixel-for-pixel.
_AVATAR_LINE_Y = (29, 44)


def _rival_limits(stats_payload):
    rival = ((stats_payload.get("competition") or {}).get("peers") or [None])[0]
    return (rival or {}).get("limits") or {}


def _draw_avatar_bar(P, y, utilization, accent_number):
    # mine = accent1, the rival's = accent2; identical to the session bar
    accent = P.palette.accent_pens(accent_number)[0]
    draw_bar(P, 38, y, 244, 8, _utilization_fraction(utilization), accent_number)
    P.text(_percent_text(utilization), 314, y + 1, accent, "caption", align="r")


def _draw_avatar_line(P, mode, y, stats_payload, limits, today):
    if mode == "none":
        return
    if mode == "daily_stats":
        P.text(
            "%s TOKENS • %s PROMPTS • %s WORDS" % (
                format_tokens(today.get(day_metric_key(), 0)),
                format_integer_grouped(today.get("prompts", 0)),
                format_compact(today.get("words", 0)),
            ),
            160, y, P.palette.text_dark, "caption", letter_spacing=1, align="c",
        )
        return
    if mode == "my_session":
        _draw_avatar_bar(P, y, (limits.get("session") or {}).get("utilization"), 1)
    elif mode == "my_weekly":
        _draw_avatar_bar(P, y, (limits.get("weekly") or {}).get("utilization"), 1)
    elif mode == "rival_session":
        _draw_avatar_bar(P, y, (_rival_limits(stats_payload).get("session") or {}).get("utilization"), 2)
    elif mode == "rival_weekly":
        _draw_avatar_bar(P, y, (_rival_limits(stats_payload).get("weekly") or {}).get("utilization"), 2)


def draw_avatar(P, stats_payload):
    limits = stats_payload.get("limits") or {}
    daily_activity = stats_payload.get("daily_activity") or []
    today = daily_activity[-1] if daily_activity else {}

    draw_chrome(P, "CLAUDE CODE", avatar_animation.animator.chrome_label())

    # NB: the two info lines STAY on battery — the stats (15 min) and limits
    # (5 min) feeds keep refreshing; only live_status (the avatar animation) is
    # off, so only the mascot rests (2026-06-13). Each line is user-configurable
    # (OPTIONS > DISPLAY > AVATAR LINE 1/2): a utilization bar (mine = accent1,
    # rival = accent2), the daily tokens/prompts/words line, or nothing.
    _draw_avatar_line(P, avatar_line(1), _AVATAR_LINE_Y[0], stats_payload, limits, today)
    _draw_avatar_line(P, avatar_line(2), _AVATAR_LINE_Y[1], stats_payload, limits, today)

    # the mascot — the animator owns the stage + word bands (and repaints them
    # at animation cadence between full redraws; static frame on battery)
    avatar_animation.animator.draw_stage(P, sleeping=avatar_animation.animator.on_battery)
    avatar_animation.animator.draw_word(P)


def _percent_text(utilization):
    return "%d%%" % round(utilization) if utilization is not None else "-"


def _utilization_fraction(utilization):
    return max(0, min(1, utilization / 100)) if utilization is not None else 0


def _opponent_row(P, y, label, utilization, reset_text, accent_number):
    # LABEL + reset countdown under it + utilization bar + pct (oppRow)
    C = P.palette
    P.text(label, ROW_NAME_X, y, C.text, "row_label", letter_spacing=1)
    if reset_text:
        P.text(reset_text, ROW_NAME_X, y + 11, C.text_dark, "caption", letter_spacing=1)
    draw_bar(P, ROW_BAR_X, y, ROW_BAR_WIDTH, ROW_BAR_HEIGHT,
             _utilization_fraction(utilization), accent_number)
    accent = C.accent_pens(accent_number)[0]
    P.text(_percent_text(utilization), ROW_VALUE_RIGHT, y, accent, "row_value", align="r")


def draw_usage(P, stats_payload):
    limits = stats_payload.get("limits") or {}
    session = limits.get("session") or {}
    weekly = limits.get("weekly") or {}

    draw_chrome(P, "USAGE LIMITS", "")  # top-right intentionally blank

    # YOUR USAGE — SESSION (accent 1) + WEEKLY (accent 2) utilization bars
    draw_section_label(P, "YOUR USAGE", SECTION_LABEL_Y)
    session_percent = session.get("utilization")
    weekly_percent = weekly.get("utilization")
    draw_bar_row(P, 48, "SESSION", _utilization_fraction(session_percent),
                 _percent_text(session_percent), 1)
    draw_bar_row(P, 70, "WEEKLY", _utilization_fraction(weekly_percent),
                 _percent_text(weekly_percent), 2)

    # OPPONENT USAGE — the rival's bars + reset countdowns (only with a peer)
    rival = ((stats_payload.get("competition") or {}).get("peers") or [None])[0]
    rival_limits = (rival or {}).get("limits")
    if rival_limits:
        draw_section_label(P, "OPPONENT USAGE", 94)
        # stale rival data: resets_at stays correct until it passes, but an
        # expired one can't be replaced by stale data — blank it, don't pin NOW
        fetch_state = (rival.get("_fetch") or {})
        rival_stale = fetch_state.get("ok") is False or bool(rival_limits.get("stale"))

        def rival_reset_text(limit_block):
            seconds = seconds_until_reset(limit_block)
            if rival_stale and seconds is not None and seconds <= 0:
                return "-"
            return format_reset(seconds)

        rival_session = rival_limits.get("session") or {}
        rival_weekly = rival_limits.get("weekly") or {}
        _opponent_row(P, 110, "SESSION", rival_session.get("utilization"),
                      rival_reset_text(rival_session), 1)
        _opponent_row(P, 134, "WEEKLY", rival_weekly.get("utilization"),
                      rival_reset_text(rival_weekly), 2)

    # RESETS — my reset countdowns, pinned to the bottom
    draw_section_label(P, "RESETS", 171)
    columns = distribute_columns(6, 308, 2, 8)
    cards_y = 187
    draw_card(P, columns[0][0], cards_y, columns[0][1], "SESSION RESET",
              format_reset(seconds_until_reset(session)), 1)
    draw_card(P, columns[1][0], cards_y, columns[1][1], "WEEKLY RESET",
              format_reset(seconds_until_reset(weekly)), 2)
