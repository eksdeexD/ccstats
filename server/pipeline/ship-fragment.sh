#!/bin/sh
# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# FRAGMENT-NODE uploader — pushes this box's readings UP to the MAIN stats server over sftp.
# Installed to /opt/claude-stats/ship-fragment.sh by provision-remote.sh and run by the every-minute
# root cron it sets up. Args (kept positional to avoid all quoting pitfalls):
#   $1 = this node's label        $2 = statsuser@main-domain (the sftp upload target)
# The data key is sftp-only and write-jailed by filesystem perms to /var/www/stats/{fragments,limits-remote}.
set -eu

LABEL="$1"
DEST="$2"
SFTP="/usr/bin/sftp -q -b - -i /root/.ssh/ccstats_frag -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

# 1) all-time stats fragment — MAIN folds it into the global totals on its next --mode full run.
/usr/bin/python3 /opt/claude-stats/extract.py --mode fragment --server "$LABEL" --output /tmp/ccstats-fragment.json
printf 'put /tmp/ccstats-fragment.json /var/www/stats/fragments/%s.json\n' "$LABEL" | $SFTP "$DEST"

# 2) session/weekly LIMITS reading — ship it so MAIN can serve the freshest reading across every box.
# Rate limits are GLOBAL per Anthropic account and this whole system runs ONE account, so a reading
# taken on ANY box is the same truth. MAIN runs usage-monitor.py with --merge-dir, picking the freshest
# non-stale reading across {its own poll} ∪ {remotes' shipped files}. That keeps the USAGE feed live
# whenever a session is active ANYWHERE — even if MAIN's own token has been expired for months.
# usage-monitor.py self-gates: with no active local token it writes a *stale* payload, which MAIN's
# merge ignores; with an active session it writes a fresh one MAIN will serve. Best-effort: a limits
# hiccup must never block the stats upload above, so each step is guarded.
if [ -f /opt/claude-stats/usage-monitor.py ]; then
  if /usr/bin/python3 /opt/claude-stats/usage-monitor.py --server "$LABEL" \
       --output /tmp/ccstats-limits.json --no-chown --no-limit-hits \
       --poll-state /opt/claude-stats/usage-poll-state.json; then
    printf 'put /tmp/ccstats-limits.json /var/www/stats/limits-remote/%s.json\n' "$LABEL" \
      | $SFTP "$DEST" || echo "WARN limits sftp failed (stats already shipped)"
  else
    echo "WARN usage-monitor poll failed (stats already shipped)"
  fi
fi
