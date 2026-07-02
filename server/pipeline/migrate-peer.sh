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

#
# migrate-peer.sh — v1.3.0 de-root migration for FRAGMENT NODES (peers).
#
# Runs ON the peer, as root. Normally invoked by provision-remote.sh's remote-side
# scripts (fresh provision, --update, --enable-live); can also be run by hand from a
# repo checkout:  sudo ./server/pipeline/migrate-peer.sh <label> <statsuser@main-domain>
#
# Moves the every-minute root cron (/etc/cron.d/ccstats-fragment) to a systemd
# timer running ship-fragment.sh as the unprivileged 'ccollector' user with
# CAP_DAC_READ_SEARCH only, sandboxed like the main box's oneshots. The sftp data
# key moves from /root/.ssh/ccstats_frag to /var/lib/ccstats/.ssh/ccstats_frag.
# An installed live monitor (claude-live-monitor.service) is re-rendered onto the
# de-rooted template (+ CAP_SYS_PTRACE), preserving its per-box ExecStart args.
#
# Idempotent and fail-safe, mirroring deploy.sh's derootify(): everything the run
# displaces is quarantined in a dated dir; the root cron is only quarantined AFTER
# one shipment has been run and verified through the new unit. On any failure the
# cron/key/units are restored and the box keeps running in root mode (exit 0 with
# a banner, so a multi-peer --update continues with the other peers).
#
# Old systemd (< 240) or no systemd: declines with a notice, root mode stays.
#
# Templates/scripts are taken from the directory layout this file sits in
# (pipeline/ + ../systemd/) — true both in a repo checkout and in the kit tarball
# provision-remote.sh ships to peers.
set -euo pipefail

LABEL="${1:-}"; DEST="${2:-}"
[ -n "$LABEL" ] && [ -n "$DEST" ] || { echo "usage: migrate-peer.sh <label> <statsuser@main-domain>" >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo "migrate-peer.sh must run as root" >&2; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"          # pipeline/ (ship-fragment.sh, refresh-scope.sh)
TPL="$SRC/../systemd"                          # unit templates
OPT=/opt/claude-stats
LOGDIR=/var/log/ccstats
SHIPLOG="$LOGDIR/fragment.log"
CHOME=/var/lib/ccstats
CKEY="$CHOME/.ssh/ccstats_frag"
RKEY=/root/.ssh/ccstats_frag
HOSTPART="${DEST#*@}"

for t in ccstats-fragment.service.template ccstats-fragment.timer.template \
         ccstats-scope-refresh.service.template ccstats-scope-refresh.path.template \
         ccstats-scope-refresh.timer.template claude-live-monitor.service.template; do
    [ -f "$TPL/$t" ] || { echo "migrate-peer.sh: missing template $TPL/$t" >&2; exit 1; }
done

notice_root_mode() {
    cat <<'BANNER'
════════════════ ccstats: peer de-root NOT completed — root mode kept ════════════════
This fragment node still ships via the previous (root cron) mode and KEEPS WORKING
exactly as before — nothing is broken. Fix the issue above and re-run the migration
(sudo ./server/pipeline/provision-remote.sh --update <label> on the MAIN server,
or migrate-peer.sh by hand on this box). It is idempotent and safe to re-run.
═══════════════════════════════════════════════════════════════════════════════════════
BANNER
}

# ── preflight: same systemd threshold as main's deploy.sh derootify() ──
if [ ! -d /run/systemd/system ]; then
    echo "peer de-root: skipped — systemd is not running on this box"; notice_root_mode; exit 0
fi
SDVER="$(systemctl --version | awk 'NR==1{print $2}')"
if ! [ "${SDVER:-0}" -ge 240 ] 2>/dev/null; then
    echo "peer de-root: skipped — systemd '$SDVER' too old or unparseable (need >= 240)"; notice_root_mode; exit 0
fi

QUAR="$OPT/backups/derootify-$(date +%Y%m%dT%H%M%S)"
install -d -m700 "$OPT/backups"
mkdir -p "$QUAR"; chmod 700 "$QUAR"

render() { # render <template> — @OPT@/@LABEL@/@DEST@
    sed -e "s|@OPT@|$OPT|g" -e "s|@LABEL@|$LABEL|g" -e "s|@DEST@|$DEST|g" "$1"
}
install_unit() { # install_unit <template-basename> <unit-name> [preserved-execstart]
    local tpl="$TPL/$1" unit="/etc/systemd/system/$2" exec_line="${3:-}"
    if [ -f "$unit" ]; then cp -a "$unit" "$QUAR/" 2>/dev/null || true; fi
    if [ -n "$exec_line" ]; then
        render "$tpl" | awk -v repl="$exec_line" '{ if ($0 ~ /^ExecStart=/) print repl; else print $0 }' > "$unit.tmp"
    else
        render "$tpl" > "$unit.tmp"
    fi
    mv "$unit.tmp" "$unit"; chmod 644 "$unit"
}

if ( set -e
    # 1) collector user (same shape as main). The sudo login user joins the
    #    ccollector group (main's "operator" pattern) for read access to logs/state.
    if ! id ccollector >/dev/null 2>&1; then
        useradd --system --user-group --home-dir "$CHOME" --create-home \
                --shell /usr/sbin/nologin ccollector
    fi
    if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER:-root}" != root ]; then
        if ! id -nG "$SUDO_USER" | grep -qw ccollector; then usermod -aG ccollector "$SUDO_USER"; fi
    fi
    install -d -m750 -o ccollector -g ccollector "$LOGDIR"

    # 2) data key -> the collector's home. COPY for now (the root cron still ships
    #    with the root key until the verified switch-over at the end); the root
    #    copy is quarantined only after verification succeeds.
    install -d -m700 -o ccollector -g ccollector "$CHOME/.ssh"
    if [ ! -f "$CKEY" ]; then
        [ -f "$RKEY" ] || { echo "peer de-root: no data key at $RKEY or $CKEY — cannot ship" >&2; exit 1; }
        install -m600 -o ccollector -g ccollector "$RKEY" "$CKEY"
        if [ -f "$RKEY.pub" ]; then install -m644 -o ccollector -g ccollector "$RKEY.pub" "$CKEY.pub"; fi
    fi
    # known_hosts: the shippers run sftp in BatchMode — seed main's host key
    # (keyscan now + whatever root already trusts for that host).
    KH="$CHOME/.ssh/known_hosts"
    { ssh-keyscan -T 5 "$HOSTPART" 2>/dev/null || true
      if [ -f /root/.ssh/known_hosts ]; then grep -F "$HOSTPART" /root/.ssh/known_hosts || true; fi
      if [ -f "$KH" ]; then cat "$KH"; fi
    } | sort -u > "$KH.tmp"
    [ -s "$KH.tmp" ] || echo "peer de-root: WARN could not seed known_hosts (keyscan failed?) — first connect will TOFU via accept-new"
    mv "$KH.tmp" "$KH"; chown ccollector:ccollector "$KH"; chmod 644 "$KH"

    # 3) current shipper + scope refresher (kit/repo copies — keeps repo == deployed)
    install -m755 "$SRC/ship-fragment.sh" "$OPT/ship-fragment.sh"
    install -m755 "$SRC/refresh-scope.sh" /usr/local/sbin/ccstats-refresh-scope
    install_unit ccstats-scope-refresh.service.template ccstats-scope-refresh.service
    install_unit ccstats-scope-refresh.path.template    ccstats-scope-refresh.path
    install_unit ccstats-scope-refresh.timer.template   ccstats-scope-refresh.timer

    # 4) the fragment shipment unit + every-minute timer (replaces the root cron)
    install_unit ccstats-fragment.service.template ccstats-fragment.service
    install_unit ccstats-fragment.timer.template   ccstats-fragment.timer

    # 5) live monitor (if enabled on this peer): re-render onto the de-rooted
    #    template, preserving the per-box ExecStart (ship args) but pointing
    #    --ship-key at the collector's key.
    LIVE_UNIT=/etc/systemd/system/claude-live-monitor.service
    if [ -f "$LIVE_UNIT" ] && [ -f "$OPT/live-monitor.py" ]; then
        live_exec="$(grep -h '^ExecStart=' "$LIVE_UNIT" | tail -1 || true)"
        if [ -n "$live_exec" ]; then
            live_exec="${live_exec//--ship-key $RKEY/--ship-key $CKEY}"
            install_unit claude-live-monitor.service.template claude-live-monitor.service "$live_exec"
        else
            echo "peer de-root: WARN $LIVE_UNIT has no ExecStart — leaving the unit untouched" >&2
        fi
    fi

    # 6) state the collectors must write moves to ccollector (missing files are fine)
    chown ccollector:ccollector "$OPT/usage-poll-state.json" "$OPT/live-status.json" 2>/dev/null || true

    # 7) logrotate: the shipment log moves to /var/log/ccstats/ (ccollector-owned dir —
    #    logrotate needs `su`; copytruncate as on main). The legacy stanza stays until
    #    the old root-cron log ages out.
    if [ -d /etc/logrotate.d ]; then
        if [ -f /etc/logrotate.d/ccstats-fragment ]; then cp -a /etc/logrotate.d/ccstats-fragment "$QUAR/logrotate.ccstats-fragment" 2>/dev/null || true; fi
        cat > /etc/logrotate.d/ccstats-fragment <<'LR'
# ccstats fragment node. /var/log/ccstats/*.log = v1.3.0 de-rooted units
# (StandardOutput=append: as 'ccollector'); /var/log/ccstats-fragment.log =
# the pre-1.3.0 root cron's log, rotated until it ages out.
/var/log/ccstats/*.log {
    su ccollector ccollector
    weekly
    rotate 8
    maxsize 50M
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}

/var/log/ccstats-fragment.log {
    weekly
    rotate 8
    maxsize 50M
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
LR
        chmod 644 /etc/logrotate.d/ccstats-fragment
    else
        echo "  WARN /etc/logrotate.d not found — install 'logrotate' or $SHIPLOG will grow unbounded"
    fi

    # 8) scope drop-ins (new users auto-pickup), then bring the units up
    /usr/local/sbin/ccstats-refresh-scope
    systemctl daemon-reload
    systemctl enable --now ccstats-scope-refresh.path ccstats-scope-refresh.timer >/dev/null 2>&1
    systemctl enable --now ccstats-fragment.timer >/dev/null 2>&1
    if [ -f "$LIVE_UNIT" ] && [ -f "$OPT/live-monitor.py" ]; then
        systemctl enable --now claude-live-monitor >/dev/null 2>&1 || true
        systemctl restart claude-live-monitor
    fi

    # 9) VERIFY before touching the root mode: one shipment through the new unit
    #    must reach main (ship-fragment.sh only prints the OK marker after a
    #    successful sftp; the oneshot fails loudly otherwise).
    if [ -f "$SHIPLOG" ]; then before=$(wc -l < "$SHIPLOG"); else before=0; fi
    systemctl start ccstats-fragment.service
    if ! tail -n "+$((before + 1))" "$SHIPLOG" | grep -q 'OK fragment shipped'; then
        echo "peer de-root: shipment verification FAILED — no success marker in $SHIPLOG" >&2
        exit 1
    fi
    if [ -f "$LIVE_UNIT" ] && [ -f "$OPT/live-monitor.py" ]; then
        sleep 2; systemctl is-active --quiet claude-live-monitor
    fi

    # 10) switch-over: quarantine the root cron (one mv from restoration) and move
    #     the root key into the quarantine dir (root-only, 700) — /root/.ssh keeps
    #     no ccstats credentials once the collector owns shipping.
    for f in /etc/cron.d/*; do
        if [ -f "$f" ] && grep -q 'ship-fragment\.sh' "$f" 2>/dev/null; then
            mv "$f" "$QUAR/cron.d.$(basename "$f")"
            echo "peer de-root: quarantined $f -> $QUAR/"
        fi
    done
    if [ -f "$RKEY" ]; then mv "$RKEY" "$QUAR/ccstats_frag"; fi
    if [ -f "$RKEY.pub" ]; then mv "$RKEY.pub" "$QUAR/ccstats_frag.pub"; fi
); then
    echo "peer de-root: OK — '$LABEL' ships as 'ccollector' (ccstats-fragment.timer, key at $CKEY)."
    if [ -n "$(ls -A "$QUAR" 2>/dev/null)" ]; then
        echo "peer de-root: previous cron/units/key archived in $QUAR"
    else
        rmdir "$QUAR" 2>/dev/null || true   # nothing displaced (already-migrated re-run)
    fi
else
    echo "peer de-root: a migration step FAILED — restoring the previous mode."
    restored_cron=0
    for f in "$QUAR"/cron.d.*; do
        if [ -f "$f" ]; then mv "$f" "/etc/cron.d/${f##*/cron.d.}" && restored_cron=1; fi
    done
    if [ -f "$QUAR/ccstats_frag" ]; then mv "$QUAR/ccstats_frag" "$RKEY"; chown root:root "$RKEY"; chmod 600 "$RKEY"; fi
    if [ -f "$QUAR/ccstats_frag.pub" ]; then mv "$QUAR/ccstats_frag.pub" "$RKEY.pub"; fi
    for f in "$QUAR"/*.service "$QUAR"/*.path "$QUAR"/*.timer; do
        if [ -f "$f" ]; then cp -a "$f" "/etc/systemd/system/${f##*/}" 2>/dev/null || true; fi
    done
    if [ -f "$QUAR/logrotate.ccstats-fragment" ]; then cp -a "$QUAR/logrotate.ccstats-fragment" /etc/logrotate.d/ccstats-fragment 2>/dev/null || true; fi
    systemctl daemon-reload 2>/dev/null || true
    # only fall back OFF the new timer if the box actually returned to cron mode —
    # on a failed RE-run of an already-migrated peer the timer IS the working mode.
    if [ "$restored_cron" = 1 ]; then
        systemctl disable --now ccstats-fragment.timer >/dev/null 2>&1 || true
    fi
    systemctl try-restart claude-live-monitor 2>/dev/null || true
    notice_root_mode
fi
