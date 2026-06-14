# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# The avatar content pack — every message bank in one place, server-syncable.
#
# The banks below are the BAKED DEFAULTS (ported verbatim from viewscreens/screens.js).
# A server-side /content-pack.json (same token gate as the other feeds) can
# override any bank without a firmware release: the FeedScheduler fetches it
# daily, apply() swaps the banks in and persists the raw JSON to flash so the
# pack survives reboots and works offline. Anything missing from the server
# pack keeps its default; a bad pack is rejected wholesale. The badge picks
# WHICH line to show locally (no-immediate-repeat random) — the server only
# supplies the material. Schema & authoring rules: docs/schema.md (content-pack.json).

import json

DEVICE_PACK_PATH = "/content-pack.json"
EXPECTED_SCHEMA_VERSION = 1

DEFAULTS = {
    # the working word ticker (ALL-CAPS: lowercase 'i' is missing from the pixel fonts)
    "working_words": (
        "ACCOMPLISHING", "ACTIONING", "ACTUALIZING", "BAKING", "BOOPING", "BREWING",
        "CALCULATING", "CEREBRATING", "CHANNELLING", "CHURNING", "CLAUDING", "COALESCING",
        "COGITATING", "COMPUTING", "COMBOBULATING", "CONCOCTING", "CONSIDERING",
        "CONTEMPLATING", "COOKING", "CRAFTING", "CREATING", "CRUNCHING", "DECIPHERING",
        "DELIBERATING", "DETERMINING", "DISCOMBOBULATING", "DOING", "EFFECTING",
        "ELUCIDATING", "ENCHANTING", "ENVISIONING", "FINAGLING", "FLIBBERTIGIBBETING",
        "FORGING", "FORMING", "FROLICKING", "GENERATING", "GERMINATING", "HATCHING",
        "HERDING", "HONKING", "IDEATING", "IMAGINING", "INCUBATING", "INFERRING",
        "MANIFESTING", "MARINATING", "MEANDERING", "MOSEYING", "MULLING", "MUSTERING",
        "MUSING", "NOODLING", "PERCOLATING", "PERUSING", "PHILOSOPHISING", "PONTIFICATING",
        "PONDERING", "PROCESSING", "PUTTERING", "PUZZLING", "RETICULATING", "RUMINATING",
        "SCHEMING", "SCHLEPPING", "SHIMMYING", "SIMMERING", "SMOOSHING", "SPELUNKING",
        "SPINNING", "STEWING", "SUMMONING", "SUSSING", "SYNTHESIZING", "THINKING",
        "TINKERING", "TRANSMUTING", "UNFURLING", "UNRAVELLING", "VIBING", "WANDERING",
        "WHIRRING", "WIBBLING", "WORKING", "WRANGLING",
    ),
    # HUMAN BOTTLENECK quips: tier 0 gentle (0-3 min) / 1 nudging (3-6) / 2 dramatic (6+)
    "bottleneck_tiers": (
        ("Awaiting human input.", "Standing by.", "Ready when you are.",
         "Take your time.", "Awaiting your move."),
        ("WHAT'S UP?", "Still here.", "Any day now.",
         "I could've written a poem by now.", "Tick... tock..."),
        ("HELLO?", "ARE YOU OKAY?", "BETA TESTING?", "...",
         "Did you fall asleep?", "I'll wait. Forever, apparently."),
    ),
    "book_taunts": (
        'Could\'ve written "{book}" by now.',
        '"{book}"? Done. Still waiting.',
        'Wrote "{book}" already. You?',
        'A whole "{book}", while you ponder.',
    ),
    "limit_lines": (
        "Someone's been efficient! {pct}% {window} limit, wow.",
        "{pct}% of the {window} limit. Easy, tiger.",
        "Whoa - {pct}% {window} used. Pace yourself.",
        "{window} limit at {pct}%. Living dangerously.",
        "{pct}%?! Save some for tomorrow.",
        "Sweating a little here: {pct}% {window}.",
        "{pct}% {window} limit. No pressure. (Pressure.)",
    ),
    "streak_lines": (
        "6 hours to save the streak.", "Don't let the streak die like this.",
        "The robot is judging your idleness.", "Tick tock... the streak is waiting.",
        "One prompt keeps it alive.", "Your streak called. It's lonely.",
        "Midnight's coming for your streak.", "No activity today. Brave choice.",
        "A streak unkindled is a streak undone.", "Feed the fire before midnight.",
    ),
    # celebration bubble lines (record-break / trophy tier-up directives)
    "record_lines": (
        "New personal best!", "Record smashed!", "A new high score.",
        "You've outdone yourself.", "Best. Run. Ever.", "That's a new record.",
        "History, made.",
    ),
    "trophy_lines": (
        "New trophy unlocked!", "Achievement get!", "Leveled up.",
        "Shiny new badge.", "Tier up!", "You earned this.", "Add it to the shelf.",
    ),
    # idle quotes ({"q": text, "a": author} — author stored, not shown, like the web)
    "quotes": (
        {"q": "I'm not afraid of contradicting myself, because to me it seems that a man who remains consistent his whole life must be an idiot.", "a": "Bhagwan Shree Rajneesh"},
        {"q": "Imagination is more important than knowledge.", "a": "Albert Einstein"},
        {"q": "Facts do not cease to exist because they are ignored.", "a": "Aldous Huxley"},
        {"q": "The chief cause of problems is solutions.", "a": "Eric Sevareid"},
        {"q": "The first principle is that you must not fool yourself - and you are the easiest person to fool.", "a": "Richard Feynman"},
        {"q": "Extraordinary claims require extraordinary evidence.", "a": "Carl Sagan"},
        {"q": "Anyone who believes exponential growth can go on forever in a finite world is either a madman or an economist.", "a": "Kenneth Boulding"},
    ),
}

_active_banks = dict(DEFAULTS)


def bank(name):
    return _active_banks[name]


def _validated_banks(pack_payload):
    """The pack's recognised banks, shallow-checked; raises on a bad pack."""
    if pack_payload["meta"]["schema_version"] != EXPECTED_SCHEMA_VERSION:
        raise ValueError("content pack schema %r" % pack_payload["meta"]["schema_version"])
    overrides = {}
    for name, default in DEFAULTS.items():
        if name not in pack_payload:
            continue
        replacement = pack_payload[name]
        if not isinstance(replacement, (list, tuple)) or not replacement:
            raise ValueError("bank %s is empty or not a list" % name)
        overrides[name] = replacement
    return overrides


def apply(pack_payload, persist=True):
    """Swap in a fetched pack (all-or-nothing) and persist it to flash.
    Returns True when accepted."""
    try:
        overrides = _validated_banks(pack_payload)
    except (KeyError, TypeError, ValueError) as error:
        print("content pack rejected:", error)
        return False
    _active_banks.update(overrides)
    if persist:
        serialized = json.dumps(pack_payload)
        try:
            # skip the flash write when the pack is unchanged (boot re-applies
            # the same pack every day otherwise)
            with open(DEVICE_PACK_PATH) as pack_file:
                already_persisted = pack_file.read() == serialized
        except OSError:
            already_persisted = False
        if not already_persisted:
            try:
                with open(DEVICE_PACK_PATH, "w") as pack_file:
                    pack_file.write(serialized)
            except OSError as error:
                print("content pack not persisted:", error)
    print("content pack v%s applied (%d banks)"
          % (pack_payload["meta"].get("pack_version", "?"), len(overrides)))
    return True


def load_persisted():
    """Boot-time: restore the last synced pack from flash (offline support)."""
    try:
        with open(DEVICE_PACK_PATH) as pack_file:
            pack_payload = json.load(pack_file)
    except (OSError, ValueError):
        return  # no pack yet (or unreadable) — the baked defaults stand
    apply(pack_payload, persist=False)


load_persisted()
