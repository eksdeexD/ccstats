# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Shared screen building blocks — 1:1 ports of the /viewscreens screens.js helpers
# (chrome / card / bar / barRow / seclabel / cols / vbars). Every data screen
# composes these; pixel values come straight from the spec.

SCREEN_WIDTH = 320
SCREEN_HEIGHT = 240
HEADER_HEIGHT = 23
FOOTER_Y = 227  # footer band is 240 - FOOTER_Y = 13px tall
SECTION_LABEL_Y = 32  # shared y of the section label on every screen
CARD_HEIGHT = 35

# Critical-battery blink half-period: the single remaining bar is shown for one
# second, hidden the next (a 1 s on/off interval). navigation repaints just the
# icon rect on this cadence; draw_battery_icon reads the same clock.
BATTERY_BLINK_MILLISECONDS = 1000
_BATTERY_X = SCREEN_WIDTH - 6 - 16
_BATTERY_Y = 230

_offline_dot_pen = None  # fixed black, palette-independent (built lazily)


def _get_offline_dot_pen():
    global _offline_dot_pen
    if _offline_dot_pen is None:
        _offline_dot_pen = color.rgb(0, 0, 0)
    return _offline_dot_pen


# shared bar-row geometry (PROJECTS / TOOLS / MODELS / VERSUS / PROMPTS)
ROW_NAME_X = 6
ROW_NAME_WIDTH = 76
ROW_BAR_X = 86
ROW_BAR_WIDTH = 180
ROW_BAR_HEIGHT = 9
ROW_VALUE_RIGHT = 314


def draw_chrome(P, title, tag=None):
    # header bar + dashed rule + footer (clock, battery) — identical everywhere
    C = P.palette
    P.clear(C.background)
    P.rect(0, 0, SCREEN_WIDTH, HEADER_HEIGHT, C.title_bar)
    P.hline(0, HEADER_HEIGHT - 1, SCREEN_WIDTH, C.rim)
    P.text(P.title_override or title, 6, 6, C.accent_primary, "screen_title",
           shadow=(1, 1, C.accent_primary_shadow))

    # 16x16 spark at the far right (cross in accent 1, dots + centre in light)
    spark_x = SCREEN_WIDTH - 6 - 16
    spark_y = 3
    P.rect(spark_x + 7, spark_y, 2, 16, C.accent_primary)
    P.rect(spark_x, spark_y + 7, 16, 2, C.accent_primary)
    for dot_x, dot_y in ((3, 3), (11, 3), (3, 11), (11, 11)):
        P.rect(spark_x + dot_x, spark_y + dot_y, 2, 2, C.accent_primary_light)
    P.rect(spark_x + 6, spark_y + 6, 4, 4, C.accent_primary_light)
    if tag:
        P.text(tag, spark_x - 7, 9, C.text_dark, "tag", letter_spacing=1, align="r")

    # dashed rule (2px) directly under the header
    for dash_x in range(0, SCREEN_WIDTH, 8):
        P.rect(dash_x, HEADER_HEIGHT, 4, 2, C.line)

    # footer bar: status dot + clock (left), battery (right). The dot is the
    # connection light (user idea 2026-06-13): palette status pen while
    # fetches succeed, black while they are failing.
    P.rect(0, FOOTER_Y, SCREEN_WIDTH, SCREEN_HEIGHT - FOOTER_Y, C.title_bar)
    P.rect(6, 232, 4, 4, C.status if P.connection_online else _get_offline_dot_pen())
    P.text(P.clock_text or "--:--", 13, 231, C.text_dark, "tag", letter_spacing=1)
    draw_battery_icon(P)


def draw_battery_icon(P):
    """The footer fuel gauge. P carries the gauge state (set by navigation):
    battery_cells (0..4), battery_critical, battery_static_empty,
    battery_charging. Drawn whole by draw_chrome, and on its own by
    navigation's 1 Hz repaint (the critical blink and the charging sweep) — so
    it repaints just this rect (background first, so an off-frame erases the
    bars) without a full-screen redraw."""
    C = P.palette
    # erase the icon footprint (body + terminal) to the footer bar colour
    P.rect(_BATTERY_X, _BATTERY_Y, 17, 8, C.title_bar)
    # body is 15 wide (not 14) so the four bars clear BOTH inner walls by 1px
    P.border(_BATTERY_X, _BATTERY_Y, 15, 8, C.text_dark, 1)
    P.rect(_BATTERY_X + 15, _BATTERY_Y + 2, 2, 4, C.text_dark)  # terminal
    cells = getattr(P, "battery_cells", 4)
    if getattr(P, "battery_charging", False):
        # charging sweep: fill 1 -> 2 -> 3 -> 4 -> 1 at a 1 s interval
        cells = (badge.ticks // BATTERY_BLINK_MILLISECONDS) % 4 + 1
    elif getattr(P, "battery_critical", False):
        if getattr(P, "battery_static_empty", False):
            cells = 0  # save-mode static: show an empty battery, never blink
        else:
            # blink the single remaining bar on/off at a 1 s interval
            cells = 1 if (badge.ticks // BATTERY_BLINK_MILLISECONDS) % 2 == 0 else 0
    for cell in range(cells):
        P.rect(_BATTERY_X + 2 + cell * 3, _BATTERY_Y + 2, 2, 4, C.status)


def draw_section_label(P, label, y):
    # 5x5 square bullet + tracked label + trailing 2x2 dotted line
    C = P.palette
    P.rect(6, y, 5, 5, C.text_dark)
    label_width = P.text(label, 16, y, C.text_dark, "section_label", letter_spacing=2)
    dot_x = 16 + label_width + 5
    while dot_x < 314:
        P.rect(dot_x, y + 2, 2, 2, C.line)
        dot_x += 6


def draw_card(P, x, y, width, label, value, accent_number):
    # accent-bordered label+value stat box (35px tall everywhere)
    C = P.palette
    accent, accent_dark, _, accent_shadow = C.accent_pens(accent_number)
    P.rect(x, y, width, CARD_HEIGHT, C.panel)
    P.border(x, y, width, CARD_HEIGHT, accent_dark, 2)
    P.border(x + 2, y + 2, width - 4, CARD_HEIGHT - 4, C.edge, 1)
    P.rect(x + 8, y + 8, 4, 4, accent)  # accent dot
    P.text(label, x + 16, y + 7, C.text_dark, "row_label", letter_spacing=1)
    P.text(value, x + 8, y + 18, accent, "row_value", letter_spacing=1, shadow=(1, 1, accent_shadow))


# 2px checkerboard as an 8x8 pattern-brush bitmap (one shape call instead of
# hundreds of 2x2 rects — frame time matters for input responsiveness).
# Pattern bits anchor to SCREEN origin; tiles are 2px so only the parity of
# (x//2 + y//2) matters — pick the phase that puts colour A at the bar origin,
# like the CSS conic checker anchored to the element.
_CHECKER_A_FIRST = (0b11001100,) * 2 + (0b00110011,) * 2 + (0b11001100,) * 2 + (0b00110011,) * 2
_CHECKER_B_FIRST = (0b00110011,) * 2 + (0b11001100,) * 2 + (0b00110011,) * 2 + (0b11001100,) * 2


def draw_bar(P, x, y, width, height, fraction, accent_number):
    # track + accent checker fill (2px tiles of colour/dark) + 2px top highlight
    C = P.palette
    accent, accent_dark, accent_light, _ = C.accent_pens(accent_number)
    P.rect(x, y, width, height, C.track)
    P.border(x, y, width, height, C.edge, 2)
    fill_width = max(0, min(width, round(width * fraction)))
    if fill_width > 0:
        origin_parity = ((x // 2) + (y // 2)) % 2
        rows = _CHECKER_A_FIRST if origin_parity == 0 else _CHECKER_B_FIRST
        screen.pen = brush.pattern(accent, accent_dark, rows)
        screen.shape(shape.rectangle(int(x), int(y), int(fill_width), int(height)))
        P.rect(x, y, fill_width, 2, accent_light)


def draw_bar_row(
    P, y, name, fraction, value, accent_number,
    sub_line_1=None, sub_line_2=None, name_role=None, bar_x=None, bar_width=None,
):
    # NAME (left) + progress bar + VALUE (right) + up to two dim sub-lines.
    # One definition so PROJECTS/TOOLS/MODELS/VERSUS/PROMPTS rows are identical.
    C = P.palette
    name_role = name_role or "row_label"
    bar_x = bar_x if bar_x is not None else ROW_BAR_X
    bar_width = bar_width if bar_width is not None else ROW_BAR_WIDTH

    _, name_pixel_size = P.scale[name_role]
    maximum_characters = ROW_NAME_WIDTH // (P.char_width(name_pixel_size) + 1)
    if len(name) > maximum_characters:
        name = name[:maximum_characters]
    P.text(name, ROW_NAME_X, y, C.text, name_role, letter_spacing=1)
    draw_bar(P, bar_x, y, bar_width, ROW_BAR_HEIGHT, fraction, accent_number)
    accent = C.accent_pens(accent_number)[0]
    P.text(value, ROW_VALUE_RIGHT, y, accent, "row_value", align="r")
    if sub_line_1:
        P.text(sub_line_1, ROW_BAR_X, y + 14, C.text_dark, "caption", letter_spacing=1)
    if sub_line_2:
        P.text(sub_line_2, ROW_BAR_X, y + 25, C.text_dark, "caption", letter_spacing=1)


def distribute_columns(x, width, count, gap):
    # pixel-exact n columns across `width` (cols() in the spec): fills exactly,
    # remainder pixels spread over the leftmost columns. Returns [(x, w), ...].
    total_gap = (count - 1) * gap
    base_width = (width - total_gap) // count
    remainder = (width - total_gap) - base_width * count
    columns = []
    cursor_x = x
    for index in range(count):
        column_width = base_width + (1 if index < remainder else 0)
        columns.append((cursor_x, column_width))
        cursor_x += column_width + gap
    return columns


def draw_vertical_bars(P, x, y, width, height, values, peak_index, gap):
    # bottom-aligned bar chart: peak bar accent 1, rest accent 2, zero = stub
    C = P.palette
    if not values:
        return
    maximum_value = max(values) or 1
    columns = distribute_columns(x, width, len(values), gap)
    minimum_bar_height = round(height * 0.12)
    for index, value in enumerate(values):
        column_x, column_width = columns[index]
        is_peak = index == peak_index
        if value == 0:
            P.rect(column_x, y + height - 2, column_width, 2, C.accent_secondary_zero)
            continue
        bar_height = max(minimum_bar_height, round(value / maximum_value * height))
        bar_y = y + height - bar_height
        P.rect(column_x, bar_y, column_width, bar_height,
               C.accent_primary if is_peak else C.accent_secondary)
        P.rect(column_x, bar_y, column_width, min(2, bar_height),
               C.accent_primary_light if is_peak else C.accent_secondary_light)
