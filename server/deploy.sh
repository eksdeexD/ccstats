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

# Re-install the CODE from this repo after a `git pull` — and, since v1.2.1,
# keep the DE-ROOTED runtime current (see docs/migrate-derootify.md).
#
#   sudo ./server/deploy.sh                 # the normal update command (unchanged)
#   sudo ./server/deploy.sh --no-migrate    # update code only; skip the de-root step
#   ./server/deploy.sh                      # non-root code-only deploy — works on an
#                                           # already-migrated box where the operator
#                                           # owns the /opt/claude-stats code files
#
# Updates code ONLY for the components that are already installed. It NEVER touches your
# per-machine state — config.json, token.txt, ledger.db, or the generated JSON are left alone,
# so your settings and all-time stats survive every update.
#
# v1.2.1 de-root migration (root runs only; one-time, idempotent, fail-safe): moves the
# pipeline off root onto the unprivileged 'ccollector' user (systemd units/timers with
# CAP_DAC_READ_SEARCH; CAP_SYS_PTRACE for the live monitor). If any step fails, the old
# root crons/units are restored and the box keeps running exactly as before.
set -euo pipefail

NO_MIGRATE=0
if [ "${1:-}" = "--no-migrate" ]; then NO_MIGRATE=1; fi

REPO="$(cd "$(dirname "$0")" && pwd)"
OPT=/opt/claude-stats
WEB=/var/www/stats
LOGDIR=/var/log/ccstats
ROOT=1; [ "$(id -u)" = 0 ] || ROOT=0
SERVER="$(python3 -c 'import json;print(json.load(open("/opt/claude-stats/config.json")).get("server","main"))' 2>/dev/null || echo main)"

if [ "$ROOT" = 0 ]; then
    # Non-root deploys are only possible on a box already migrated to the de-rooted
    # runtime, with the code files handed to the operator (the migration does that
    # when the repo checkout is owned by a non-root user).
    if ! id ccollector >/dev/null 2>&1 || [ ! -w "$OPT/extract.py" ]; then
        echo "run as root:  sudo ./server/deploy.sh"
        echo "(non-root deploys need the v1.2.1 de-rooted runtime AND operator-owned $OPT code files)"
        exit 1
    fi
fi

migrated() { id ccollector >/dev/null 2>&1 && [ -f /etc/systemd/system/ccstats-extract.service ]; }

# privileged systemctl: direct as root; via scoped sudo (if granted) otherwise
sysctl_priv() {
    if [ "$ROOT" = 1 ]; then systemctl "$@"; else sudo -n systemctl "$@" 2>/dev/null; fi
}
# web-asset install: www-data-owned when root (legacy layout). Non-root: overwrite
# IN PLACE (cp truncates; install would unlink+recreate, which needs dir write the
# operator doesn't have in the ccollector-owned webroot).
webinst() { # webinst <mode> <src> <dst>
    if [ "$ROOT" = 1 ]; then install -m"$1" -o www-data -g www-data "$2" "$3"
    elif [ -f "$3" ]; then cp "$2" "$3"
    else install -m"$1" "$2" "$3"; fi
}

# 0) Timestamped restore point BEFORE we install new code or regenerate. Consistent SQLite
#    snapshot of ledger.db + bottleneck.db + config. Retention is grandfather-father-son.
#    Skips on a fresh box. On a migrated box this runs through the ccstats-backup unit so it
#    works (and stays ccollector-owned) for root and non-root deploys alike.
if [ -f "$OPT/ledger.db" ]; then
    if migrated; then
        sysctl_priv start ccstats-backup.service \
            && echo "backup: pre-deploy snapshot taken (ccstats-backup.service)" \
            || echo "backup: snapshot skipped — grant 'systemctl start ccstats-backup.service' via sudoers, or run as root"
    else
        python3 "$REPO/pipeline/extract.py" --mode backup \
            --ledger "$OPT/ledger.db" --bottleneck-db "$OPT/bottleneck.db" \
            --config "$OPT/config.json" --backups-dir "$OPT/backups" \
            && echo "backup: pre-deploy snapshot taken" || echo "backup: pre-deploy snapshot skipped (check manually)"
    fi
fi

# core (always)
if [ "$ROOT" = 1 ]; then install -d -m755 "$OPT"; fi
install -m755 "$REPO/pipeline/extract.py"   "$OPT/extract.py"
install -m644 "$REPO/pipeline/pricing.json" "$OPT/pricing.json"
echo "updated: core (extract.py, pricing.json)"

# avatar content pack (badge message banks; served like the JSON feeds). Installed wherever the
# webroot exists. NOTE: deploy.sh OVERWRITES the deployed copy — to customize the lines, edit the
# repo copy (pipeline/content-pack.json) or re-apply your own after each deploy.
if [ -d "$WEB" ] && { [ "$ROOT" = 1 ] || [ -w "$WEB/content-pack.json" ]; }; then
    webinst 644 "$REPO/pipeline/content-pack.json" "$WEB/content-pack.json"
    echo "updated: content-pack.json (avatar message banks)"
    if [ "$ROOT" = 1 ] && command -v nginx >/dev/null && ! nginx -T 2>/dev/null | grep -q '/content-pack.json'; then
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
    if [ "$ROOT" = 1 ] || [ -w "$WEB/viewscreens" ]; then
        VIEWSRC="$REPO/../viewscreens"
        if [ "$ROOT" = 1 ]; then install -d -m755 -o www-data -g www-data "$WEB/viewscreens" "$WEB/viewscreens/fonts"
        else install -d -m755 "$WEB/viewscreens" "$WEB/viewscreens/fonts"; fi
        webinst 644 "$VIEWSRC/index.html" "$WEB/viewscreens/index.html"
        webinst 644 "$VIEWSRC/pico.js"    "$WEB/viewscreens/pico.js"
        webinst 644 "$VIEWSRC/screens.js" "$WEB/viewscreens/screens.js"
        cp -a "$VIEWSRC/fonts/." "$WEB/viewscreens/fonts/"   # per-font subfolders + fonts.json (filenames may contain spaces)
        if [ "$ROOT" = 1 ]; then chown -R www-data:www-data "$WEB/viewscreens"; fi
        echo "updated: /viewscreens"
        # Needs nginx location blocks (deploy.sh never edits vhosts). Warn if the live config predates them.
        if [ "$ROOT" = 1 ] && command -v nginx >/dev/null && ! nginx -T 2>/dev/null | grep -q '/viewscreens/screens.js'; then
            echo "  ⚠ NOTE: your nginx vhost is missing the /viewscreens, /viewscreens/pico.js,"
            echo "          /viewscreens/screens.js and /viewscreens/fonts/ blocks. Until you add them"
            echo "          (see nginx/stats-site.conf.template) /viewscreens will 403/404. Add those"
            echo "          blocks before the catch-all 'location /' and reload nginx."
        fi
    else
        echo "skipped: /viewscreens (not writable — run once as root to hand it to the operator)"
    fi
fi

# live-activity monitor — only if already deployed
if [ -f "$OPT/live-monitor.py" ]; then
    install -m755 "$REPO/monitor/live-monitor.py" "$OPT/live-monitor.py"
    if [ -d "$WEB/livetest" ] && { [ "$ROOT" = 1 ] || [ -w "$WEB/livetest" ]; }; then
        webinst 644 "$REPO/monitor/livetest-index.html" "$WEB/livetest/index.html"
    fi
    sysctl_priv try-restart claude-live-monitor 2>/dev/null && echo "updated: live monitor (restarted if running)" \
        || echo "updated: live monitor (restart it: systemctl restart claude-live-monitor)"
fi

# session/weekly limits poller (CLAUDE MONITOR) — only if already deployed
if [ -f "$OPT/usage-monitor.py" ]; then
    install -m755 "$REPO/monitor/usage-monitor.py" "$OPT/usage-monitor.py"
    # cross-server limits: ensure the merge drop-zone exists so the poller's --merge-dir has somewhere
    # to read remotes' shipped readings. statsuser owns it if present; otherwise root:www-data until
    # the first remote is provisioned (provision-remote.sh re-chowns it to statsuser).
    if [ "$ROOT" = 1 ] && [ -d "$WEB" ]; then
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
    sysctl_priv try-restart claude-bottleneck-monitor 2>/dev/null && echo "updated: bottleneck monitor (restarted if running)" \
        || echo "updated: bottleneck monitor (restart it: systemctl restart claude-bottleneck-monitor)"
fi

# log rotation — covers the legacy /var/log/claude-stats*.log AND the v1.2.1 /var/log/ccstats/*.log.
# logrotate is a separate package (part of the Debian/Ubuntu base) and runs itself via
# logrotate.timer / cron.daily, so this policy needs no cron of our own. Always install (idempotent).
if [ "$ROOT" = 1 ]; then
    if [ -d /etc/logrotate.d ]; then
        install -m644 "$REPO/logrotate/ccstats.conf" /etc/logrotate.d/ccstats
        echo "updated: logrotate policy (/etc/logrotate.d/ccstats)"
    else
        echo "  ⚠ NOTE: /etc/logrotate.d not found — install the 'logrotate' package, else"
        echo "          the pipeline logs will grow without bound."
    fi
fi

# ───────────────────────────── v1.2.1 de-root migration ─────────────────────────────
# Root runs only. One-time on legacy boxes; on already-migrated boxes it just refreshes
# the unit files from the templates. Fail-safe: any error restores the previous root
# crons/units and prints how to migrate with Claude Code's help instead.

render() { # render <template> — substitute @OPT@/@WEB@/@SERVER@
    sed -e "s|@OPT@|$OPT|g" -e "s|@WEB@|$WEB|g" -e "s|@SERVER@|$SERVER|g" "$1"
}

install_unit() { # install_unit <template-basename> <unit-name> [preserved-execstart]
    local tpl="$REPO/systemd/$1" unit="/etc/systemd/system/$2" exec_line="${3:-}"
    [ -f "$unit" ] && cp -a "$unit" "$QUAR/" 2>/dev/null || true
    if [ -n "$exec_line" ]; then
        render "$tpl" | awk -v repl="$exec_line" '{ if ($0 ~ /^ExecStart=/) print repl; else print $0 }' > "$unit.tmp"
    else
        render "$tpl" > "$unit.tmp"
    fi
    mv "$unit.tmp" "$unit"; chmod 644 "$unit"
}

print_fallback_banner() {
    cat <<'BANNER'
════════════════════ ccstats: de-root migration NOT completed ════════════════════
Your install still runs in the previous (root) mode and KEEPS WORKING as before —
nothing is broken, and any cron entries that were disabled have been restored.

To migrate with assistance, open Claude Code in this repo and say:

    Read docs/migrate-derootify.md and migrate this ccstats install.

Claude will explain the change, check this box's specifics, ask for your OK, and
do the migration step by step. Or just re-run  sudo ./server/deploy.sh  later
(use --no-migrate to keep skipping this step on purpose).
═══════════════════════════════════════════════════════════════════════════════════
BANNER
}

derootify() {
    # ── preflight: skip (quietly, safely) where migration doesn't apply ──
    if [ ! -d /run/systemd/system ]; then
        echo "de-root: skipped — systemd is not running on this box"; print_fallback_banner; return 0
    fi
    local sdver; sdver="$(systemctl --version | awk 'NR==1{print $2}')"
    if ! [ "${sdver:-0}" -ge 240 ] 2>/dev/null; then
        echo "de-root: skipped — systemd '$sdver' too old or unparseable (need >= 240)"; print_fallback_banner; return 0
    fi
    if grep -rqs 'ship-fragment\.sh' /etc/cron.d/ 2>/dev/null; then
        echo "de-root: skipped — this is a fragment node (peer). Peers stay root-mode in this"
        echo "         release and are managed from the MAIN server via provision-remote.sh."
        return 0
    fi

    QUAR="$OPT/backups/derootify-$(date +%Y%m%dT%H%M%S)"
    mkdir -p "$QUAR"

    # operator = owner of the repo checkout (gets code ownership + state read access,
    # enabling future sudo-less deploys). root stays owner on root-owned checkouts.
    local OPERATOR; OPERATOR="$(stat -c %U "$REPO")"

    if ( set -e
        # 1) collector user + operator group membership
        id ccollector >/dev/null 2>&1 || useradd --system --user-group \
            --home-dir /var/lib/ccstats --create-home --shell /usr/sbin/nologin ccollector
        if [ "$OPERATOR" != root ] && ! id -nG "$OPERATOR" | grep -qw ccollector; then
            usermod -aG ccollector "$OPERATOR"
        fi

        # 2) quarantine the legacy root crons FIRST (restored automatically on failure)
        crontab -l > "$QUAR/root-crontab.orig" 2>/dev/null || true
        if [ -s "$QUAR/root-crontab.orig" ] && grep -q 'claude-stats' "$QUAR/root-crontab.orig"; then
            grep 'claude-stats' "$QUAR/root-crontab.orig" > "$QUAR/root-crontab.removed"
            grep -v 'claude-stats' "$QUAR/root-crontab.orig" | crontab -
            echo "de-root: moved $(wc -l < "$QUAR/root-crontab.removed") root crontab line(s) to $QUAR/"
        fi
        for f in /etc/cron.d/*; do
            { [ -f "$f" ] && grep -q 'claude-stats' "$f" 2>/dev/null; } || continue
            mv "$f" "$QUAR/cron.d.$(basename "$f")"
            echo "de-root: quarantined $f -> $QUAR/"
        done

        # 3) stop the daemons while we re-own state and swap units
        systemctl stop claude-live-monitor claude-bottleneck-monitor 2>/dev/null || true

        # 4) log dir + scope refresher (auto-discovers new users; see refresh-scope.sh)
        install -d -m750 -o ccollector -g ccollector "$LOGDIR"
        install -m755 "$REPO/pipeline/refresh-scope.sh" /usr/local/sbin/ccstats-refresh-scope
        install_unit ccstats-scope-refresh.service.template ccstats-scope-refresh.service
        install_unit ccstats-scope-refresh.path.template    ccstats-scope-refresh.path
        install_unit ccstats-scope-refresh.timer.template   ccstats-scope-refresh.timer

        # 5) component units — gated on what is installed; the live monitor's ExecStart
        #    (per-box args like --merge-dir, set up by provision-remote.sh) is preserved.
        install_unit ccstats-extract.service.template ccstats-extract.service
        install_unit ccstats-extract.timer.template   ccstats-extract.timer
        install_unit ccstats-backup.service.template  ccstats-backup.service
        if [ -f "$OPT/usage-monitor.py" ]; then
            install_unit ccstats-usage.service.template ccstats-usage.service
            install_unit ccstats-usage.timer.template   ccstats-usage.timer
        fi
        if [ -f "$WEB/competitor.json" ] || [ -f "$WEB/competition.json" ]; then
            install_unit ccstats-competitor.service.template ccstats-competitor.service
            install_unit ccstats-competitor.timer.template   ccstats-competitor.timer
        fi
        if [ -f "$OPT/live-monitor.py" ]; then
            live_exec=""
            if [ -f "$QUAR/claude-live-monitor.service" ]; then
                live_exec="$(grep -h '^ExecStart=' "$QUAR/claude-live-monitor.service" | tail -1 || true)"
            elif [ -f /etc/systemd/system/claude-live-monitor.service ]; then
                live_exec="$(grep -h '^ExecStart=' /etc/systemd/system/claude-live-monitor.service | tail -1 || true)"
            fi
            install_unit claude-live-monitor.service.template claude-live-monitor.service "$live_exec"
        fi
        if [ -f "$OPT/bottleneck-monitor.py" ]; then
            install_unit claude-bottleneck-monitor.service.template claude-bottleneck-monitor.service
        fi

        # 6) ownership: state -> ccollector; code + secrets -> operator; web feeds -> ccollector
        chown ccollector:ccollector "$OPT"/ledger.db "$OPT"/ledger.db.bak "$OPT"/bottleneck.db \
            "$OPT"/milestones.json "$OPT"/celebrations.json "$OPT"/limit-hits.json \
            "$OPT"/usage-poll-state.json 2>/dev/null || true
        chmod g+r "$OPT"/ledger.db "$OPT"/ledger.db.bak "$OPT"/bottleneck.db 2>/dev/null || true
        chown -R ccollector:ccollector "$OPT/backups" "$OPT/__pycache__" 2>/dev/null || true
        chmod 750 "$OPT/backups" 2>/dev/null || true
        chown "$OPERATOR" "$OPT"/config.json "$OPT"/token.txt "$OPT"/peer-token.txt 2>/dev/null || true
        chown -R "$OPERATOR" "$OPT"/remotes.d "$OPT"/remote-keys 2>/dev/null || true
        if [ "$OPERATOR" != root ]; then
            chown "$OPERATOR" "$OPT"/*.py "$OPT"/pricing.json 2>/dev/null || true
            chown -R "$OPERATOR":www-data "$WEB/viewscreens" "$WEB/livetest" "$WEB/content-pack.json" 2>/dev/null || true
        fi
        chown "$OPERATOR":ccollector "$OPT"; chmod 2775 "$OPT"
        chown ccollector:www-data "$WEB" 2>/dev/null || true
        chown ccollector "$WEB"/claude-stats.json "$WEB"/claude-limits.json "$WEB"/competitor.json \
            "$WEB"/competition.json "$WEB"/live-status.json 2>/dev/null || true
        chown -R ccollector:ccollector "$WEB/peers" 2>/dev/null || true

        # 7) scope drop-ins, then bring everything up
        /usr/local/sbin/ccstats-refresh-scope
        systemctl daemon-reload
        systemctl enable --now ccstats-scope-refresh.path ccstats-scope-refresh.timer >/dev/null 2>&1
        systemctl enable --now ccstats-extract.timer >/dev/null 2>&1
        if [ -f /etc/systemd/system/ccstats-usage.timer ]; then systemctl enable --now ccstats-usage.timer >/dev/null 2>&1; fi
        if [ -f /etc/systemd/system/ccstats-competitor.timer ]; then systemctl enable --now ccstats-competitor.timer >/dev/null 2>&1; fi
        if [ -f /etc/systemd/system/claude-live-monitor.service ]; then systemctl enable --now claude-live-monitor >/dev/null 2>&1; fi
        if [ -f /etc/systemd/system/claude-bottleneck-monitor.service ]; then systemctl enable --now claude-bottleneck-monitor >/dev/null 2>&1; fi

        # 8) verify: one full extract as ccollector must produce a fresh feed; daemons must run
        systemctl start ccstats-extract.service
        [ -n "$(find "$WEB/claude-stats.json" -newermt '-120 seconds' 2>/dev/null)" ]
        if [ -f /etc/systemd/system/claude-live-monitor.service ]; then
            sleep 2; systemctl is-active --quiet claude-live-monitor
        fi
        if [ -f /etc/systemd/system/claude-bottleneck-monitor.service ]; then
            systemctl is-active --quiet claude-bottleneck-monitor
        fi
    ); then
        echo "de-root: OK — pipeline runs as 'ccollector' (units + timers); operator = $OPERATOR."
        if [ -n "$(ls -A "$QUAR" 2>/dev/null)" ]; then
            echo "de-root: previous crons/units archived in $QUAR"
        else
            rmdir "$QUAR" 2>/dev/null || true   # nothing was archived (already-migrated re-run)
        fi
    else
        echo "de-root: a migration step FAILED — rolling back to the previous root mode."
        [ -s "$QUAR/root-crontab.orig" ] && crontab "$QUAR/root-crontab.orig" || true
        for f in "$QUAR"/cron.d.*; do
            [ -f "$f" ] && mv "$f" "/etc/cron.d/${f##*/cron.d.}" 2>/dev/null || true
        done
        for f in "$QUAR"/*.service; do
            [ -f "$f" ] && cp -a "$f" "/etc/systemd/system/${f##*/}" 2>/dev/null || true
        done
        systemctl daemon-reload 2>/dev/null || true
        systemctl disable --now ccstats-extract.timer ccstats-usage.timer ccstats-competitor.timer \
            ccstats-scope-refresh.path ccstats-scope-refresh.timer >/dev/null 2>&1 || true
        systemctl try-restart claude-live-monitor claude-bottleneck-monitor 2>/dev/null || true
        print_fallback_banner
    fi
}

if [ "$ROOT" = 1 ] && [ "$NO_MIGRATE" = 0 ]; then
    derootify
elif [ "$ROOT" = 1 ]; then
    echo "de-root: skipped (--no-migrate)"
fi

# pick up the latest stats immediately
if migrated; then
    sysctl_priv start ccstats-extract.service && echo "regenerated claude-stats.json (ccstats-extract)" \
        || echo "stats regen skipped — grant 'systemctl start ccstats-extract.service' via sudoers, or run as root"
    if [ -f /etc/systemd/system/ccstats-competitor.service ]; then
        sysctl_priv start ccstats-competitor.service && echo "regenerated competition feed (ccstats-competitor)" || true
    fi
elif [ "$ROOT" = 1 ]; then
    # legacy root mode (migration skipped or rolled back): regenerate exactly as before
    /usr/bin/python3 "$OPT/extract.py" --mode full --server "$SERVER" \
        --fragments-dir "$WEB/fragments" --output "$WEB/claude-stats.json" >/dev/null 2>&1 \
        && chown www-data:www-data "$WEB/claude-stats.json" && echo "regenerated claude-stats.json" || echo "stats regen skipped (check manually)"
    if [ -f "$WEB/competitor.json" ] || [ -f "$WEB/competition.json" ]; then
        /usr/bin/python3 "$OPT/extract.py" --mode competitor --server "$SERVER" --ledger "$OPT/ledger.db" \
            --config "$OPT/config.json" --limits-file "$WEB/claude-limits.json" --bottleneck-db "$OPT/bottleneck.db" \
            --peers-dir "$WEB/peers" --output "$WEB/competitor.json" --competition-output "$WEB/competition.json" \
            >/dev/null 2>&1 && chown www-data:www-data "$WEB/competitor.json" "$WEB/competition.json" 2>/dev/null \
            && echo "regenerated competition feed" || echo "competition regen skipped"
    fi
fi

if [ "$ROOT" = 1 ] && command -v nginx >/dev/null && nginx -t >/dev/null 2>&1; then
    systemctl reload nginx && echo "nginx reloaded"
fi
echo "deploy done — code updated; config.json / token.txt / ledger.db untouched."
