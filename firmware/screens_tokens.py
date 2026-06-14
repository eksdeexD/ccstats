# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# TOKEN USAGE + PROMPTS screens — 1:1 ports of drawTokens()/drawPrompts()
# in viewscreens/screens.js. All coordinates are the spec's literal pixels.

from formatters import (
    format_compact,
    format_integer_grouped,
    format_minutes,
    format_tokens,
    format_usd,
)
from options import day_metric_key, token_mode, token_value
from screen_shared import (
    SECTION_LABEL_Y,
    draw_card,
    draw_bar_row,
    draw_chrome,
    draw_section_label,
    draw_vertical_bars,
    ROW_BAR_X,
    ROW_BAR_WIDTH,
)


def peak_index_of(series):
    peak_index = 0
    for index in range(1, len(series)):
        if series[index] > series[peak_index]:
            peak_index = index
    return peak_index


def draw_tokens(P, stats_payload):
    # Contract field names cross the parse boundary here only.
    C = P.palette
    totals = stats_payload.get("totals") or {}
    feed_meta = stats_payload.get("meta") or {}
    cost_estimate = stats_payload.get("cost_estimate") or {}
    daily_activity = stats_payload.get("daily_activity") or []

    draw_chrome(P, "TOKEN USAGE", "ALL TIME")
    draw_section_label(
        P, "TOTAL TOKENS" if token_mode() == "all" else "IN + OUT TOKENS", SECTION_LABEL_Y
    )

    # hero — big total (left) + 2-line caption (right)
    P.text(format_tokens(token_value(totals)), 6, 44, C.accent_primary, "hero_value",
           letter_spacing=1, shadow=(1, 1, C.accent_primary_shadow))
    corpus_days = feed_meta.get("corpus_days", 0)
    P.text("OVER %d DAYS" % corpus_days, 314, 45, C.text_dark, "caption",
           letter_spacing=1, align="r")
    P.text(format_integer_grouped(totals.get("user_prompts", 0)) + " PROMPTS", 314, 57,
           C.text_dark, "caption", letter_spacing=1, align="r")

    # 30-day token trend — peak day highlighted
    draw_section_label(P, "TOKENS / DAY · 30D", 84)
    metric_key = day_metric_key()
    series = [day.get(metric_key, 0) for day in daily_activity[-30:]]
    draw_vertical_bars(P, 6, 96, 308, 62, series, peak_index_of(series) if series else -1, 1)

    # COST EST (accent 1) + CACHE HIT (accent 2) cards side by side
    cards_y = 178
    draw_card(P, 6, cards_y, 150, "COST EST", format_usd(cost_estimate.get("total_usd", 0)), 1)
    cache_hit_percent = round(totals.get("cache_hit_ratio", 0) * 100)
    draw_card(P, 164, cards_y, 150, "CACHE HIT", "%d%%" % cache_hit_percent, 2)


PROJECTS_PER_PAGE = 4

# PROJECTS "MORE" paging: a 4-up window offset over the (already sorted) project
# list. navigation owns the advance/reset (B = MORE, any nav button = back to 0);
# draw_projects reads it through projects_page(). Session-transient like the old
# /view projStart — never persisted.
_projects_page = 0


def projects_page():
    return _projects_page


def set_projects_page(value):
    global _projects_page
    _projects_page = value


def draw_project_rows(P, projects, start=0):
    # projectRows(): a 4-up page of projects as shared bar-rows with two dim
    # sub-lines; the GLOBAL rank-1 project is accent 1, the rest accent 2; bars
    # scale to the global top project so widths stay comparable across pages.
    # Reused by VERSUS - PROJECTS for the rival's breakdown (start defaults to 0).
    maximum_tokens = token_value(projects[0]) or 1 if projects else 1
    list_y = 48
    row_pitch = 46
    for index, project in enumerate(projects[start:start + PROJECTS_PER_PAGE]):
        global_rank = start + index  # only the true #1 is gold, even on later pages
        active_minutes = project.get("total_active_min", 0)
        time_text = format_minutes(active_minutes) if active_minutes else ""
        agents_text = format_integer_grouped(project.get("agent_launches", 0)) + " AGENTS"
        cost_text = (
            format_usd(project.get("cost_estimate_usd"))
            if project.get("cost_estimate_usd") is not None
            else ""
        )
        sub_line_1 = " • ".join(part for part in (time_text, agents_text, cost_text) if part)
        sub_line_2 = "%s PROMPTS • %s WORDS" % (
            format_integer_grouped(project.get("user_prompts", 0)),
            format_compact(project.get("user_words", 0)),
        )
        project_tokens = token_value(project)
        draw_bar_row(
            P, list_y + index * row_pitch, (project.get("name") or "").upper(),
            project_tokens / maximum_tokens, format_tokens(project_tokens),
            1 if global_rank == 0 else 2, sub_line_1, sub_line_2,
            bar_width=ROW_BAR_WIDTH - 8,  # bars 8px shorter for number space
        )


def draw_projects(P, stats_payload):
    projects = sorted(
        stats_payload.get("projects") or [], key=token_value, reverse=True
    )
    server_count = len((stats_payload.get("meta") or {}).get("servers") or ()) or 1
    draw_chrome(P, "PROJECTS", "SERVERS: %d • PROJECTS: %d" % (server_count, len(projects)))
    draw_section_label(
        P, "BY TOKENS • " + ("ALL" if token_mode() == "all" else "NO CACHE"), SECTION_LABEL_Y
    )
    # guard: the project count can shrink between fetches — clamp a stale window
    max_start = max(0, len(projects) - PROJECTS_PER_PAGE)
    if _projects_page > max_start:
        set_projects_page(0)
    draw_project_rows(P, projects, start=projects_page())


def draw_prompts(P, stats_payload):
    totals = stats_payload.get("totals") or {}
    daily_activity = stats_payload.get("daily_activity") or []

    draw_chrome(P, "PROMPTS", "ALL TIME")
    draw_section_label(P, "PROMPTS • BY WINDOW", SECTION_LABEL_Y)

    prompts_per_day = [day.get("prompts", 0) for day in daily_activity]

    def prompts_in_last(day_count):
        return sum(prompts_per_day[-day_count:]) if prompts_per_day else 0

    total_prompts = totals.get("user_prompts", 0)
    window_rows = (
        ("24H", prompts_in_last(1), 1),
        ("7D", prompts_in_last(7), 2),
        ("30D", prompts_in_last(30), 2),
        ("TOTAL", total_prompts, 2),
    )
    maximum_value = max(total_prompts, 1)
    list_y = 48
    row_pitch = 22
    for index, (label, value, accent_number) in enumerate(window_rows):
        # bars shifted 30px left of the shared geometry for space before the numbers
        draw_bar_row(P, list_y + index * row_pitch, label, value / maximum_value,
                     format_integer_grouped(value), accent_number, bar_x=ROW_BAR_X - 30)

    # 30-day prompts/day trend — peak day highlighted
    draw_section_label(P, "PROMPTS / DAY • 30D", 144)
    series = prompts_per_day[-30:]
    draw_vertical_bars(P, 6, 156, 308, 58, series, peak_index_of(series) if series else -1, 1)
