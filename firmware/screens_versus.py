# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# VERSUS category — 1:1 ports of cmpRow()/vsTag()/drawVersus()/drawVsHuman()/
# drawVsHumanBest()/drawVsRecords()/drawVsProjects()/drawVsAwards() from
# viewscreens/screens.js. All head-to-head data comes from the competition feed.

from formatters import (
    format_compact,
    format_duration,
    format_integer_grouped,
    format_minutes,
    format_percent_one_decimal,
    format_record_date,
    format_tokens,
)
from options import token_mode, token_value
from screen_shared import SECTION_LABEL_Y, draw_chrome, draw_section_label
from screens_tokens import draw_project_rows
from screens_trophies import TROPHY_FAMILIES, evaluate_trophies, peer_totals, tier_pens

# shared comparison-column geometry (CMP_* in the spec)
COMPARE_LABEL_X = 6
COMPARE_ME_CENTER = 134
COMPARE_SEPARATOR_CENTER = 195
COMPARE_RIVAL_CENTER = 255


def _competition_parts(stats_payload):
    competition = stats_payload.get("competition") or {}
    me = competition.get("me") or {}
    peers = competition.get("peers") or []
    rival = peers[0] if peers else {}
    return me, rival, bool(peers)


def versus_tag(has_rival, rival, live_label):
    # SOLO (no rival) / STALE (last pull of the rival's feed failed) / live label
    if not has_rival:
        return "SOLO"
    fetch_state = (rival or {}).get("_fetch") or {}
    return "STALE" if fetch_state.get("ok") is False else (live_label or "LIVE")


def compare_row(P, y, label, my_text, rival_text, my_number, rival_number,
                has_rival, higher_wins=True):
    # LABEL | my value (accent 1) <chevron> rival value (accent 2). The
    # separator is the win chevron: '>' me, '<' rival, '=' tie, '·' no rival;
    # higher_wins=False flips the direction (lower is better, e.g. BOTTLENECK).
    C = P.palette
    if label:
        P.text(label, COMPARE_LABEL_X, y, C.text_dark, "row_label", letter_spacing=1)
    P.text(my_text, COMPARE_ME_CENTER, y, C.accent_primary, "compare_value", align="c")
    P.text(rival_text, COMPARE_RIVAL_CENTER, y, C.accent_secondary, "compare_value", align="c")
    separator = "·"
    if has_rival and my_number is not None and rival_number is not None:
        if my_number == rival_number:
            separator = "="
        elif (my_number > rival_number) if higher_wins else (my_number < rival_number):
            separator = ">"
        else:
            separator = "<"
    P.text(separator, COMPARE_SEPARATOR_CENTER, y, C.text_dark, "caption", align="c")


def _draw_versus_header(P, me, rival, has_rival, y=46):
    # YOU VS RIVAL alias header, shared by the VERSUS screens
    C = P.palette
    P.text((me.get("alias") or "YOU").upper(), COMPARE_ME_CENTER, y,
           C.accent_primary, "row_label", align="c")
    P.text("VS", COMPARE_SEPARATOR_CENTER, y, C.text_dark, "caption",
           letter_spacing=1, align="c")
    P.text((rival.get("alias") or "RIVAL").upper() if has_rival else "NO RIVAL",
           COMPARE_RIVAL_CENTER, y, C.accent_secondary, "row_label", align="c")


def _window_tokens(competitor, window_key):
    windows = (competitor or {}).get("windows") or {}
    return token_value(windows.get(window_key) or {})


def draw_versus(P, stats_payload):
    me, rival, has_rival = _competition_parts(stats_payload)
    draw_chrome(P, "VERSUS", versus_tag(has_rival, rival, "LIVE"))
    draw_section_label(
        P, "TOKEN RACE • " + ("ALL" if token_mode() == "all" else "NO CACHE"), SECTION_LABEL_Y
    )
    _draw_versus_header(P, me, rival, has_rival)

    periods = (("24H", "24h"), ("7D", "7d"), ("30D", "30d"), ("TOTAL", "all"))
    rows_y = 66
    row_pitch = 22
    for index, (label, window_key) in enumerate(periods):
        my_tokens = _window_tokens(me, window_key)
        rival_tokens = _window_tokens(rival, window_key)
        compare_row(P, rows_y + index * row_pitch, label, format_tokens(my_tokens),
                    format_tokens(rival_tokens) if has_rival else "-",
                    my_tokens, rival_tokens, has_rival)

    # AGENTS — all-time subagent launches ('-' until a side ships agents_total)
    draw_section_label(P, "AGENTS", 156)
    my_agents = (me.get("metrics") or {}).get("agents_total")
    rival_agents = (rival.get("metrics") or {}).get("agents_total")
    compare_row(P, 174, "LAUNCHED",
                format_integer_grouped(my_agents) if my_agents is not None else "-",
                format_integer_grouped(rival_agents) if has_rival and rival_agents is not None else "-",
                my_agents, rival_agents, has_rival)


def draw_versus_human(P, stats_payload):
    me, rival, has_rival = _competition_parts(stats_payload)
    my_metrics = me.get("metrics") or {}
    rival_metrics = rival.get("metrics") or {}
    draw_chrome(P, "VERSUS - HUMAN", versus_tag(has_rival, rival, "LIVE"))
    draw_section_label(P, "HUMAN EFFORT • ALL", SECTION_LABEL_Y)
    _draw_versus_header(P, me, rival, has_rival)

    def metric_row(key, format_value):
        mine = my_metrics.get(key)
        theirs = rival_metrics.get(key)
        return (format_value(mine or 0),
                format_value(theirs or 0) if has_rival else "-", mine, theirs)

    rows = (
        ("WORDS",) + metric_row("words_typed_total", format_compact) + (True,),
        ("CHARS",) + metric_row("user_chars_typed", format_compact) + (True,),
        ("PROMPTS",) + metric_row("prompts_total", format_integer_grouped) + (True,),
        ("BOTTLENK",) + metric_row("bottleneck_sec_total", format_duration) + (False,),
        ("ACTIVE",) + metric_row("total_active_min", format_minutes) + (True,),
        ("DAYS",) + metric_row("active_days", format_integer_grouped) + (True,),
    )
    rows_y = 66
    row_pitch = 19
    for index, (label, my_text, rival_text, my_number, rival_number, higher_wins) in enumerate(rows):
        compare_row(P, rows_y + index * row_pitch, label, my_text, rival_text,
                    my_number, rival_number, has_rival, higher_wins)


def draw_versus_human_best(P, stats_payload):
    C = P.palette
    me, rival, has_rival = _competition_parts(stats_payload)
    my_metrics = me.get("metrics") or {}
    rival_metrics = rival.get("metrics") or {}
    draw_chrome(P, "VERSUS - BEST DAY", versus_tag(has_rival, rival, "LIVE"))
    draw_section_label(P, "BEST SINGLE DAY", SECTION_LABEL_Y)
    _draw_versus_header(P, me, rival, has_rival)

    records = (("WORDS", "record_day_words", format_compact),
               ("PROMPTS", "record_day_prompts", format_integer_grouped),
               ("ACTIVE", "record_day_active_min", format_minutes),
               ("SESSIONS", "record_day_sessions", format_integer_grouped))
    rows_y = 68
    row_pitch = 32
    for index, (label, key, format_value) in enumerate(records):
        y = rows_y + index * row_pitch
        my_record = my_metrics.get(key) or {}
        rival_record = rival_metrics.get(key) or {}
        my_value = my_record.get("value")
        rival_value = rival_record.get("value")
        compare_row(P, y, label,
                    format_value(my_value) if my_value is not None else "-",
                    format_value(rival_value) if has_rival and rival_value is not None else "-",
                    my_value, rival_value, has_rival)
        P.text(format_record_date(my_record.get("date")), COMPARE_ME_CENTER, y + 11,
               C.text_dark, "caption", align="c")
        if has_rival:
            P.text(format_record_date(rival_record.get("date")), COMPARE_RIVAL_CENTER,
                   y + 11, C.text_dark, "caption", align="c")


def draw_versus_records(P, stats_payload):
    me, rival, has_rival = _competition_parts(stats_payload)
    my_metrics = me.get("metrics") or {}
    rival_metrics = rival.get("metrics") or {}
    my_peak = my_metrics.get("peak_day_io") or my_metrics.get("peak_day") or {}
    rival_peak = rival_metrics.get("peak_day_io") or rival_metrics.get("peak_day") or {}
    draw_chrome(P, "VERSUS - RECORDS", versus_tag(has_rival, rival, "ALL TIME"))
    draw_section_label(P, "PERSONAL BESTS", SECTION_LABEL_Y)
    _draw_versus_header(P, me, rival, has_rival)

    rows = (
        ("STREAK", "%dD" % (my_metrics.get("current_streak") or 0),
         "%dD" % (rival_metrics.get("current_streak") or 0),
         my_metrics.get("current_streak"), rival_metrics.get("current_streak")),
        ("BEST", "%dD" % (my_metrics.get("longest_streak") or 0),
         "%dD" % (rival_metrics.get("longest_streak") or 0),
         my_metrics.get("longest_streak"), rival_metrics.get("longest_streak")),
        ("PEAKDAY", format_tokens(my_peak.get("tokens", 0)),
         format_tokens(rival_peak.get("tokens", 0)),
         my_peak.get("tokens"), rival_peak.get("tokens")),
        ("ENDURE", format_minutes(my_metrics.get("endurance_longest_session_min", 0)),
         format_minutes(rival_metrics.get("endurance_longest_session_min", 0)),
         my_metrics.get("endurance_longest_session_min"),
         rival_metrics.get("endurance_longest_session_min")),
        ("CACHEHIT", format_percent_one_decimal((my_metrics.get("cache_hit_ratio") or 0) * 100),
         format_percent_one_decimal((rival_metrics.get("cache_hit_ratio") or 0) * 100),
         my_metrics.get("cache_hit_ratio"), rival_metrics.get("cache_hit_ratio")),
    )
    rows_y = 66
    row_pitch = 22
    for index, (label, my_text, rival_text, my_number, rival_number) in enumerate(rows):
        compare_row(P, rows_y + index * row_pitch, label, my_text,
                    rival_text if has_rival else "-", my_number, rival_number, has_rival)


def draw_versus_projects(P, stats_payload):
    C = P.palette
    me, rival, has_rival = _competition_parts(stats_payload)
    projects = sorted(rival.get("projects") or [], key=token_value, reverse=True)
    draw_chrome(P, "VERSUS - PROJECTS", "PROJECTS: %d" % len(projects))
    rival_name = (rival.get("alias") or "RIVAL").upper() if has_rival else "RIVAL"
    draw_section_label(
        P, "%s • BY TOKENS • %s" % (rival_name, "ALL" if token_mode() == "all" else "NO CACHE"),
        SECTION_LABEL_Y,
    )
    if not projects:
        P.text("NO PROJECT DATA YET" if has_rival else "NO RIVAL", 6, 60,
               C.text_dark, "row_label", letter_spacing=1)
        return
    draw_project_rows(P, projects)


def draw_versus_awards(P, stats_payload):
    C = P.palette
    me, rival, has_rival = _competition_parts(stats_payload)
    my_trophies = evaluate_trophies(stats_payload.get("totals") or {}, me)
    rival_trophies = evaluate_trophies(peer_totals(rival), rival) if has_rival else None
    draw_chrome(P, "VERSUS - TROPHIES", "")
    draw_section_label(P, "TROPHY TIERS", SECTION_LABEL_Y)
    _draw_versus_header(P, me, rival, has_rival, 44)

    def draw_pips(center_x, y, tier):
        pen = tier_pens(C)[tier]
        pip_width = 4
        pip_gap = 1
        pips_width = 4 * pip_width + 3 * pip_gap
        x = center_x - round(pips_width / 2)
        for index in range(4):
            P.rect(x + index * (pip_width + pip_gap), y, pip_width, 4,
                   pen if index < tier else C.edge)

    rows_y = 58
    row_pitch = 13
    row = 0
    for family_index, family in enumerate(TROPHY_FAMILIES):
        peer_eligible = family[5]
        if not peer_eligible:
            continue
        y = rows_y + row * row_pitch
        row += 1
        my_tier = my_trophies[family_index]["tier"]
        rival_tier = rival_trophies[family_index]["tier"] if has_rival else 0
        P.text(family[0], 6, y, C.text_dark, "tag")
        draw_pips(COMPARE_ME_CENTER, y, my_tier)
        separator = ("·" if not has_rival
                     else ">" if my_tier > rival_tier
                     else "<" if my_tier < rival_tier else "=")
        P.text(separator, COMPARE_SEPARATOR_CENTER, y, C.text_dark, "caption", align="c")
        if has_rival:
            draw_pips(COMPARE_RIVAL_CENTER, y, rival_tier)
        else:
            P.text("-", COMPARE_RIVAL_CENTER, y, C.text_dark, "caption", align="c")
