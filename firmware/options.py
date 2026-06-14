# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Runtime user options (the /viewscreens _OPTS equivalent), backed by the
# persistent settings store. Accessors, not constants: a from-import of a
# value would freeze it at import time and the OPTIONS editors change these
# at runtime — screens call these at draw time instead.

import settings


def token_mode():
    return settings.get("token_mode")  # 'nocache' = input+output; 'all' = + cache


# The CLAUDE CODE avatar screen has two configurable info lines. Each can show a
# utilization bar (mine = accent1, the rival's = accent2), the daily
# tokens/prompts/words line, or nothing. Cycle order = AVATAR_LINE_MODES; the
# OPTIONS editor shows the AVATAR_LINE_LABELS text. Stored as avatar_line_1/_2.
AVATAR_LINE_MODES = ("my_session", "rival_session", "my_weekly", "rival_weekly",
                     "daily_stats", "none")
AVATAR_LINE_LABELS = {
    "my_session": "MY SESSION",
    "rival_session": "RIVAL SESSION",
    "my_weekly": "MY WEEKLY",
    "rival_weekly": "RIVAL WEEKLY",
    "daily_stats": "DAILY STATS",
    "none": "NONE",
}


def avatar_line(slot):
    return settings.get("avatar_line_%d" % slot)  # slot 1 or 2 -> AVATAR line mode


def token_value(record):
    # tokVal(): resolve any record carrying token fields to one number per mode.
    if not record:
        return 0
    if token_mode() == "all":
        return record.get("tokens_total", 0)
    return record.get("tokens_input", 0) + record.get("tokens_output", 0)


def day_metric_key():
    # the per-day series field matching the token mode (daily_activity rows)
    return "tokens" if token_mode() == "all" else "tokens_io"
