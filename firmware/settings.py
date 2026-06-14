# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Persistent user settings — the single store behind every OPTIONS screen.
#
# One flat dict, flashed through badgeware's State API (/state/ccstats.json —
# device flash, NOT the read-only /system mount, so it survives reinstalls).
# load() runs once at boot; update() writes through immediately on change, so
# a setting is never lost to a battery pull. Consumers read with get() at
# draw/use time (never from-import a value — that freezes it at import time).
#
# Keys are config contract: they are written to flash, so renaming one orphans
# the stored value. Keep them stable once shipped (like names.py screen ids).

import badgeware  # noqa: F401 -- injects the State API into builtins

STATE_APP_NAME = "ccstats"

DEFAULTS = {
    "palette": "DEFAULT",  # palette preset name (theme.PALETTE_PRESETS)
    "font_preset": "preset1",  # type-scale preset key (type_scale.FONT_PRESETS)
    "sprite_name": "gloom",  # active avatar sprite (avatar_frames.SPRITES)
    "brightness": 0.85,  # UI 0.0-1.0 over the USABLE backlight range (main.apply_brightness)
    "dim_on_battery": True,  # battery drops the panel to the dimmest usable level
    "token_mode": "nocache",  # 'nocache' = input+output only; 'all' = + cache
    "boot_screen": "avatar",  # screen id shown after boot (names.py ids)
    "animation_speed": 1.0,  # avatar stage-frame cadence multiplier
    "avatar_line_1": "my_session",  # top AVATAR info line (options.AVATAR_LINE_MODES)
    "avatar_line_2": "daily_stats",  # second AVATAR info line (default = tokens/prompts/words)
    "hidden_screens": [],  # screen ids removed from navigation
    "auto_boot": True,  # PWRON reset launches ccstats (launcher patch)
    "battery_saver_off": False,  # True = full cadences + animation on battery
    "avatar_cycle_minutes": 0,  # sprite auto-cycle interval; 0 = off
}

_values = dict(DEFAULTS)


def load():
    """Read the saved settings over the defaults (State.load also writes the
    defaults file on first boot). Call once, before anything reads get()."""
    _values.update(DEFAULTS)  # unsaved new keys always have their default
    State.load(STATE_APP_NAME, _values)


def get(key):
    return _values[key]


def update(key, value):
    """Write one setting through to flash (no-op when unchanged)."""
    if _values.get(key) == value:
        return
    _values[key] = value
    State.save(STATE_APP_NAME, _values)
