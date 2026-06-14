# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Device secrets — copy to firmware/secrets.py, fill in, flash to the device.
# secrets.py is gitignored and must NEVER be committed.

WIFI_SSID = "your-wifi-ssid"
WIFI_PASSWORD = "your-wifi-password"

# OPTIONAL: several networks in priority order — boot scans and joins the
# first one it can (falling through on failure; hidden SSIDs are tried last).
# When set, WIFI_SSID/WIFI_PASSWORD above are ignored.
# WIFI_NETWORKS = (
#     ("home-wifi", "home-password"),
#     ("office-wifi", "office-password"),
#     ("phone-hotspot", "hotspot-password"),
# )

# Base URL of your stats server (no trailing slash) + its access token.
# Feeds: /claude-stats.json /claude-limits.json /competition.json /live-status.json
STATS_BASE_URL = "https://stats.example.net"
STATS_TOKEN = "paste-your-access-token"

# Display name shown on the badge (config, never hardcoded in firmware).
ALIAS = "YourName"
