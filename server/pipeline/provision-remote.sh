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
# provision-remote.sh — add / update REMOTE Claude Code servers as "fragment nodes".
#
# Run on the MAIN (aggregator) server.
#   sudo ./pipeline/provision-remote.sh                      # add a new remote (interactive)
#   sudo ./pipeline/provision-remote.sh --list                # list provisioned remotes
#   sudo ./pipeline/provision-remote.sh --update <label>|all   # re-push code to remote(s)
#   sudo ./pipeline/provision-remote.sh --enable-live <label>  # turn on the ~2s live status channel
#
# A fragment node emits only its own per-session usage every minute (`extract.py --mode fragment`)
# and uploads it to this server's /var/www/stats/fragments/. The next `--mode full` run here ingests
# it; the remote then appears in the JSON's meta.servers and all totals. The remote gets NO
# /view, monitor, nginx, token, or ledger — pure data source.
#
# ── Two SSH directions (the whole model) ─────────────────────────────────────────────────────────
#   1. PROVISIONING  (main -> remote, at setup/update): the script logs into the remote AS YOUR OWN
#      sudo user (e.g. you@host). You paste ONE line on the remote that just adds this script's key to
#      *your* ~/.ssh/authorized_keys (no sudo in the paste). Root steps run via `sudo` over an
#      interactive session — you type the remote sudo password ONCE per run. No passwordless sudo is
#      ever configured.
#   2. DATA UPLOAD   (remote -> main, every minute): a SECOND key is generated on the remote; its
#      public half is wired into a locked-down `statsuser` here automatically (sftp-only). The remote
#      cron uploads via sftp. Private keys never move.
#
# Re-runnable & idempotent. Stdlib/coreutils + openssh only.
set -euo pipefail

# ── pretty output ────────────────────────────────────────────────────────────────────────────────
b()    { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
info() { printf '  \033[36m·\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root on the MAIN server:  sudo ./pipeline/provision-remote.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/pipeline/extract.py" ] || die "can't find pipeline/extract.py next to this script ($REPO)"

WEB=/var/www/stats
FRAG="$WEB/fragments"
OPT=/opt/claude-stats
KEYDIR="$OPT/remote-keys"           # provisioning private keys (root, 700) — never committed
REG="$OPT/remotes.d"                # one .conf per provisioned remote (root, 700)
STATSUSER=statsuser                 # locked-down sftp-only account remotes upload into

ensure_main_side() {  # idempotent main-server prerequisites
  if ! id "$STATSUSER" >/dev/null 2>&1; then
    useradd -m -s /usr/sbin/nologin "$STATSUSER"; ok "created locked-down user '$STATSUSER' (nologin, no password)"
  fi
  install -d -m755 -o root -g www-data "$WEB"
  install -d -m2775 -o "$STATSUSER" -g www-data "$FRAG"
  # drop-zone for remotes' shipped session/weekly limit readings (MAIN merges it with --merge-dir).
  # Same statsuser-writable perms as $FRAG, so the existing sftp-only key can write here too.
  install -d -m2775 -o "$STATSUSER" -g www-data "$WEB/limits-remote"
  install -d -m700 -o "$STATSUSER" -g "$STATSUSER" "/home/$STATSUSER/.ssh"
  touch "/home/$STATSUSER/.ssh/authorized_keys"
  chown "$STATSUSER:$STATSUSER" "/home/$STATSUSER/.ssh/authorized_keys"; chmod 600 "/home/$STATSUSER/.ssh/authorized_keys"
  install -d -m700 "$KEYDIR" "$REG"
}

# ── --list ─────────────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = --list ]; then
  [ -d "$REG" ] || { echo "no remotes provisioned yet"; exit 0; }
  shopt -s nullglob
  found=0
  for f in "$REG"/*.conf; do
    found=1; ( . "$f"; printf '  %-14s %s@%s  -> %s  (live=%s)\n' "$label" "$user" "$host" "$main_domain" "${live:-0}" )
  done
  [ "$found" = 1 ] || echo "no remotes provisioned yet"
  exit 0
fi

# ── --update <label>|all ─────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = --update ]; then
  TARGET="${2:-}"; [ -n "$TARGET" ] || die "usage: --update <label>|all"
  ensure_main_side
  shopt -s nullglob
  confs=()
  if [ "$TARGET" = all ]; then confs=("$REG"/*.conf); else confs=("$REG/$TARGET.conf"); fi
  [ "${#confs[@]}" -gt 0 ] && [ -e "${confs[0]}" ] || die "no matching remote registry entry (try --list)"
  for f in "${confs[@]}"; do
    ( set -e
      . "$f"
      b "Updating '$label' ($user@$host) — you'll be asked for its sudo password once"
      PROV_KEY="$KEYDIR/${label}_provision"
      [ -f "$PROV_KEY" ] || die "missing provisioning key $PROV_KEY (re-add this remote)"
      SSHK="ssh -i $PROV_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
      SCPK="scp -i $PROV_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
      $SCPK "$REPO/pipeline/extract.py" "$user@$host:/tmp/ccstats-extract.py" >/dev/null
      $SCPK "$REPO/pipeline/pricing.json" "$user@$host:/tmp/ccstats-pricing.json" >/dev/null
      $SCPK "$REPO/monitor/usage-monitor.py" "$user@$host:/tmp/ccstats-usagemon.py" >/dev/null
      $SCPK "$REPO/pipeline/ship-fragment.sh" "$user@$host:/tmp/ccstats-shipfrag.sh" >/dev/null
      [ "${live:-0}" = 1 ] && $SCPK "$REPO/monitor/live-monitor.py" "$user@$host:/tmp/ccstats-livemon.py" >/dev/null
      UPD_LOCAL="$(mktemp)"
      cat > "$UPD_LOCAL" <<'UPD'
set -eu
sudo -v
sudo install -m755 /tmp/ccstats-extract.py   /opt/claude-stats/extract.py
sudo install -m644 /tmp/ccstats-pricing.json /opt/claude-stats/pricing.json
sudo install -m644 /tmp/ccstats-extract.py   /home/ccstats/extract.py 2>/dev/null || true
sudo install -m644 /tmp/ccstats-pricing.json /home/ccstats/pricing.json 2>/dev/null || true
# limits poller + the shipper that pushes its reading up (closes the cross-server limits gap on
# remotes provisioned before this existed; keeps repo == deployed so it can't silently drift again)
sudo install -m755 /tmp/ccstats-usagemon.py  /opt/claude-stats/usage-monitor.py
sudo install -m644 /tmp/ccstats-usagemon.py  /home/ccstats/usage-monitor.py 2>/dev/null || true
sudo install -m755 /tmp/ccstats-shipfrag.sh  /opt/claude-stats/ship-fragment.sh
rm -f /tmp/ccstats-extract.py /tmp/ccstats-pricing.json /tmp/ccstats-usagemon.py /tmp/ccstats-shipfrag.sh
if [ "${LIVE:-0}" = 1 ] && [ -f /tmp/ccstats-livemon.py ]; then
  sudo install -m755 /tmp/ccstats-livemon.py /opt/claude-stats/live-monitor.py
  sudo install -m644 /tmp/ccstats-livemon.py /home/ccstats/live-monitor.py 2>/dev/null || true
  rm -f /tmp/ccstats-livemon.py
  sudo systemctl restart claude-live-monitor 2>/dev/null || true
fi
echo CCSTATS_UPDATE_DONE
UPD
      # scp + `bash <file>` (NOT heredoc on stdin) so `ssh -t` keeps a real terminal for sudo
      $SCPK "$UPD_LOCAL" "$user@$host:/tmp/ccstats-update.sh" >/dev/null
      rm -f "$UPD_LOCAL"
      $SSHK -t "$user@$host" "LIVE='${live:-0}' bash /tmp/ccstats-update.sh"
      $SSHK "$user@$host" 'rm -f /tmp/ccstats-update.sh' 2>/dev/null || true
      ok "updated '$label'"
    ) || warn "update failed for $(basename "$f" .conf) — see above"
  done
  b "Done. Updated code on the selected remote(s)."
  exit 0
fi

# ── --enable-live <label> — turn on the ~2 s working/idle/waiting status channel for a remote ─────
# Sets up BOTH sides: the remote runs live-monitor.py and ships its status up over a multiplexed,
# activity-gated SSH connection (reusing the existing sftp data key); main runs its monitor with
# --merge-dir so the remote's users appear in the aggregate live-status.json + /livetest.
if [ "${1:-}" = --enable-live ]; then
  EL="${2:-}"; [ -n "$EL" ] || die "usage: --enable-live <label>"
  [ -f "$REPO/monitor/live-monitor.py" ] || die "repo monitor/live-monitor.py not found"
  ensure_main_side
  CONF="$REG/$EL.conf"; [ -f "$CONF" ] || die "no such remote '$EL' (try --list)"
  . "$CONF"
  PROV_KEY="$KEYDIR/${label}_provision"; [ -f "$PROV_KEY" ] || die "missing provisioning key for '$label'"
  SSHK="ssh -i $PROV_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
  SCPK="scp -i $PROV_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

  # ---- main side: drop-zone for shipped status + main monitor merges it ----
  b "1. Main side (drop-zone + merge)"
  install -d -m2775 -o "$STATSUSER" -g www-data "$WEB/live-remote"; ok "$WEB/live-remote (statsuser-writable)"
  install -m755 "$REPO/monitor/live-monitor.py" "$OPT/live-monitor.py"
  if [ -d "$WEB/livetest" ]; then   # keep the /livetest page in sync with the new server:user schema
    install -m644 -o www-data -g www-data "$REPO/monitor/livetest-index.html" "$WEB/livetest/index.html"
    ok "refreshed /livetest page (server-aware)"
  fi
  [ -f /etc/systemd/system/claude-live-monitor.service ] && \
    cp -f /etc/systemd/system/claude-live-monitor.service /etc/systemd/system/claude-live-monitor.service.bak-live 2>/dev/null || true
  cat > /etc/systemd/system/claude-live-monitor.service <<UNIT
[Unit]
Description=Claude Code live activity monitor (main; merges remote servers)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $OPT/live-monitor.py --server main --merge-dir $WEB/live-remote --verbose
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now claude-live-monitor >/dev/null 2>&1 || true
  systemctl restart claude-live-monitor
  ok "main monitor now merges $WEB/live-remote (backup: …/claude-live-monitor.service.bak-live)"

  # ---- remote side: live-monitor + shipper unit (reuses the sftp data key) ----
  b "2. Remote side ($user@$host) — one sudo password"
  $SCPK "$REPO/monitor/live-monitor.py" "$user@$host:/tmp/ccstats-livemon.py" >/dev/null
  EL_LOCAL="$(mktemp)"
  cat > "$EL_LOCAL" <<'ELR'
set -eu
sudo -v
sudo install -m755 /tmp/ccstats-livemon.py /opt/claude-stats/live-monitor.py
sudo install -m644 -o ccstats -g ccstats /tmp/ccstats-livemon.py /home/ccstats/live-monitor.py 2>/dev/null || true
rm -f /tmp/ccstats-livemon.py
sudo tee /etc/systemd/system/claude-live-monitor.service >/dev/null <<UNIT
[Unit]
Description=Claude Code live activity monitor + shipper ($LABEL → main)
After=network.target

[Service]
Type=simple
RuntimeDirectory=ccstats
ExecStart=/usr/bin/python3 /opt/claude-stats/live-monitor.py --server $LABEL --output /opt/claude-stats/live-status.json --no-chown --ship-dest $STATSUSER@$MAIN_DOMAIN --ship-key /root/.ssh/ccstats_frag --ship-remote-path /var/www/stats/live-remote --ship-grace 1800 --ship-control /run/ccstats/cm-live --verbose
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now claude-live-monitor
echo CCSTATS_LIVE_DONE
ELR
  $SCPK "$EL_LOCAL" "$user@$host:/tmp/ccstats-enable-live.sh" >/dev/null
  rm -f "$EL_LOCAL"
  $SSHK -t "$user@$host" "LABEL='$label' STATSUSER='$STATSUSER' MAIN_DOMAIN='$main_domain' bash /tmp/ccstats-enable-live.sh"
  $SSHK "$user@$host" 'rm -f /tmp/ccstats-enable-live.sh' 2>/dev/null || true
  ok "remote live monitor + shipper started"

  # mark live=1 in the registry
  if grep -q '^live=' "$CONF"; then
    sed -i 's/^live=.*/live=1/' "$CONF"
  else
    echo "live=1" >> "$CONF"
  fi
  echo
  b "✓ Live channel enabled for '$label'."
  info "Status ships up only while a session is active (tunnel drops ~30 min after the last one)."
  info "Watch: the /livetest page should show '$label' within a few seconds of activity there."
  info "Remote monitor log: ssh $user@$host 'sudo journalctl -u claude-live-monitor -f'"
  info "⚠ Verify the process matcher on the remote (how 'claude' appears in /proc) if it never shows working."
  exit 0
fi

[ -z "${1:-}" ] || die "unknown option '$1' (no args = add; or --list / --update <l>|all / --enable-live <l>)"

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# ADD A NEW REMOTE
# ─────────────────────────────────────────────────────────────────────────────────────────────────
b "Add a remote Claude Code server as a fragment node"
echo
read -rp "Your SSH login on the remote as user@host, e.g. you@server2.example.net : " TARGET
[ -n "${TARGET:-}" ] || die "user@host is required"
[[ "$TARGET" == *@* ]] || die "expected user@host (e.g. you@server2.example.net)"
RUSER="${TARGET%@*}"; RHOST="${TARGET#*@}"
read -rp "Short unique label for this server (a-z0-9-), e.g. server2        : " LABEL
[[ "$LABEL" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "label must be lower-case letters/digits/hyphens"
[ "$LABEL" != main ] || die "'main' is reserved for this server — pick another label"

DEF_TZ=UTC
[ -f "$OPT/config.json" ] && DEF_TZ="$(python3 -c 'import json;print(json.load(open("'"$OPT"'/config.json")).get("timezone","UTC"))' 2>/dev/null || echo UTC)"
read -rp "Timezone for the remote [$DEF_TZ] (match main so histograms align)  : " TZ_IN
TZ_NAME="${TZ_IN:-$DEF_TZ}"

# This MAIN server's stable DOMAIN (NOT its IP — the IP can change). The remote uploads here over ssh.
DEF_DOMAIN=""
shopt -s nullglob; for f in "$REG"/*.conf; do DEF_DOMAIN="$(. "$f"; echo "${main_domain:-}")"; [ -n "$DEF_DOMAIN" ] && break; done
DPROMPT="(e.g. stats.example.net)"; [ -n "$DEF_DOMAIN" ] && DPROMPT="[$DEF_DOMAIN]"
read -rp "This MAIN server's DOMAIN the remote uploads to $DPROMPT : " DOMAIN_IN
MAIN_DOMAIN="${DOMAIN_IN:-$DEF_DOMAIN}"
[ -n "${MAIN_DOMAIN:-}" ] || die "main domain is required (must resolve to this server and be SSH-reachable on :22)"

echo
b "Plan"
info "login (provision): $RUSER@$RHOST   (sudo password asked ONCE; no passwordless sudo configured)"
info "label / tz        : $LABEL / $TZ_NAME"
info "data flow         : $RHOST  --every-min sftp-->  $MAIN_DOMAIN:{fragments,limits-remote}/$LABEL.json"
info "remote gets       : /opt/claude-stats/{extract.py,pricing.json,usage-monitor.py,config.json,ship-fragment.sh} + root cron + logrotate; source copies in /home/ccstats"
echo
read -rp "Proceed? [y/N] " yn; [[ "${yn:-}" =~ ^[Yy]$ ]] || die "aborted"

ensure_main_side

# ── provisioning keypair (generated HERE; you paste its PUBLIC key into YOUR ~/.ssh on the remote) ─
b "1. Provisioning key (main → remote, as $RUSER)"
PROV_KEY="$KEYDIR/${LABEL}_provision"
[ -f "$PROV_KEY" ] || ssh-keygen -t ed25519 -N '' -C "ccstats-provision@main" -f "$PROV_KEY" >/dev/null
ok "key: $PROV_KEY"
PROV_PUB="$(cat "$PROV_KEY.pub")"

# bootstrap line: pure authorized_keys append into the user's OWN home — no sudo, no new user, no sudoers
BOOTSTRAP="mkdir -p ~/.ssh && chmod 700 ~/.ssh && printf '%s\n' '$PROV_PUB' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo BOOTSTRAP_OK"
echo
b "2. ►► COPY-PASTE THIS on the remote (log in as $RUSER@$RHOST however you normally do):"
echo
echo "--------------------------------------------------------------------------------"
echo "$BOOTSTRAP"
echo "--------------------------------------------------------------------------------"
echo
info "It only adds this script's key to YOUR ~/.ssh/authorized_keys — no sudo, no new user yet."
info "You should see 'BOOTSTRAP_OK'. (The script creates the ccstats/statsuser accounts itself, under sudo.)"
echo
read -rp "Done? Press Enter to continue (Ctrl-C to abort) "

SSHK="ssh -i $PROV_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
SCPK="scp -i $PROV_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

b "3. Connecting to $RUSER@$RHOST"
$SSHK "$TARGET" 'echo ok' >/dev/null 2>&1 || die "can't connect — was the bootstrap line pasted (BOOTSTRAP_OK)?"
ok "connected"

# ── copy code + generate the DATA key (as $RUSER, no sudo) so we can authorize it on main first ────
b "4. Staging code + generating the data key on the remote"
$SCPK "$REPO/pipeline/extract.py"      "$TARGET:/tmp/ccstats-extract.py"   >/dev/null
$SCPK "$REPO/pipeline/pricing.json"    "$TARGET:/tmp/ccstats-pricing.json" >/dev/null
$SCPK "$REPO/monitor/usage-monitor.py" "$TARGET:/tmp/ccstats-usagemon.py"  >/dev/null
$SCPK "$REPO/pipeline/ship-fragment.sh" "$TARGET:/tmp/ccstats-shipfrag.sh" >/dev/null
DATA_PUB="$($SSHK "$TARGET" "test -f ~/.ccstats_frag || ssh-keygen -t ed25519 -N '' -C 'ccstats-fragment@$LABEL' -f ~/.ccstats_frag >/dev/null; cat ~/.ccstats_frag.pub")"
[ -n "$DATA_PUB" ] || die "failed to generate/read the remote data key"
ok "data key ready (private stays on the remote)"

# ── authorize the data key on main: sftp-only, no shell, no forwarding ─────────────────────────────
b "5. Authorizing upload into '$STATSUSER' (sftp-only, jailed by perms)"
AUTH="/home/$STATSUSER/.ssh/authorized_keys"
# Keep exactly ONE key per label: drop any prior entry for this label, then add the current one.
# (Idempotent across re-runs — a regenerated key replaces the old line instead of stacking up.)
# restrict = no pty/forwarding/agent/X11; command="internal-sftp" = sftp subsystem only, never a shell.
KEYBODY="$(printf '%s' "$DATA_PUB" | awk '{print $1, $2}')"   # type + base64 only (drop keygen comment)
TMPK="$(mktemp)"
grep -v "ccstats-fragment@${LABEL}\$" "$AUTH" 2>/dev/null > "$TMPK" || true
printf 'restrict,command="internal-sftp" %s ccstats-fragment@%s\n' "$KEYBODY" "$LABEL" >> "$TMPK"
install -m600 -o "$STATSUSER" -g "$STATSUSER" "$TMPK" "$AUTH"; rm -f "$TMPK"
ok "authorized one sftp-only key for '$LABEL' (can only write the fragments + limits-remote dirs)"

# ── one interactive sudo session: install everything, move data key to root, cron, smoke test ──────
# NB: the setup script is scp'd to the remote and run via `ssh -t … bash <file>`, NOT piped on stdin.
# With a heredoc on stdin, `ssh -t` can't allocate a terminal ("stdin is not a terminal") and sudo
# then has nowhere to read the password. Sending it as a file keeps stdin = the local terminal.
b "6. Configuring the remote (one sudo password)"
SETUP_LOCAL="$(mktemp)"
cat > "$SETUP_LOCAL" <<'REMOTE'
set -eu
sudo -v
sudo install -d -m755 /opt/claude-stats
sudo install -m755 /tmp/ccstats-extract.py    /opt/claude-stats/extract.py
sudo install -m644 /tmp/ccstats-pricing.json  /opt/claude-stats/pricing.json
sudo install -m755 /tmp/ccstats-usagemon.py   /opt/claude-stats/usage-monitor.py   # limits poller (ships up)
# mirror source copies under /home/ccstats (like the main box: edit here / deploy to /opt)
sudo useradd -m -s /usr/sbin/nologin ccstats 2>/dev/null || true
sudo install -d -m755 -o ccstats -g ccstats /home/ccstats
sudo install -m644 -o ccstats -g ccstats /tmp/ccstats-extract.py   /home/ccstats/extract.py
sudo install -m644 -o ccstats -g ccstats /tmp/ccstats-pricing.json /home/ccstats/pricing.json
sudo install -m644 -o ccstats -g ccstats /tmp/ccstats-usagemon.py  /home/ccstats/usage-monitor.py
# per-machine config (timezone drives the fragment's hour/weekday histograms)
printf '{\n  "timezone": "%s",\n  "server": "%s"\n}\n' "$TZ_NAME" "$LABEL" | sudo tee /opt/claude-stats/config.json >/dev/null
sudo chmod 600 /opt/claude-stats/config.json
# place the data key as /root/.ssh/ccstats_frag (cron runs as root: it needs /proc + all users'
# 0600 transcripts). Copy with an EXPLICIT target name — `mv`-ing the dotfile into a directory keeps
# the leading dot (/root/.ssh/.ccstats_frag), which is what broke earlier runs. Idempotent.
sudo install -d -m700 /root/.ssh
sudo install -m600 -o root -g root "$HOME/.ccstats_frag"     /root/.ssh/ccstats_frag
sudo install -m644 -o root -g root "$HOME/.ccstats_frag.pub" /root/.ssh/ccstats_frag.pub
sudo rm -f /root/.ssh/.ccstats_frag /root/.ssh/.ccstats_frag.pub   # clean any dotfile left by the old bug
# pre-trust main's host key so the unattended upload never prompts
sudo sh -c "ssh-keyscan -T 5 '$MAIN_DOMAIN' 2>/dev/null >> /root/.ssh/known_hosts; sort -u /root/.ssh/known_hosts -o /root/.ssh/known_hosts"
# uploader (used by cron AND the smoke test) — ships both the stats fragment AND the limits reading
sudo install -m755 /tmp/ccstats-shipfrag.sh /opt/claude-stats/ship-fragment.sh
# root cron — usage feed every minute (token usage is fine on a relaxed cadence)
sudo tee /etc/cron.d/ccstats-fragment >/dev/null <<CRON
SHELL=/bin/sh
* * * * * root /opt/claude-stats/ship-fragment.sh $LABEL $STATSUSER@$MAIN_DOMAIN >>/var/log/ccstats-fragment.log 2>&1
CRON
sudo chmod 644 /etc/cron.d/ccstats-fragment
# rotate the every-minute shipper log so it can never grow unbounded. logrotate ships in the
# Debian/Ubuntu base and runs itself (logrotate.timer / cron.daily); no cron of ours needed.
if [ -d /etc/logrotate.d ]; then
sudo tee /etc/logrotate.d/ccstats-fragment >/dev/null <<'LR'
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
sudo chmod 644 /etc/logrotate.d/ccstats-fragment
else
echo "  WARN /etc/logrotate.d not found — install 'logrotate' or /var/log/ccstats-fragment.log will grow unbounded"
fi
rm -f /tmp/ccstats-extract.py /tmp/ccstats-pricing.json /tmp/ccstats-usagemon.py /tmp/ccstats-shipfrag.sh
# smoke test now
sudo /opt/claude-stats/ship-fragment.sh "$LABEL" "$STATSUSER@$MAIN_DOMAIN"
# the private data key now lives only in /root/.ssh — drop the staging copy from $HOME
rm -f "$HOME/.ccstats_frag" "$HOME/.ccstats_frag.pub"
echo CCSTATS_SETUP_DONE
REMOTE
$SCPK "$SETUP_LOCAL" "$TARGET:/tmp/ccstats-setup.sh" >/dev/null
rm -f "$SETUP_LOCAL"
$SSHK -t "$TARGET" "LABEL='$LABEL' TZ_NAME='$TZ_NAME' MAIN_DOMAIN='$MAIN_DOMAIN' STATSUSER='$STATSUSER' bash /tmp/ccstats-setup.sh"
$SSHK "$TARGET" 'rm -f /tmp/ccstats-setup.sh' 2>/dev/null || true
ok "remote configured + cron installed + smoke test ran"

# ── verify the fragment landed here ───────────────────────────────────────────────────────────────
b "7. Verifying on main"
sleep 1
[ -f "$FRAG/$LABEL.json" ] || die "fragment did NOT arrive at $FRAG/$LABEL.json — check the remote can reach $MAIN_DOMAIN:22"
N="$(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1])).get("sessions",[])))' "$FRAG/$LABEL.json" 2>/dev/null || echo '?')"
ok "fragment landed: $FRAG/$LABEL.json  ($N sessions)"
# limits reading is best-effort (only ships fresh when this box has an active token); don't fail the
# provision if it's absent, just report — MAIN serves whichever box currently has a live session.
if [ -f "$WEB/limits-remote/$LABEL.json" ]; then
  LS="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print("stale" if d.get("stale") else (str((d.get("session") or {}).get("utilization"))+"%"))' "$WEB/limits-remote/$LABEL.json" 2>/dev/null || echo '?')"
  ok "limits reading landed: $WEB/limits-remote/$LABEL.json  (session=$LS)"
else
  info "no limits reading yet (this box may have no active Claude session — fine; it ships once one runs)"
fi

# ── record in the registry (for --list / --update) ────────────────────────────────────────────────
umask 077
cat > "$REG/$LABEL.conf" <<CONF
label=$LABEL
user=$RUSER
host=$RHOST
main_domain=$MAIN_DOMAIN
timezone=$TZ_NAME
live=0
CONF

echo
b "✓ Done — '$LABEL' is wired in."
info "Stats fragment + limits reading ship every minute; --mode full folds stats into all totals, and"
info "  MAIN's usage-monitor --merge-dir serves this box's limits whenever it has the active session."
info "Update its code later:   sudo $0 --update $LABEL    (or --update all)"
info "List remotes:            sudo $0 --list"
info "Remote log:              ssh $TARGET 'sudo tail -f /var/log/ccstats-fragment.log'"
