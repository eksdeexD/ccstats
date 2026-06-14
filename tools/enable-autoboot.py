#!/usr/bin/env python3
# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Patch the badge's launcher menu so a cold boot goes straight into ccstats.

Behaviour after patching:
  - power-on / RESET button (PWRON reset cause)  -> launch /system/apps/ccstats
  - HOME pressed inside an app (watchdog reset)  -> show the launcher menu
  - mpremote reset (also watchdog)               -> show the launcher menu
  - a /state/ccstats-launch-once marker present  -> launch ccstats once (any
    reset cause), then delete the marker

The app's AUTO BOOT setting (auto_boot in /state/ccstats.json, edited on the
OPTIONS DISPLAY screen) turns the PWRON behaviour on/off without re-patching.
The launch-once marker is dropped by install-app.py so a deploy (which ends in
an mpremote/watchdog reset) lands in the app instead of the menu; it bypasses
both the reset-cause check and the AUTO BOOT setting and fires exactly once.

The patch wraps the menu's update() right before its `on_exit = run(update)`
line, using the device's installed menu as the base. Re-running on a patched
menu replaces the old block with the current one (safe to repeat). After a
Pimoroni firmware update restores the stock menu, just re-run this tool. To
revert, restore the stock file from the pimoroni/tufty2350 repo
(firmware/apps/menu/__init__.py).

Usage: tools/enable-autoboot.py [path-to-mpremote]
"""

import base64
import os
import subprocess
import sys
import tempfile

MENU_PATH = "/system/apps/menu/__init__.py"
PATCH_MARKER = "ccstats auto-boot"
HOOK_LINE = "on_exit = run(update).result"

AUTO_BOOT_BLOCK = '''
# --- ccstats auto-boot (inserted by ccstats/tools/enable-autoboot.py) ---
# Cold boots (power-on / RESET button = PWRON cause) go straight into the
# ccstats app; HOME inside an app reboots via the watchdog (WDT cause), which
# lands here and shows the menu instead. The app's AUTO BOOT user setting
# (auto_boot in its settings file) turns the whole behaviour off.
import json as _ccstats_json
import machine as _ccstats_machine
import os as _ccstats_os

_ccstats_boot_app = "/system/apps/ccstats"
_ccstats_launch_marker = "/state/ccstats-launch-once"


def _ccstats_auto_boot_enabled():
    try:
        with open("/state/ccstats.json") as state_file:
            return _ccstats_json.load(state_file).get("auto_boot", True)
    except (OSError, ValueError):
        return True  # no settings saved yet -> auto-boot stays on


def _ccstats_consume_launch_marker():
    # the installer (install-app.py) drops this file to request a one-shot
    # launch on the very next boot, so a deploy lands in the app instead of the
    # menu. Delete it as we read it so it fires exactly once; afterwards the
    # normal PWRON/auto_boot behaviour resumes. Bypasses both the reset-cause
    # check and the AUTO BOOT setting — it's an explicit "launch now" request.
    try:
        _ccstats_os.stat(_ccstats_launch_marker)
    except OSError:
        return False
    try:
        _ccstats_os.remove(_ccstats_launch_marker)
    except OSError:
        pass
    return True


_ccstats_auto_boot = file_exists(_ccstats_boot_app + "/__init__.py") and (
    _ccstats_consume_launch_marker()
    or (
        _ccstats_machine.reset_cause() == _ccstats_machine.PWRON_RESET
        and _ccstats_auto_boot_enabled()
    )
)

_ccstats_menu_update = update

# the menu title-cases directory names ("ccstats" -> "Ccstats"); ours is an
# acronym, so fix the scanned entry up after the fact. The icon TILE colour
# is also pinned to the ccstats accent-1 orange (#ff6422): the menu picks
# tile colours by grid slot from its bold/faded lists, so the original draw
# runs with this app's slot temporarily swapped (the icon.png glyph is dark
# for contrast, like the logo).
_ccstats_tile_bold = color.rgb(255, 100, 34)
_ccstats_tile_faded = color.rgb(255, 100, 34, 120)

# the bold/faded tile-colour lists are APP.PY module globals — the original
# draw() sees them from its own module scope; this block (menu __init__
# scope) must reach them through the module object
import app as _ccstats_menu_app_module

for _ccstats_menu_app in apps.apps:
    if _ccstats_menu_app.path == "ccstats":
        _ccstats_menu_app.name = "CCSTATS"

        def _ccstats_tile_draw(menu_app=_ccstats_menu_app):
            slot = menu_app.index % 6
            bold = _ccstats_menu_app_module.bold
            faded = _ccstats_menu_app_module.faded
            bold_backup, faded_backup = bold[slot], faded[slot]
            bold[slot], faded[slot] = _ccstats_tile_bold, _ccstats_tile_faded
            try:
                type(menu_app).draw(menu_app)
            finally:
                bold[slot], faded[slot] = bold_backup, faded_backup

        _ccstats_menu_app.draw = _ccstats_tile_draw


def update():
    global _ccstats_auto_boot
    if _ccstats_auto_boot:
        _ccstats_auto_boot = False
        return _ccstats_boot_app
    return _ccstats_menu_update()
# --- end ccstats auto-boot ---

'''

BLOCK_BEGIN = "# --- ccstats auto-boot"
BLOCK_END = "# --- end ccstats auto-boot ---\n"

INSTALLER_TEMPLATE = '''\
import binascii
import os
import rp2
import vfs

os.umount("/system")
user_flash_size = rp2.Flash().ioctl(4, 0) * rp2.Flash().ioctl(5, 0)
fat_block_device = rp2.Flash(start=0, len=user_flash_size - 1024 * 1024)
vfs.mount(vfs.VfsFat(fat_block_device), "/system")

content = binascii.a2b_base64(%r)
with open(%r, "wb") as file:
    file.write(content)
print("menu patched,", len(content), "bytes")
'''


def main():
    mpremote_binary = sys.argv[1] if len(sys.argv) > 1 else "mpremote"

    menu_source = subprocess.run(
        [mpremote_binary, "cat", MENU_PATH], capture_output=True, check=True
    ).stdout.decode()
    # the stock menu ships with CRLF line endings — normalize so the block
    # markers (and HOOK_LINE) match regardless of terminator style
    menu_source = menu_source.replace("\r\n", "\n").replace("\r", "\n")

    if PATCH_MARKER in menu_source:
        # strip the previously inserted block, then re-insert the current one
        begin = menu_source.find(BLOCK_BEGIN)
        end = menu_source.find(BLOCK_END)
        if begin == -1 or end == -1:
            sys.exit("found the patch marker but not the block bounds — "
                     "inspect %s by hand" % MENU_PATH)
        menu_source = menu_source[:begin] + menu_source[end + len(BLOCK_END):]
        print("existing patch removed — re-patching with the current block")
    if HOOK_LINE not in menu_source:
        sys.exit(
            "could not find %r in the installed menu — the menu changed "
            "upstream; update this tool before patching" % HOOK_LINE
        )

    patched_source = menu_source.replace(HOOK_LINE, AUTO_BOOT_BLOCK + HOOK_LINE)
    encoded = base64.b64encode(patched_source.encode()).decode()

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as installer:
        installer.write(INSTALLER_TEMPLATE % (encoded, MENU_PATH))
        installer_path = installer.name
    try:
        subprocess.run([mpremote_binary, "run", installer_path], check=True)
        subprocess.run([mpremote_binary, "reset"], check=True)
        print("done — power-cycle (or RESET) now boots into ccstats; HOME returns to the menu")
    finally:
        os.unlink(installer_path)


if __name__ == "__main__":
    main()
