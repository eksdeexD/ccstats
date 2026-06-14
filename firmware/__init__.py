# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# ccstats badge-app entry point — launched from the badgeware menu when the
# firmware directory is installed as /system/apps/ccstats. The host dev loop
# uses dev_run.py instead.

import sys
import time

# The launcher chdirs into the app directory; make both the app modules and
# the device root (where /secrets.py lives) importable.
sys.path.insert(0, "/system/apps/ccstats")
sys.path.insert(0, "/")

import main

main.run_firmware()  # boots, then enters the navigation loop (never returns)

# Belt and braces: if the loop ever exits, hold the last frame. The
# launcher's HOME-button irq is the exit path (resets back to the menu).
while True:
    badge.poll()
    time.sleep_ms(100)
