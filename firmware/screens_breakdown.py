# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# BREAKDOWN category — 1:1 ports of drawWords()/drawTools()/drawModels() from
# viewscreens/screens.js, including the rotating book-comparison line (the rotation
# itself is driven by the navigation loop via BOOK_CYCLE_MILLISECONDS).

import random
import re

from formatters import (
    format_compact,
    format_duration,
    format_integer_grouped,
    format_tokens,
)
from options import token_value
from screen_shared import (
    ROW_BAR_WIDTH,
    SECTION_LABEL_Y,
    distribute_columns,
    draw_bar_row,
    draw_card,
    draw_chrome,
    draw_section_label,
)

# Book-comparison table: words written vs famous books ("your words = Nx <title>").
# (title, author, word_count) — mirrors BOOKS in screens.js.
BOOKS = (
    ("Fahrenheit 451", "Ray Bradbury", 46000),
    ("Brave New World", "Aldous Huxley", 64000),
    ("Do Androids Dream?", "Philip K. Dick", 64000),
    ("Neuromancer", "William Gibson", 68000),
    ("Frankenstein", "Mary Shelley", 75000),
    ("Canticle for Leibowitz", "Walter M. Miller Jr.", 83000),
    ("Cryptonomicon", "Neal Stephenson", 412000),
    ("Atlas Shrugged", "Ayn Rand", 565000),
    ("Steppenwolf", "Hermann Hesse", 67000),
    ("The Glass Bead Game", "Hermann Hesse", 140000),
    ("The Alchemist", "Paulo Coelho", 39000),
    ("The Little Prince", "Antoine de Saint-Exupery", 17000),
    ("Jonathan Livingston Seagull", "Richard Bach", 10000),
    ("Zen in the Art of Archery", "Eugen Herrigel", 20000),
    ("Crime and Punishment", "Fyodor Dostoevsky", 211000),
    ("The Idiot", "Fyodor Dostoevsky", 242000),
    ("Manufacturing Consent", "Edward S. Herman & Noam Chomsky", 103000),
    ("1984", "George Orwell", 88942),
    ("Borderliners", "Peter Hoeg", 75000),
    ("Understanding Power", "Noam Chomsky", 125000),
    ("Necessary Illusions", "Noam Chomsky", 120000),
    ("Scattered Minds", "Gabor Mate", 85000),
    ("Beyond Chutzpah", "Norman Finkelstein", 100000),
    ("The Mustard Seed", "Bhagwan Shree Rajneesh", 140000),
    ("Free to Choose", "Milton & Rose Friedman", 88000),
    ("Sea-Wolf", "Jack London", 57000),
    ("I, Robot", "Isaac Asimov", 69000),
    ("Foundation", "Isaac Asimov", 68000),
    ("Dune", "Frank Herbert", 188000),
    ("Out of the Silent Planet", "C.S. Lewis", 58000),
    ("Notes from the Underground", "Fyodor Dostoevsky", 19000),
    ("The Silo Saga", "Hugh Howey", 360000),
    ("A Tale of Two Cities", "Charles J.H. Dickens", 135000),
    ("Great Expectations", "Charles J.H. Dickens", 183000),
    ("Oliver Twist", "Charles J.H. Dickens", 155000),
    ("The Road", "Cormac McCarthy", 58000),
    ("Animal Farm", "George Orwell", 29966),
    ("Homage to Catalonia", "George Orwell", 38000),
    ("Pelle the Conqueror", "Martin A. Nexo", 190000),
    ("A Clockwork Orange", "J. Anthony Burgess W.", 61000),
    ("Starship Troopers", "Robert A. Heinlein", 120000),
    ("Space Odyssey series", "Arthur C. Clarke", 260000),
    ("The Hobbit", "J.R.R. Tolkien", 95000),
    ("The Lord of the Rings", "J.R.R. Tolkien", 455000),
    ("The Silmarillion", "J.R.R. Tolkien", 130000),
    ("The Martian", "Andy Weir", 104000),
    ("A Song of Ice and Fire", "George R.R. Martin", 1770000),
    ("The Art of War", "Sun Tzu", 6500),
    ("Alice in Wonderland", "Lewis Carroll", 26000),
    ("Through the Looking Glass", "Lewis Carroll", 27000),
    ("Discworld", "Terry Pratchett", 8000000),
    ("Hyperion Cantos", "Dan Simmons", 450000),
    ("The Witcher Saga", "Andrzej Sapkowski", 350000),
    ("A New Earth", "Eckhart Tolle", 72000),
    ("The Handmaid's Tale", "Margaret E. Atwood", 100000),
    ("Misery", "Stephen King", 170000),
    ("The Iliad", "Homer", 152000),
    ("The Odyssey", "Homer", 121000),
    ("Ready Player One", "Ernest C. Cline", 137000),
    ("The Time Machine", "H.G. Wells", 32000),
)

BOOK_CYCLE_MILLISECONDS = 10000  # rotate to a fresh title every 10 s (BOOK_CYCLE_MS)
_book_line_index = -1


def cycle_book():
    # pick a fresh random title (never the same twice in a row)
    global _book_line_index
    while True:
        candidate = random.randrange(len(BOOKS))
        if candidate != _book_line_index or len(BOOKS) == 1:
            _book_line_index = candidate
            return


def draw_words(P, stats_payload):
    global _book_line_index
    C = P.palette
    totals = stats_payload.get("totals") or {}
    competition = stats_payload.get("competition") or {}
    my_metrics = (competition.get("me") or {}).get("metrics") or {}

    draw_chrome(P, "WORDS", "ALL TIME")
    draw_section_label(P, "HUMAN INPUT", SECTION_LABEL_Y)

    # two hero rows: WORDS (accent 1) + CHARACTERS TYPED (accent 2)
    user_words = totals.get("user_words", 0)
    P.text(format_compact(user_words), 6, 44, C.accent_primary, "hero_value",
           letter_spacing=1, shadow=(1, 1, C.accent_primary_shadow))
    P.text("WORDS WRITTEN", 314, 45, C.text_dark, "caption", letter_spacing=1, align="r")
    P.text(format_integer_grouped(totals.get("user_prompts", 0)) + " PROMPTS", 314, 57,
           C.text_dark, "caption", letter_spacing=1, align="r")
    P.text(format_compact(totals.get("user_chars_typed", 0)), 6, 86, C.accent_secondary,
           "hero_value", letter_spacing=1, shadow=(1, 1, C.accent_secondary_shadow))
    P.text("CHARACTERS", 314, 87, C.text_dark, "caption", letter_spacing=1, align="r")
    P.text("TYPED", 314, 99, C.text_dark, "caption", letter_spacing=1, align="r")

    # book line: "= Nx <TITLE>" + "BY <AUTHOR>"
    if user_words and BOOKS:
        if _book_line_index < 0 or _book_line_index >= len(BOOKS):
            _book_line_index = user_words % len(BOOKS)  # stable initial pick
        title, author, book_words = BOOKS[_book_line_index]
        multiple = user_words / book_words
        multiple_text = (
            "%d" % round(multiple) if multiple >= 10 else "%.1f" % (round(multiple * 10) / 10)
        )
        book_y = 128
        multiple_width = P.text("= %sX" % multiple_text, 6, book_y + 4, C.accent_primary,
                                "row_value", letter_spacing=1,
                                shadow=(1, 1, C.accent_primary_shadow))
        title_x = 6 + multiple_width + 8
        _, name_pixel_size = P.scale["row_label"]
        maximum_characters = int((314 - title_x) // (P.char_width(name_pixel_size) + 1))
        title = title.upper()
        if len(title) > maximum_characters:
            title = title[:maximum_characters]
        P.text(title, title_x, book_y, C.text, "row_label", letter_spacing=1)
        P.text("BY " + author.upper(), title_x, book_y + 11, C.text_dark, "caption",
               letter_spacing=1)

    # EFFORT — PROMPTS / LEVERAGE / BOTTLENECK cards
    draw_section_label(P, "EFFORT", 171)
    user_prompts = totals.get("user_prompts", 0)
    leverage = round(token_value(totals) / user_prompts) if user_prompts else 0
    columns = distribute_columns(6, 308, 3, 6)
    cards_y = 187
    draw_card(P, columns[0][0], cards_y, columns[0][1], "PROMPTS",
              format_integer_grouped(user_prompts), 1)
    draw_card(P, columns[1][0], cards_y, columns[1][1], "LEVERAGE",
              format_compact(leverage), 2)
    draw_card(P, columns[2][0], cards_y, columns[2][1], "BOTTLENK",
              format_duration(my_metrics.get("bottleneck_sec_total", 0)), 1)


def draw_tools(P, stats_payload):
    totals = stats_payload.get("totals") or {}
    tools = (stats_payload.get("top_tools") or [])[:8]
    maximum_count = (tools[0].get("count") or 1) if tools else 1

    draw_chrome(P, "TOOLS", format_integer_grouped(totals.get("tool_uses", 0)) + " USES")
    draw_section_label(P, "TOP TOOLS", SECTION_LABEL_Y)
    list_y = 48
    row_pitch = 22
    for index, tool in enumerate(tools):
        draw_bar_row(P, list_y + index * row_pitch, (tool.get("name") or "").upper(),
                     (tool.get("count") or 0) / maximum_count,
                     format_compact(tool.get("count", 0)), 1 if index == 0 else 2,
                     bar_width=ROW_BAR_WIDTH - 10)  # 10px shorter so high counts (10.2K+) clear the bar


def short_model_name(name):
    # "claude-opus-4-7" -> "OPUS 4.7"
    if not name:
        return "-"
    match = re.search(r"(opus|sonnet|haiku)\D*(\d+)\D+(\d+)", str(name).lower())
    if match:
        return "%s %s.%s" % (match.group(1).upper(), match.group(2), match.group(3))
    name = str(name)
    return (name[7:] if name.startswith("claude-") else name).upper()


def draw_models(P, stats_payload):
    C = P.palette
    models = sorted(stats_payload.get("models") or [],
                    key=lambda model: model.get("pct", 0), reverse=True)

    draw_chrome(P, "MODELS", "%d MODEL%s" % (len(models), "" if len(models) == 1 else "S"))
    draw_section_label(P, "MODEL SHARE", SECTION_LABEL_Y)

    # share palette: accent 1, accent 2, then both dimmed — repeats in order
    share_pens = (C.accent_primary, C.accent_secondary,
                  C.accent_primary_dim, C.accent_secondary_dim)
    share_top = models[:10]
    other_percent = max(0, 100 - sum(model.get("pct", 0) for model in share_top))
    segments = [
        (short_model_name(model.get("name")), model.get("pct", 0),
         share_pens[index % len(share_pens)])
        for index, model in enumerate(share_top)
    ]
    if len(models) > 10 and other_percent > 0.5:
        segments.append(("OTHER", other_percent, C.text_dark))

    # stacked share bar
    share_x = 6
    share_width = 308
    share_y = 44
    share_height = 12
    P.rect(share_x, share_y, share_width, share_height, C.track)
    cursor_x = share_x
    for _, percent, pen in segments:
        segment_width = round(share_width * percent / 100)
        P.rect(cursor_x, share_y, segment_width, share_height, pen)
        cursor_x += segment_width
    P.border(share_x, share_y, share_width, share_height, C.edge, 1)

    # legend — 5 per row, wraps to a second row for models 6-10
    per_row = 5
    legend_columns = distribute_columns(share_x, share_width, per_row, 4)
    legend_row_height = 11
    legend_y = share_y + share_height + 7
    for index, (label, _, pen) in enumerate(segments):
        column_x, _ = legend_columns[index % per_row]
        row_y = legend_y + (index // per_row) * legend_row_height
        P.rect(column_x, row_y - 2, 6, 6, pen)
        P.border(column_x, row_y - 2, 6, 6, C.edge, 1)
        P.text(label, column_x + 9, row_y - 1, C.text_dark, "model_share_label",
               letter_spacing=1)

    # per-model rows by turns — capped at 6, pitch squeezed to fit above the footer
    legend_rows = -(-len(segments) // per_row) if segments else 1
    by_turns_y = legend_y + (legend_rows - 1) * legend_row_height + 36
    draw_section_label(P, "BY TURNS", by_turns_y)
    turn_top = models[:6]  # the spec keeps the share (pct) order here
    maximum_turns = (turn_top[0].get("turns") or 1) if turn_top else 1
    list_y = by_turns_y + 14
    row_pitch = min(22, (222 - list_y) // len(turn_top)) if turn_top else 22
    for index, model in enumerate(turn_top):
        draw_bar_row(P, list_y + index * row_pitch, short_model_name(model.get("name")),
                     (model.get("turns") or 0) / maximum_turns,
                     format_compact(model.get("turns", 0)), 1 if index == 0 else 2,
                     name_role="model_turn_label")
