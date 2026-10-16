#!/usr/bin/env bash
#
# install.sh — deploy vps-stats on a VPS. Run as root.
#
# Idempotent: a second run changes nothing, and it is safe to run on a box where a previous run
# half-finished. Every file written into the system is owned by root; the only exception is the
# state directory /var/lib/vps-stats, which belongs to the unprivileged vpsstats user.
set -euo pipefail

REPO_ROOT_DEFAULT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
REPO_ROOT="$REPO_ROOT_DEFAULT"
SERVE_PORT=80
MAC_ALIAS="mac"
DRY_RUN=0
NO_MAC_KEY=0
STEP=0

usage() {
  cat <<'EOF'
Usage: deploy/install.sh [options]

Deploy vps-stats on this VPS. Run as root; the commands it prints are not prefixed with sudo.

Options:
  --dry-run           print every command, change nothing
  --no-mac-key        skip generating and authorising the ssh key for the Mac probe
  --serve-port N      tailnet port for `tailscale serve` (default: 80)
  --repo-root DIR     source tree to install from (default: this script's parent directory)
  --mac-alias NAME    ssh alias the exporter uses for the Mac (default: mac)
  -h, --help          show this help and exit
EOF
}

say()  { printf '    %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

step() {
  STEP=$((STEP + 1))
  printf '\n==> [%d/%d] %s\n' "$STEP" 9 "$*"
}

# Echo a command, then run it unless we are in --dry-run. Reading state is done directly where
# it is needed; this wrapper guards every command that would change the box.
run() {
  printf '    +'
  printf ' %q' "$@"
  printf '\n'
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=1; shift ;;
    --no-mac-key)   NO_MAC_KEY=1; shift ;;
    --serve-port)   SERVE_PORT="${2:?--serve-port needs a value}"; shift 2 ;;
    --serve-port=*) SERVE_PORT="${1#*=}"; shift ;;
    --repo-root)    REPO_ROOT="${2:?--repo-root needs a value}"; shift 2 ;;
    --repo-root=*)  REPO_ROOT="${1#*=}"; shift ;;
    --mac-alias)    MAC_ALIAS="${2:?--mac-alias needs a value}"; shift 2 ;;
    --mac-alias=*)  MAC_ALIAS="${1#*=}"; shift ;;
    -h|--help)      usage; exit 0 ;;
    *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "$SERVE_PORT" =~ ^[0-9]+$ ]]; then
  printf -- '--serve-port must be a number, got: %s\n' "$SERVE_PORT" >&2
  exit 2
fi

# 1. ------------------------------------------------------------------------ preflight
step "Preflight"
if [[ "$DRY_RUN" -eq 0 && "$EUID" -ne 0 ]]; then
  printf 'install.sh must run as root (use sudo). Use --dry-run to preview without root.\n' >&2
  exit 1
fi
for tool in systemctl python3 tailscale curl ssh ssh-keygen apt-get; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$tool" >&2
    exit 1
  fi
done
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  printf 'python3 3.9 or newer is required; found: %s\n' "$(python3 --version 2>&1)" >&2
  exit 1
fi
for relative in \
  exporter/stats.py \
  web/index.html \
  systemd/vps-stats.service \
  systemd/vps-stats.timer \
  deploy/nginx.conf
do
  if [[ ! -f "$REPO_ROOT/$relative" ]]; then
    printf 'Missing required file: %s/%s — is --repo-root correct?\n' "$REPO_ROOT" "$relative" >&2
    exit 1
  fi
done
if ! systemctl is-active --quiet tailscaled; then
  printf 'tailscaled is not running; start it before installing (the site is tailnet-only).\n' >&2
  exit 1
fi
DNS_NAME="$(tailscale status --json 2>/dev/null | python3 -c '
import json, sys
data = json.load(sys.stdin)
print((data.get("Self", {}).get("DNSName") or "").rstrip("."))
' 2>/dev/null || true)"
if [[ -z "$DNS_NAME" ]]; then
  printf '%s\n' \
    'No tailnet DNS name in `tailscale status --json`; this box must be reachable on the' \
    'tailnet.' >&2
  exit 1
fi
SHORT_NAME="${DNS_NAME%%.*}"
say "tailnet name: $DNS_NAME"
say "card name:    $SHORT_NAME"

# 2. ------------------------------------------------------------------------ nginx package
step "nginx"
if command -v nginx >/dev/null 2>&1; then
  say "nginx already installed; skipping apt"
else
  run apt-get update -qq
  run apt-get install -y --no-install-recommends nginx
fi

# 3. ----------------------------------------------------------------- user and state dir
step "Service user and state directory"
# Create the group explicitly. `useradd --system` only gets a same-named group because the host's
# /etc/login.defs says USERGROUPS_ENAB yes; where it says no, step 5's
# `install -d -o vpsstats -g vpsstats` fails under `set -e` and the unit's Group= does not
# resolve either. One line removes the hidden dependency on that default.
if getent group vpsstats >/dev/null 2>&1; then
  say "group vpsstats already exists"
else
  run groupadd --system vpsstats
fi
if id vpsstats >/dev/null 2>&1; then
  say "user vpsstats already exists"
else
  run useradd --system --home-dir /var/lib/vps-stats --shell /usr/sbin/nologin vpsstats
fi
# www-data comes with the nginx package installed in step 2; check before install -d so a missing
# group names itself instead of failing with a bare error.
if ! getent group www-data >/dev/null 2>&1; then
  printf '%s\n' \
    'Missing group: www-data — it is created by the nginx package; did step 2 install nginx?' >&2
  exit 1
fi
# The state directory is setgid and grouped with www-data, so files created inside it inherit that
# group and the nginx worker can read the served JSON by group without the file being
# world-readable. The exporter's own process group is deliberately left alone (vpsstats): the
# directory supplies the file group, not the process. `install -d` re-applies owner, group and mode
# to an existing directory, so this line also repairs a directory left behind by an earlier run.
run install -d -o vpsstats -g www-data -m 2750 /var/lib/vps-stats

# 4. ------------------------------------------------------------------- installed files
step "Install files"
run install -d /opt/vps-stats/exporter /opt/vps-stats/web
run install -m 0644 "$REPO_ROOT/exporter/stats.py" /opt/vps-stats/exporter/stats.py
run install -m 0644 "$REPO_ROOT/web/index.html" /opt/vps-stats/web/index.html
run install -m 0644 "$REPO_ROOT/systemd/vps-stats.service" /etc/systemd/system/vps-stats.service
run install -m 0644 "$REPO_ROOT/systemd/vps-stats.timer" /etc/systemd/system/vps-stats.timer
run install -d /etc/nginx/sites-available /etc/nginx/sites-enabled
run install -m 0644 "$REPO_ROOT/deploy/nginx.conf" /etc/nginx/sites-available/vps-stats.conf
run ln -sfn /etc/nginx/sites-available/vps-stats.conf /etc/nginx/sites-enabled/vps-stats.conf

# The nginx package drops /etc/nginx/sites-enabled/default to serve a stock welcome page that
# nothing here needs and nothing was asked to keep. Left in place it would also answer on
# 127.0.0.1:8080 and shadow our site.
if [[ -e /etc/nginx/sites-enabled/default ]]; then
  run rm -f /etc/nginx/sites-enabled/default
fi

# The service defaults --name to the hostname, which on this box is the unhelpful "vps". Set it
# to the short tailnet name via a drop-in so the card shows the name the reader typed.
DROPIN_DIR=/etc/systemd/system/vps-stats.service.d
DROPIN_FILE="$DROPIN_DIR/name.conf"
run install -d -m 0755 "$DROPIN_DIR"
DESIRED_DROPIN="[Service]
Environment=VPS_STATS_NAME=$SHORT_NAME"
if [[ -f "$DROPIN_FILE" ]] && [[ "$(<"$DROPIN_FILE")" == "$DESIRED_DROPIN" ]]; then
  say "drop-in already current: $DROPIN_FILE (card name: $SHORT_NAME)"
else
  say "writing $DROPIN_FILE (card name: $SHORT_NAME)"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    printf '%s\n' "$DESIRED_DROPIN" > "$DROPIN_FILE"
    chmod 0644 "$DROPIN_FILE"
  fi
fi

# Best effort: record the revision so the box can be traced back to a commit. A checkout with no
# history is fine; skip the file rather than fail the install.
if DEPLOYED_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)"; then
  if [[ "$DRY_RUN" -eq 0 ]]; then
    printf '%s\n' "$DEPLOYED_SHA" > /opt/vps-stats/DEPLOYED_SHA
  else
    say "would write /opt/vps-stats/DEPLOYED_SHA = $DEPLOYED_SHA"
  fi
else
  say "no git revision in $REPO_ROOT; skipping /opt/vps-stats/DEPLOYED_SHA"
fi

# 5. ------------------------------------------------------------------ Mac probe ssh key
step "Mac probe key"
if [[ "$NO_MAC_KEY" -eq 1 ]]; then
  say "--no-mac-key given: leaving the Mac probe key and ssh config alone"
else
  SSH_DIR=/var/lib/vps-stats/.ssh
  SSH_CONFIG="$SSH_DIR/config"
  KEY="$SSH_DIR/id_ed25519"
  run install -d -o vpsstats -g vpsstats -m 0700 "$SSH_DIR"
  if [[ -f "$KEY" ]]; then
    say "ssh key already present: $KEY"
  else
    run ssh-keygen -t ed25519 -N "" -f "$KEY"
  fi
  if [[ -f "$KEY" ]]; then
    run chown vpsstats:vpsstats "$KEY"
    run chmod 0600 "$KEY"
  fi
  if [[ -f "$KEY.pub" ]]; then
    run chown vpsstats:vpsstats "$KEY.pub"
  fi

  # Root's own ssh config already resolves the `mac` alias, so read HostName/User from it and
  # copy them into the exporter's private config (whose HOME is /var/lib/vps-stats).
  MAC_HOSTNAME="$(ssh -G "$MAC_ALIAS" 2>/dev/null \
    | awk '$1 == "hostname" {print $2; exit}' || true)"
  MAC_USER="$(ssh -G "$MAC_ALIAS" 2>/dev/null \
    | awk '$1 == "user" {print $2; exit}' || true)"
  if [[ -z "$MAC_HOSTNAME" || -z "$MAC_USER" ]]; then
    warn "could not resolve '$MAC_ALIAS' via \`ssh -G\`; skipping $SSH_CONFIG"
  else
    DESIRED_CONFIG="$(cat <<EOF
# Managed by the vps-stats deploy/install.sh — edit the repository, not this file.
# HostName and User come from root's own ssh config for the '$MAC_ALIAS' alias so the exporter,
# whose HOME is /var/lib/vps-stats, can reach the Mac without root's file.
Host $MAC_ALIAS
    HostName $MAC_HOSTNAME
    User $MAC_USER
    IdentityFile $KEY
    IdentitiesOnly yes
    BatchMode yes
    ConnectTimeout 8
    StrictHostKeyChecking accept-new
    UserKnownHostsFile ~/.ssh/known_hosts
EOF
)"
    if [[ -f "$SSH_CONFIG" ]] && [[ "$(<"$SSH_CONFIG")" == "$DESIRED_CONFIG" ]]; then
      say "ssh config already current: $SSH_CONFIG"
    else
      say "writing $SSH_CONFIG"
      if [[ "$DRY_RUN" -eq 0 ]]; then
        printf '%s\n' "$DESIRED_CONFIG" > "$SSH_CONFIG"
        chown vpsstats:vpsstats "$SSH_CONFIG"
        chmod 0600 "$SSH_CONFIG"
      fi
    fi

    if [[ -f "$KEY.pub" ]]; then
      PUBKEY="$(<"$KEY.pub")"
      # Escape any single quote in the key so the remote shell receives it verbatim.
      ESCAPED_PUBKEY=${PUBKEY//\'/\'\\\'\'}
      REMOTE_CMD="mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && \
chmod 600 ~/.ssh/authorized_keys && grep -qxF '$ESCAPED_PUBKEY' ~/.ssh/authorized_keys || \
echo '$ESCAPED_PUBKEY' >> ~/.ssh/authorized_keys"
      if [[ "$DRY_RUN" -eq 1 ]]; then
        say "would authorise the probe key on $MAC_ALIAS via ssh"
      elif ssh "$MAC_ALIAS" "$REMOTE_CMD"; then
        say "authorised the probe key on $MAC_ALIAS"
      else
        warn "could not reach the Mac at '$MAC_ALIAS'; re-run deploy/install.sh when it is awake"
        warn "to authorise the probe key. The install continues without it."
      fi
    else
      say "no public key yet (dry run); skipping Mac authorisation"
    fi
  fi
fi

# 6. -------------------------------------------------------------------------- systemd
step "systemd units"
run systemctl daemon-reload
run systemctl enable --now vps-stats.timer
run systemctl restart vps-stats.service

STATS_FILE=/var/lib/vps-stats/stats.json
GENERATED_AT=""
VPS_FIELD=""
if [[ "$DRY_RUN" -eq 1 ]]; then
  say "dry run: not waiting for $STATS_FILE"
else
  say "waiting up to 60 s for $STATS_FILE"
  for _ in $(seq 1 60); do
    READOUT="$(python3 - "$STATS_FILE" <<'PY' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        doc = json.load(handle)
except (OSError, ValueError):
    raise SystemExit(1)
if doc.get("schema") != 1:
    raise SystemExit(1)
print(doc.get("generated_at", ""), doc.get("hosts", {}).get("vps", {}).get("field", ""))
PY
)"
    if [[ -n "$READOUT" ]]; then
      GENERATED_AT="${READOUT%% *}"
      VPS_FIELD="${READOUT##* }"
      break
    fi
    sleep 1
  done
  if [[ -z "$GENERATED_AT" ]]; then
    systemctl status vps-stats.service --no-pager || true
    journalctl -u vps-stats.service -n 30 --no-pager || true
    printf 'No valid %s with schema 1 appeared within 60 s; install did not succeed.\n' \
      "$STATS_FILE" >&2
    exit 1
  fi
  say "first sample: generated_at=$GENERATED_AT field=$VPS_FIELD"
fi

# 7. ---------------------------------------------------------------------------- nginx
step "nginx configuration"
run nginx -t
if systemctl is-active --quiet nginx; then
  run systemctl reload nginx
else
  run systemctl restart nginx
fi

# 8. ------------------------------------------------------------------- tailnet publish
step "Publish on the tailnet"
if [[ "$DRY_RUN" -eq 1 ]]; then
  run tailscale serve --bg --http="$SERVE_PORT" http://127.0.0.1:8080
  SERVE_OK=1
elif tailscale serve --bg --http="$SERVE_PORT" http://127.0.0.1:8080; then
  SERVE_OK=1
  tailscale serve status || true
else
  SERVE_OK=0
  printf '\n' >&2
  warn "tailscale serve failed on HTTP $SERVE_PORT. Serve may not be enabled for this tailnet."
  warn "Enable Serve in the Tailscale admin console (DNS page, HTTPS/Serve), then re-run:"
  warn "  tailscale serve --bg --http=$SERVE_PORT http://127.0.0.1:8080"
  warn "Until then the page is reachable only on 127.0.0.1:8080."
fi

# 9. -------------------------------------------------------------------------- summary
step "Summary"
say "page:      http://$DNS_NAME/"
say "state dir: /var/lib/vps-stats"
say "card name: $SHORT_NAME"
if [[ "$SERVE_OK" -eq 0 ]]; then
  say "NOTE: tailnet publish is not in place yet — see the warning above."
fi
say "revert:"
say "  sudo tailscale serve reset"
say "  sudo systemctl disable --now vps-stats.timer vps-stats.service"
say "  sudo rm -f /etc/systemd/system/vps-stats.service /etc/systemd/system/vps-stats.timer"
say "  sudo rm -f /etc/systemd/system/vps-stats.service.d/name.conf"
say "  sudo rm -f /etc/nginx/sites-available/vps-stats.conf /etc/nginx/sites-enabled/vps-stats.conf"
say "  sudo rm -rf /var/lib/vps-stats"
say "  sudo rm -rf /opt/vps-stats"
say "  sudo systemctl reload nginx"
say "next: run deploy/smoke.sh to verify the deployment"
printf '\nINSTALL OK\n'
