#!/usr/bin/env bash
# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Re-install the CODE from this repo after a `git pull`.  Run as root:  sudo ./server/deploy.sh
#
# Updates code ONLY for the components that are already installed. It NEVER touches your
# per-machine state — config.json, token.txt, ledger.db, or the generated JSON are left alone,
# so your settings and all-time stats survive every update.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root: sudo ./server/deploy.sh"; exit 1; }
REPO="$(cd "$(dirname "$0")" && pwd)"
OPT=/opt/claude-stats
WEB=/var/www/stats
SERVER="$(python3 -c 'import json;print(json.load(open("/opt/claude-stats/config.json")).get("server","main"))' 2>/dev/null || echo main)"

# 0) Timestamped restore point BEFORE we install new code or regenerate. Runs the freshly pulled
#    extract.py (so it works even on the first deploy that introduces backups). Consistent SQLite
#    snapshot of ledger.db + bottleneck.db + config. Retention is grandfather-father-son (every
#    intra-day point for the last 24h + the newest one per day for 30 days). Skips on a fresh box.
if [ -f "$OPT/ledger.db" ]; then
    python3 "$REPO/pipeline/extract.py" --mode backup \
        --ledger "$OPT/ledger.db" --bottleneck-db "$OPT/bottleneck.db" \
        --config "$OPT/config.json" --backups-dir "$OPT/backups" \
        && echo "backup: pre-deploy snapshot taken" || echo "backup: pre-deploy snapshot skipped (check manually)"
fi

# core (always)
install -d -m755 "$OPT"
install -m755 "$REPO/pipeline/extract.py"   "$OPT/extract.py"
install -m644 "$REPO/pipeline/pricing.json" "$OPT/pricing.json"
echo "updated: core (extract.py, pricing.json)"

# avatar content pack (badge message banks; served like the JSON feeds). Installed wherever the
# webroot exists. NOTE: deploy.sh OVERWRITES the deployed copy — to customize the lines, edit the
# repo copy (pipeline/content-pack.json) or re-apply your own after each deploy.
if [ -d "$WEB" ]; then
    install -m644 -o www-data -g www-data "$REPO/pipeline/content-pack.json" "$WEB/content-pack.json"
    echo "updated: content-pack.json (avatar message banks)"
    if command -v nginx >/dev/null && ! nginx -T 2>/dev/null | grep -q '/content-pack.json'; then
        echo "  ⚠ NOTE: your nginx vhost has no /content-pack.json location block, so the badge"
        echo "          can't fetch the message banks (it falls back to its baked-in defaults)."
        echo "          Add the block from nginx/stats-site.conf.template and reload nginx."
    fi
fi

# /viewscreens (dashboard, canvas/PicoGraphics-style).
# View sources live at the repo ROOT (viewscreens/), not under server/, so reach them via $REPO/..
# Installed on any box that already serves a dashboard — matches the new /viewscreens as well as a
# pre-migration /view or /view2 webroot (so the first post-migration deploy creates /viewscreens, and
# every later deploy keeps updating it once the old dirs are gone). Stays inert until the matching
# nginx location blocks exist (deploy.sh never edits vhosts).
if [ -d "$WEB/viewscreens" ] || [ -d "$WEB/view" ] || [ -d "$WEB/view2" ]; then
    VIEWSRC="$REPO/../viewscreens"
    install -d -m755 -o www-data -g www-data "$WEB/viewscreens" "$WEB/viewscreens/fonts"
    install -m644 -o www-data -g www-data "$VIEWSRC/index.html"     "$WEB/viewscreens/index.html"
    install -m644 -o www-data -g www-data "$VIEWSRC/pico.js"        "$WEB/viewscreens/pico.js"
    install -m644 -o www-data -g www-data "$VIEWSRC/screens.js"     "$WEB/viewscreens/screens.js"
    cp -a "$VIEWSRC/fonts/." "$WEB/viewscreens/fonts/"     # per-font subfolders + fonts.json (filenames may contain spaces)
    chown -R www-data:www-data "$WEB/viewscreens"
    echo "updated: /viewscreens"
    # Needs nginx location blocks (deploy.sh never edits vhosts). Warn if the live config predates them.
    if command -v nginx >/dev/null && ! nginx -T 2>/dev/null | grep -q '/viewscreens/screens.js'; then
        echo "  ⚠ NOTE: your nginx vhost is missing the /viewscreens, /viewscreens/pico.js,"
        echo "          /viewscreens/screens.js and /viewscreens/fonts/ blocks. Until you add them"
        echo "          (see nginx/stats-site.conf.template) /viewscreens will 403/404. Add those"
        echo "          blocks before the catch-all 'location /' and reload nginx."
    fi
fi

# live-activity monitor — only if already deployed
if [ -f "$OPT/live-monitor.py" ]; then
    install -m755 "$REPO/monitor/live-monitor.py" "$OPT/live-monitor.py"
    [ -d "$WEB/livetest" ] && install -m644 -o www-data -g www-data "$REPO/monitor/livetest-index.html" "$WEB/livetest/index.html"
    systemctl restart claude-live-monitor 2>/dev/null && echo "updated: live monitor (restarted)" || echo "updated: live monitor (service not running)"
fi

# session/weekly limits poller (CLAUDE MONITOR) — only if already deployed
if [ -f "$OPT/usage-monitor.py" ]; then
    install -m755 "$REPO/monitor/usage-monitor.py" "$OPT/usage-monitor.py"
    # cross-server limits: ensure the merge drop-zone exists so the poller's --merge-dir has somewhere
    # to read remotes' shipped readings (keeps the feed live when MAIN's own token is expired).
    # statsuser owns it if present; otherwise root:www-data until the first remote is provisioned
    # (provision-remote.sh re-chowns it to statsuser). Your usage-monitor cron must pass
    # --merge-dir $WEB/limits-remote — see server/README.md.
    if [ -d "$WEB" ]; then
        if id statsuser >/dev/null 2>&1; then
            install -d -m2775 -o statsuser -g www-data "$WEB/limits-remote"
        else
            install -d -m2775 -o root -g www-data "$WEB/limits-remote"
        fi
    fi
    echo "updated: usage monitor (limits feed; merge dir $WEB/limits-remote)"
fi

# durable HUMAN BOTTLENECK monitor — only if already deployed
if [ -f "$OPT/bottleneck-monitor.py" ]; then
    install -m755 "$REPO/monitor/bottleneck-monitor.py" "$OPT/bottleneck-monitor.py"
    systemctl restart claude-bottleneck-monitor 2>/dev/null && echo "updated: bottleneck monitor (restarted)" || echo "updated: bottleneck monitor (service not running)"
fi

# log rotation — keep the cron-driven /var/log/claude-stats*.log from growing unbounded. logrotate is
# a separate package (not systemd) but is part of the Debian/Ubuntu base and runs itself via
# logrotate.timer / cron.daily, so this policy needs no cron of our own. Always install (idempotent).
if [ -d /etc/logrotate.d ]; then
    install -m644 "$REPO/logrotate/ccstats.conf" /etc/logrotate.d/ccstats
    echo "updated: logrotate policy (/etc/logrotate.d/ccstats)"
else
    echo "  ⚠ NOTE: /etc/logrotate.d not found — install the 'logrotate' package, else"
    echo "          /var/log/claude-stats*.log will grow without bound."
fi

# pick up the latest stats immediately
/usr/bin/python3 "$OPT/extract.py" --mode full --server "$SERVER" \
    --fragments-dir "$WEB/fragments" --output "$WEB/claude-stats.json" >/dev/null 2>&1 \
    && chown www-data:www-data "$WEB/claude-stats.json" && echo "regenerated claude-stats.json" || echo "stats regen skipped (check manually)"


# refresh the head-to-head competition feed too, if in use
if [ -f "$WEB/competitor.json" ] || [ -f "$WEB/competition.json" ]; then
    /usr/bin/python3 "$OPT/extract.py" --mode competitor --server "$SERVER" --ledger "$OPT/ledger.db" \
        --config "$OPT/config.json" --limits-file "$WEB/claude-limits.json" --bottleneck-db "$OPT/bottleneck.db" \
        --peers-dir "$WEB/peers" --output "$WEB/competitor.json" --competition-output "$WEB/competition.json" \
        >/dev/null 2>&1 && chown www-data:www-data "$WEB/competitor.json" "$WEB/competition.json" 2>/dev/null \
        && echo "regenerated competition feed" || echo "competition regen skipped"
fi

if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1; then
    systemctl reload nginx && echo "nginx reloaded"
fi
echo "deploy done — code updated; config.json / token.txt / ledger.db untouched."
