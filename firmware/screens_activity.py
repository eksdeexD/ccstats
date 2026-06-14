# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# ACTIVITY category — 1:1 ports of drawActivity()/drawCalendar()/drawRhythm()/
# drawRhythmMatrix() from viewscreens/screens.js. All coordinates are the spec's
# literal pixels.

import time

from formatters import format_integer_grouped
from options import day_metric_key
from screen_shared import (
    SECTION_LABEL_Y,
    CARD_HEIGHT,
    distribute_columns,
    draw_card,
    draw_chrome,
    draw_section_label,
    draw_vertical_bars,
)

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
WEEKDAY_NAMES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
WEEKDAY_LETTERS = ("M", "T", "W", "T", "F", "S", "S")

# heatmap density grid (drawActivity)
HEAT_ROWS = 9
HEAT_COLUMNS = 12
HEAT_CELL_WIDTH = 14
HEAT_CELL_HEIGHT = 12
HEAT_GAP = 2
HEAT_X = 6
HEAT_GRID_TOP = 61
HEAT_RIGHT = HEAT_X + HEAT_COLUMNS * (HEAT_CELL_WIDTH + HEAT_GAP) - HEAT_GAP


def heat_level(value, maximum_value, prompts):
    # 5 active levels; an active day (prompts > 0) never reads as empty
    if value == 0:
        level = 0
    else:
        level = min(5, max(1, -(-value * 5 // maximum_value)))  # ceil(value/max*5)
    if level == 0 and (prompts or 0) > 0:
        level = 1
    return level


# ---- date arithmetic (the spec uses JS Date; here: epoch-day numbers) ----

def day_number_from_date_text(date_text):
    # "2026-06-11" -> whole days since the device epoch (noon avoids edges)
    year, month, day = int(date_text[0:4]), int(date_text[5:7]), int(date_text[8:10])
    return time.mktime((year, month, day, 12, 0, 0, 0, 0)) // 86400


def date_parts_of_day_number(day_number):
    parts = time.gmtime(int(day_number) * 86400 + 43200)
    return parts[0], parts[1], parts[2]  # year, month, day


def weekday_of_day_number(day_number):
    return time.gmtime(int(day_number) * 86400 + 43200)[6]  # 0 = Monday


def date_text_of_day_number(day_number):
    year, month, day = date_parts_of_day_number(day_number)
    return "%04d-%02d-%02d" % (year, month, day)


def _draw_heat_legend(P, y):
    # LESS [5 ramp boxes] MORE — shared by ACTIVITY and CALENDAR
    C = P.palette
    legend_x = 6
    legend_x += P.text("LESS", legend_x, y, C.text_dark, "legend_label", letter_spacing=1) + 4
    for level in range(1, 6):
        P.rect(legend_x, y - 1, 8, 8, C.heat_ramp[level])
        P.border(legend_x, y - 1, 8, 8, C.edge, 1)
        legend_x += 8 + 3
    P.text("MORE", legend_x + 1, y, C.text_dark, "legend_label", letter_spacing=1)


def draw_activity(P, stats_payload):
    C = P.palette
    totals = stats_payload.get("totals") or {}
    feed_meta = stats_payload.get("meta") or {}
    daily_activity = stats_payload.get("daily_activity") or []

    draw_chrome(P, "ACTIVITY", "TOKENS")  # top-right tag = active metric
    draw_section_label(P, "DAILY TOKENS", SECTION_LABEL_Y)

    # density block, row-major: oldest top-left, today bottom-right
    metric_key = day_metric_key()
    values = [day.get(metric_key, 0) for day in daily_activity]
    maximum_value = max(values) if values else 1
    maximum_value = maximum_value or 1
    day_count = len(values)
    total_cells = HEAT_ROWS * HEAT_COLUMNS
    for row in range(HEAT_ROWS):
        for column in range(HEAT_COLUMNS):
            cell_x = HEAT_X + column * (HEAT_CELL_WIDTH + HEAT_GAP)
            cell_y = HEAT_GRID_TOP + row * (HEAT_CELL_HEIGHT + HEAT_GAP)
            day_index = day_count - total_cells + (row * HEAT_COLUMNS + column)
            if day_index < 0 or day_index >= day_count:
                # not-yet-existing day: 1px outline
                P.border(cell_x, cell_y, HEAT_CELL_WIDTH, HEAT_CELL_HEIGHT, C.heat_zero, 1)
            else:
                level = heat_level(values[day_index], maximum_value,
                                   daily_activity[day_index].get("prompts", 0))
                P.rect(cell_x, cell_y, HEAT_CELL_WIDTH, HEAT_CELL_HEIGHT, C.heat_ramp[level])

    # corner labels with pixel triangles
    P.tri(6, 51, "l", C.text_dark)
    P.text("%d DAYS AGO" % (total_cells - 1), 14, 52, C.text_dark, "tag", letter_spacing=1)
    grid_bottom = HEAT_GRID_TOP + HEAT_ROWS * (HEAT_CELL_HEIGHT + HEAT_GAP) - HEAT_GAP
    P.tri(HEAT_RIGHT - 4, grid_bottom + 2, "r", C.text_dark)
    P.text("TODAY", HEAT_RIGHT - 4 - 4, grid_bottom + 3, C.text_dark, "tag",
           letter_spacing=1, align="r")

    _draw_heat_legend(P, 215)

    # 4-card right stack, alternating accents (shared card geometry)
    cards_x = 320 - 6 - 104
    cards_top = 56
    card_gap = 8
    card_rows = (
        ("STREAK", "%dD" % totals.get("current_streak", 0), 1),
        ("BEST", "%dD" % totals.get("longest_streak", 0), 2),
        ("ACTIVE", "%d/%d" % (totals.get("active_days", 0), feed_meta.get("corpus_days", 0)), 1),
        ("SESSIONS", format_integer_grouped(totals.get("sessions", 0)), 2),
    )
    for index, (label, value, accent_number) in enumerate(card_rows):
        draw_card(P, cards_x, cards_top + index * (CARD_HEIGHT + card_gap), 104,
                  label, value, accent_number)


def draw_calendar(P, stats_payload):
    C = P.palette
    daily_activity = stats_payload.get("daily_activity") or []
    feed_meta = stats_payload.get("meta") or {}

    draw_chrome(P, "CALENDAR", "TOKENS")  # top-right tag = active metric

    # index days by date; the ramp uses the whole-corpus max (like the heatmap)
    days_by_date = {}
    last_date_text = None
    for day in daily_activity:
        if day.get("date"):
            days_by_date[day["date"]] = day
            last_date_text = day["date"]
    metric_key = day_metric_key()
    values = [day.get(metric_key, 0) for day in daily_activity]
    maximum_value = (max(values) if values else 1) or 1

    # anchor "today" = the feed's last day; show the most recent 5 weeks
    # (Mon..Sun columns, oldest week on top)
    anchor_day = (
        day_number_from_date_text(last_date_text) if last_date_text
        else time.time() // 86400
    )
    calendar_rows = 5
    bottom_monday = anchor_day - weekday_of_day_number(anchor_day)
    grid_start_day = bottom_monday - (calendar_rows - 1) * 7

    columns = distribute_columns(6, 308, 7, 2)
    cell_height = 28
    row_gap = 2
    header_y = 46
    grid_y = 56
    for column, letter in enumerate(WEEKDAY_LETTERS):
        column_x, column_width = columns[column]
        P.text(letter, round(column_x + column_width / 2), header_y, C.text_dark,
               "tag", letter_spacing=1, align="c")

    span_first_day = None
    span_last_day = None
    for row in range(calendar_rows):
        for column in range(7):
            cell_day = grid_start_day + row * 7 + column
            date_text = date_text_of_day_number(cell_day)
            day_entry = days_by_date.get(date_text)
            column_x, column_width = columns[column]
            cell_y = grid_y + row * (cell_height + row_gap)
            if not day_entry or cell_day > anchor_day:
                P.border(column_x, cell_y, column_width, cell_height, C.heat_zero, 1)
                continue
            if span_first_day is None:
                span_first_day = cell_day
            span_last_day = cell_day
            level = heat_level(day_entry.get(metric_key, 0), maximum_value,
                               day_entry.get("prompts", 0))
            dark_cell = level >= 4
            P.rect(column_x, cell_y, column_width, cell_height, C.heat_ramp[level])
            year, month, day_of_month = date_parts_of_day_number(cell_day)
            if day_of_month == 1:  # month tag on the 1st
                P.text(MONTHS[month - 1], column_x + 3, cell_y + 3,
                       C.background if dark_cell else C.text_dark, "tag")
            P.text(str(day_of_month), column_x + column_width - 3,
                   cell_y + cell_height - 13,
                   C.background if dark_cell else C.text, "row_value", align="r")
            if date_text == last_date_text:  # today outline
                P.border(column_x, cell_y, column_width, cell_height, C.text, 1)

    # section label carries the visible date range ('-', Silkscreen has no arrow)
    if span_first_day is not None:
        _, first_month, first_day = date_parts_of_day_number(span_first_day)
        _, last_month, last_day = date_parts_of_day_number(span_last_day)
        span_text = " • %d %s - %d %s" % (
            first_day, MONTHS[first_month - 1], last_day, MONTHS[last_month - 1])
    else:
        span_text = ""
    draw_section_label(P, "DAILY TOKENS" + span_text, SECTION_LABEL_Y)

    _draw_heat_legend(P, 215)
    P.text("%d DAYS" % feed_meta.get("corpus_days", 0), 314, 215, C.text_dark,
           "legend_label", letter_spacing=1, align="r")


def draw_rhythm(P, stats_payload):
    C = P.palette
    totals = stats_payload.get("totals") or {}
    histograms = stats_payload.get("histograms") or {}

    draw_chrome(P, "RHYTHM", "PROMPTS")  # top-right tag = active metric
    draw_section_label(P, "BY HOUR • 0-23", SECTION_LABEL_Y)
    hours_y = 44
    hours_height = 84
    hours = histograms.get("hours") or []
    draw_vertical_bars(P, 6, hours_y, 308, hours_height, hours,
                       totals.get("peak_hour", -1), 2)
    hour_columns = distribute_columns(6, 308, 24, 2)
    hour_nudges = {12: -1, 18: -1}
    for hour in (0, 6, 12, 18, 23):
        column_x, column_width = hour_columns[hour]
        P.text(str(hour), round(column_x + column_width / 2) + hour_nudges.get(hour, 0),
               hours_y + hours_height + 2, C.text_dark, "axis_tick", align="c")

    draw_section_label(P, "BY WEEKDAY", 144)
    weekdays_y = 156
    weekdays_height = 54
    draw_vertical_bars(P, 6, weekdays_y, 308, weekdays_height,
                       histograms.get("weekdays") or [], totals.get("peak_weekday", -1), 6)
    weekday_columns = distribute_columns(6, 308, 7, 6)
    for index, letter in enumerate(WEEKDAY_LETTERS):
        column_x, column_width = weekday_columns[index]
        P.text(letter, round(column_x + column_width / 2),
               weekdays_y + weekdays_height + 2, C.text_dark, "axis_tick", align="c")


def draw_rhythm_matrix(P, stats_payload):
    C = P.palette
    weekday_hour = (stats_payload.get("histograms") or {}).get("weekday_hour") or []

    # busiest cell (peak weekday x hour)
    busiest_row = 0
    busiest_column = 0
    busiest_value = -1
    for row_index, row in enumerate(weekday_hour):
        for column_index, value in enumerate(row or []):
            if value > busiest_value:
                busiest_value = value
                busiest_row = row_index
                busiest_column = column_index

    draw_chrome(P, "RHYTHM MATRIX", "PROMPTS")  # top-right tag = active metric
    draw_section_label(P, "WEEKDAY × HOUR", SECTION_LABEL_Y)

    matrix_x = 18
    matrix_width = 296
    matrix_y = 52
    cell_height = 18
    row_gap = 3
    # 7 rows x 24 columns, heat-ramped over 4 active levels (rhythmMatrix())
    maximum_value = 1
    for row in weekday_hour:
        for value in row or []:
            if value > maximum_value:
                maximum_value = value
    columns = distribute_columns(matrix_x, matrix_width, 24, 1)
    for row in range(7):
        row_values = weekday_hour[row] if row < len(weekday_hour) else []
        for column in range(24):
            value = row_values[column] if column < len(row_values) else 0
            level = 0 if value == 0 else min(4, max(1, -(-value * 4 // maximum_value)))
            column_x, column_width = columns[column]
            P.rect(column_x, matrix_y + row * (cell_height + row_gap), column_width,
                   cell_height,
                   C.heat_zero if level == 0 else C.heat_ramp[level + 1])

    for row, letter in enumerate(WEEKDAY_LETTERS):  # weekday rail
        P.text(letter, 6, matrix_y + row * (cell_height + row_gap) + cell_height // 2 - 3,
               C.text_dark, "tag")
    axis_y = matrix_y + 7 * (cell_height + row_gap) + 1
    hour_nudges = {12: -1, 18: -1}
    for hour in (0, 6, 12, 18, 23):
        column_x, column_width = columns[hour]
        P.text(str(hour), round(column_x + column_width / 2) + hour_nudges.get(hour, 0),
               axis_y, C.text_dark, "axis_tick", align="c")

    if busiest_value > 0:
        busiest_text = "%s %02d-%02d" % (
            WEEKDAY_NAMES[busiest_row], busiest_column, (busiest_column + 1) % 24)
    else:
        busiest_text = "-"
    P.text("BUSIEST • " + busiest_text, 6, axis_y + 14, C.text_dark, "caption",
           letter_spacing=1)
