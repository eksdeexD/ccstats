# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Host development smoke test:
#
#   mpremote mount firmware exec "import dev_smoke"
#
# Boots, fetches once, then renders EVERY ported screen for a moment and
# reports per-screen success over serial — catches runtime errors on screens
# without button-walking to them. Ends on the first screen of the registry.

import time

BUTTON_HOME.irq(None)  # interrupted-launcher guard, like dev_run

import badgeware  # noqa: F401
import main
import screen_registry
import settings
from navigation import Navigation

settings.load()
badge.mode(HIRES | VSYNC)
main.apply_brightness(settings.get("brightness"))
main.boot_status_lines.clear()
main.draw_boot_screen()
main.join_wifi()
main.sync_clock()
stats_payload = main.fetch_stats_with_boot_report()

navigation = Navigation(main.boot_theme, stats_payload)
for category_index, (category_name, screens_in_category) in enumerate(navigation.categories):
    for screen_index, (screen_id, _) in enumerate(screens_in_category):
        navigation.category_index = category_index
        navigation.screen_index = screen_index
        try:
            started_ms = time.ticks_ms()
            navigation.draw()
            display.update()
            print("smoke OK %s/%s (%d ms)"
                  % (category_name, screen_id, time.ticks_diff(time.ticks_ms(), started_ms)))
        except Exception as error:
            print("smoke FAIL %s/%s -> %r" % (category_name, screen_id, error))
        time.sleep_ms(1200)

navigation.category_index = 0
navigation.screen_index = 0
navigation.draw()
display.update()
print("smoke test done")
