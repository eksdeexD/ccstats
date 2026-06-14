# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Host development entry point:
#
#   mpremote mount firmware exec "import dev_run"
#
# runs the firmware from the working tree (no copy step). Not used on-device.

# An interrupted launcher leaves a reset-on-HOME irq armed (badgeware.launch);
# disarm it so handling the badge does not hard-reset it mid-run. The
# installed app must NOT do this — there that irq is the exit-to-menu path.
BUTTON_HOME.irq(None)

import main

main.run_firmware()
