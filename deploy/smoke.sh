#!/usr/bin/env bash
#
# smoke.sh — independent verification of a deployed vps-stats install. Run as root on the box.
#
# Deliberately NO `set -e`: this script's whole job is to keep going and report one result per
# check, even after a failure. We use `set -uo pipefail` so unset variables and broken pipes are
# still errors of the kind that should be caught while writing the script.
set -uo pipefail

QUICK=0
PUBLIC_IP=""
TIMER_STOPPED=0

usage() {
  cat <<'EOF'
Usage: deploy/smoke.sh [options]

Verify a deployed vps-stats install. Run as root on the VPS.

Options:
  --quick            skip the slow staleness test (check 12)
  --public-ip IP     public address used by the "not reachable on the public internet" check
  -h, --help         show this help and exit
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)      QUICK=1; shift ;;
    --public-ip)  PUBLIC_IP="${2:?--public-ip needs a value}"; shift 2 ;;
    --public-ip=*) PUBLIC_IP="${1#*=}"; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

API="http://127.0.0.1:8080/api/stats"
PAGE="http://127.0.0.1:8080/"
SCRATCH="$(mktemp -d)"

# THE most important lines in this file. If the staleness test stopped the timer, an
# interrupted or failed run must not leave the collector switched off, so the trap restarts it
# as well as cleaning the scratch directory. Do not remove this.
cleanup() {
  if [[ "${TIMER_STOPPED:-0}" -eq 1 ]]; then
    systemctl start vps-stats.timer 2>/dev/null || true
  fi
  if [[ -n "${SCRATCH:-}" && -d "${SCRATCH:-}" ]]; then
    rm -rf "$SCRATCH"
  fi
}
trap cleanup EXIT INT TERM

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS  %s — %s\n' "$1" "$2"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL  %s — %s\n' "$1" "$2"; }
skip() { SKIP_COUNT=$((SKIP_COUNT + 1)); printf 'SKIP  %s — %s\n' "$1" "$2"; }

# check <name> <observed value> <predicate command...>
# The predicate's exit status decides PASS or FAIL; the observed value is printed either way.
check() {
  local name="$1" observed="$2"
  shift 2
  if "$@" >/dev/null 2>&1; then
    pass "$name" "$observed"
  else
    fail "$name" "$observed"
  fi
}

# field <json file> <dotted path> — print one value, empty when it cannot be read.
field() {
  python3 -c '
import json, sys
try:
    node = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    raise SystemExit(1)
for part in sys.argv[2].split("."):
    node = node[part]
print(node)
' "$1" "$2" 2>/dev/null
}

# A bare 403 from /api/stats tells the reader nothing. Spell out what it means: the nginx worker
# is not in the served file's group, so name the state directory, its group and the file mode.
http_note() {
  local code="$1"
  if [[ "$code" = "403" ]]; then
    printf '403 (nginx worker cannot read /var/lib/vps-stats/stats.json: group www-data, mode 640)'
  else
    printf '%s' "${code:-none}"
  fi
}

# 1. ----------------------------------------------------------------- only expected ports
ss_listen="$(ss -ltnH 2>/dev/null || ss -ltn 2>/dev/null | tail -n +2 || true)"
ts_ips="$(tailscale status --json 2>/dev/null | python3 -c '
import json, sys
data = json.load(sys.stdin)
print(" ".join(data.get("Self", {}).get("TailscaleIPs") or []))
' 2>/dev/null || true)"
unexpected="$(printf '%s\n' "$ss_listen" | TS_IPS="$ts_ips" python3 -c '
import ipaddress, os, sys
networks = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]
for value in os.environ.get("TS_IPS", "").split():
    try:
        networks.append(ipaddress.ip_network(value))
    except ValueError:
        pass
bad = []
for line in sys.stdin:
    parts = line.split()
    if len(parts) < 4:
        continue
    local = parts[3]
    host, _, port = local.rpartition(":")
    host = host.strip("[]")
    if port == "22":
        continue
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and (addr.is_loopback or any(addr in net for net in networks)):
        continue
    bad.append(local)
print(",".join(bad))
' || printf 'validator-error')"
check "only expected ports listen" "unexpected: ${unexpected:-none}" test -z "$unexpected"

# 2. --------------------------------------------------- nginx is loopback-only for our site
has_loop=0
printf '%s\n' "$ss_listen" | grep -q '127\.0\.0\.1:8080' && has_loop=1
wildcard=0
printf '%s\n' "$ss_listen" | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\*|\[::\]):8080' && wildcard=1
if [[ "$has_loop" -eq 1 && "$wildcard" -eq 0 ]]; then
  check "nginx listens on loopback only" "127.0.0.1:8080 present, wildcard absent" true
else
  check "nginx listens on loopback only" "127.0.0.1:8080=$has_loop wildcard=$wildcard" false
fi

# 3. ----------------------------------------------------------- the page answers on loopback
page_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$PAGE" 2>/dev/null || true)"
check "page answers on loopback" "HTTP ${page_code:-none}" test "$page_code" = "200"

# Fetch the API document once for checks 4-6, keeping the HTTP status so that a 403 can be
# spelled out: it means the nginx worker cannot read the served file.
api_code="$(curl -s --max-time 5 -w '%{http_code}' "$API" \
  -o "$SCRATCH/api.json" 2>/dev/null || true)"
api_code="${api_code:-none}"
api_note="$(http_note "$api_code")"

# 4. -------------------------------------------- /api/stats is JSON with the promised shape
shape_out="$(python3 -c '
import json, sys, time
try:
    doc = json.load(sys.stdin)
except ValueError as exc:
    print("not JSON: %s" % exc)
    raise SystemExit(1)
problems = []
if doc.get("schema") != 1:
    problems.append("schema=%r" % doc.get("schema"))
vps = doc.get("hosts", {}).get("vps", {})
if vps.get("status") != "online":
    problems.append("hosts.vps.status=%r" % vps.get("status"))
history = doc.get("history", {})
if not isinstance(history.get("vps", {}).get("t"), list):
    problems.append("history.vps.t is not a list")
epoch = vps.get("generated_at_epoch")
if not isinstance(epoch, (int, float)) or abs(time.time() - epoch) > 120:
    problems.append("generated_at_epoch=%r not within 120s" % epoch)
for kind in ("vps", "mac"):
    series = history.get(kind)
    if not isinstance(series, dict):
        continue
    lengths = {key: len(value) for key, value in series.items() if isinstance(value, list)}
    if lengths and len(set(lengths.values())) != 1:
        problems.append("%s series lengths differ: %r" % (kind, lengths))
if problems:
    print("; ".join(problems))
    raise SystemExit(1)
print("schema=1, vps online, series parallel")
' < "$SCRATCH/api.json")"
shape_rc=$?
check "/api/stats has the promised shape" \
  "HTTP $api_note ${shape_out:-no output}" test "$shape_rc" -eq 0

# 5. ------------------------------------------------------------ /api/stats is never cached
api_head_code="$(curl -sI --max-time 5 "$API" -o "$SCRATCH/api.headers" \
  -w '%{http_code}' 2>/dev/null || true)"
api_head_code="${api_head_code:-none}"
api_headers="$(cat "$SCRATCH/api.headers" 2>/dev/null || true)"
page_headers="$(curl -sI --max-time 5 "$PAGE" 2>/dev/null || true)"
api_cache="$(printf '%s\n' "$api_headers" | grep -i '^Cache-Control:' | tr -d '\r' | head -n1)"
page_cache="$(printf '%s\n' "$page_headers" | grep -i '^Cache-Control:' | tr -d '\r' | head -n1)"
api_nosniff="$(printf '%s\n' "$api_headers" | grep -ci '^X-Content-Type-Options: *nosniff' || true)"
page_nosniff="$(printf '%s\n' "$page_headers" \
  | grep -ci '^X-Content-Type-Options: *nosniff' || true)"
cache_ok=1
printf '%s' "$api_cache" | grep -qi 'no-store' || cache_ok=0
printf '%s' "$page_cache" | grep -qi 'max-age=300' || cache_ok=0
[[ "$api_nosniff" -ge 1 ]] || cache_ok=0
[[ "$page_nosniff" -ge 1 ]] || cache_ok=0
api_cache_observed="HTTP $(http_note "$api_head_code") api[$api_cache] page[$page_cache]"
api_cache_observed="$api_cache_observed nosniff api/page=${api_nosniff}/${page_nosniff}"
check "/api/stats is never cached" "$api_cache_observed" test "$cache_ok" -eq 1

# 6. ---------------------------------------------------------------- the numbers match the box
mem_total_kb="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)"
mem_box="$(awk -v kb="$mem_total_kb" 'BEGIN {printf "%.2f", kb*1024/1073741824}')"
mem_json="$(field "$SCRATCH/api.json" hosts.vps.memory.total_gb)"
mem_ok="$(awk -v box="$mem_box" -v js="${mem_json:-0}" \
  'BEGIN {d=box-js; if (d<0) d=-d; print (d <= 0.05*box) ? 1 : 0}')"
check "memory total matches the box" \
  "HTTP $api_note box ${mem_box} GB vs json ${mem_json:-?} GB" test "$mem_ok" = "1"

disk_used_kb="$(df -k / | awk 'NR==2 {print $3}')"
disk_box="$(awk -v kb="$disk_used_kb" 'BEGIN {printf "%.1f", kb*1024/1073741824}')"
disk_json="$(field "$SCRATCH/api.json" hosts.vps.disk.used_gb)"
disk_ok="$(awk -v box="$disk_box" -v js="${disk_json:-0}" \
  'BEGIN {d=box-js; if (d<0) d=-d; print (d <= 0.05*box) ? 1 : 0}')"
check "disk used matches the box" \
  "HTTP $api_note box ${disk_box} GB vs json ${disk_json:-?} GB" test "$disk_ok" = "1"

load1_box="$(awk '{print $1}' /proc/loadavg)"
load_json="$(field "$SCRATCH/api.json" hosts.vps.load.1m)"
load_ok="$(awk -v box="$load1_box" -v js="${load_json:-0}" \
  'BEGIN {d=box-js; if (d<0) d=-d; print (d <= 0.5) ? 1 : 0}')"
check "load 1m matches the box" \
  "HTTP $api_note box ${load1_box} vs json ${load_json:-?}" test "$load_ok" = "1"

uptime_box="$(awk '{print int($1)}' /proc/uptime)"
uptime_json="$(field "$SCRATCH/api.json" hosts.vps.uptime_s)"
uptime_ok="$(awk -v box="$uptime_box" -v js="${uptime_json:-0}" \
  'BEGIN {d=box-js; if (d<0) d=-d; print (d <= 60) ? 1 : 0}')"
check "uptime matches the box" \
  "HTTP $api_note box ${uptime_box} s vs json ${uptime_json:-?} s" test "$uptime_ok" = "1"

bad_pcts="$(python3 -c '
import json, sys
doc = json.load(open(sys.argv[1]))

def walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, path + "/" + key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, path + "/%d" % index)
    else:
        yield path, node

bad = []
for path, value in walk(doc):
    if not any(part.endswith("_pct") for part in path.split("/")):
        continue
    if value is None:
        continue
    if not isinstance(value, (int, float)) or value < 0 or value > 100:
        bad.append((path, value))
print(", ".join("%s=%s" % (p, v) for p, v in bad))
' "$SCRATCH/api.json" 2>/dev/null || echo "could not read the document")"
check "every _pct is within 0-100" \
  "HTTP $api_note ${bad_pcts:-all within range}" test -z "$bad_pcts"

# 7. ------------------------------------------------------------ nothing on the public internet
if [[ -z "$PUBLIC_IP" ]]; then
  skip "not reachable on the public internet" "no --public-ip supplied"
else
  pub_out="$(curl -s -w '\n%{http_code}' --max-time 5 --max-redirs 0 \
    "http://$PUBLIC_IP:8080/" 2>/dev/null)"
  pub_rc=$?
  pub_code="${pub_out##*$'\n'}"
  pub_body="${pub_out%$'\n'*}"
  if [[ "$pub_rc" -ne 0 || -z "$pub_body" ]]; then
    check "not reachable on the public internet" "curl rc=$pub_rc, body empty, as expected" true
  elif [[ "$pub_code" = "200" ]]; then
    check "not reachable on the public internet" \
      "HTTP 200 from http://$PUBLIC_IP:8080/ — the site is exposed" false
  else
    check "not reachable on the public internet" \
      "HTTP $pub_code with a body from http://$PUBLIC_IP:8080/" false
  fi
fi

# 8. --------------------------------------------- the timer is armed, the service is oneshot
timer_active="$(systemctl is-active vps-stats.timer 2>/dev/null || true)"
service_type_line="$(systemctl show -p Type vps-stats.service 2>/dev/null || true)"
timer_next="$(systemctl list-timers vps-stats.timer --no-pager 2>/dev/null | sed -n '2p')"
armed_ok=1
[[ "$timer_active" = "active" ]] || armed_ok=0
[[ "$service_type_line" = "Type=oneshot" ]] || armed_ok=0
[[ -n "$timer_next" && "$timer_next" != *"n/a"* && "$timer_next" == *[0-9]* ]] || armed_ok=0
check "timer is armed and the service is oneshot" \
  "active=$timer_active $service_type_line next=${timer_next:-none}" test "$armed_ok" -eq 1

# 9. ------------------------------------------------------------- freshness advances (20 s)
epoch1="$(field "$SCRATCH/api.json" generated_at_epoch)"
sleep 20
curl -s --max-time 5 "$API" -o "$SCRATCH/api2.json" 2>/dev/null || true
epoch2="$(field "$SCRATCH/api2.json" generated_at_epoch)"
advance=""
if [[ "$epoch1" =~ ^[0-9]+$ && "$epoch2" =~ ^[0-9]+$ ]]; then
  advance=$((epoch2 - epoch1))
fi
advance_ok=0
if [[ -n "$advance" && "$advance" -ge 15 && "$advance" -le 45 ]]; then
  advance_ok=1
fi
check "freshness advances (15-45 s in 20 s)" "advanced ${advance:-unknown} s" \
  test "$advance_ok" -eq 1

# 10. ------------------------------------------------------------------------ resource budget
nginx_rss="$(ps -o rss= -C nginx 2>/dev/null | awk '{s+=$1} END {print s+0}')"
check "nginx RSS is within 20 MB" "${nginx_rss} kB" test "$nginx_rss" -le 20480

cpu_nsec="$(systemctl show vps-stats.service -p CPUUsageNSec --value 2>/dev/null || true)"
mem_line="$(systemctl show vps-stats.service -p MemoryCurrent 2>/dev/null || true)"
mem_current="${mem_line#MemoryCurrent=}"
ticks="$(journalctl -u vps-stats.service --since '-1min' --no-pager 2>/dev/null \
  | grep -c 'Starting' || true)"
memory_ok=1
# systemd reports a UINT64_MAX sentinel for some gone cgroups; treat absurd values as
# unavailable rather than failing the run on a number that is not a measurement.
if [[ "$mem_current" =~ ^[0-9]+$ ]] && [[ "$mem_current" -lt 1099511627776 ]] \
  && [[ "$mem_current" -gt $((128 * 1024 * 1024)) ]]; then
  memory_ok=0
fi
# CPU is reported, not asserted: on a 1-vCPU box a single number is not a meaningful budget.
budget_observed="CPUUsageNSec=${cpu_nsec:-unknown}"
budget_observed="$budget_observed MemoryCurrent=${mem_current:-unavailable}"
budget_observed="$budget_observed ticks/1min=${ticks}"
check "service is within its memory budget" "$budget_observed" test "$memory_ok" -eq 1

# 11. ------------------------------------------------- reachable on the tailnet, from the Mac
dns_name="$(tailscale status --json 2>/dev/null | python3 -c '
import json, sys
data = json.load(sys.stdin)
print((data.get("Self", {}).get("DNSName") or "").rstrip("."))
' 2>/dev/null || true)"
if [[ -z "$dns_name" ]]; then
  skip "reachable on the tailnet from the Mac" "no tailnet DNS name available"
else
  mac_out="$(ssh -o BatchMode=yes -o ConnectTimeout=8 mac \
    "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://$dns_name/api/stats || true" \
    2>/dev/null)"
  mac_rc=$?
  if [[ "$mac_rc" -ne 0 ]]; then
    skip "reachable on the tailnet from the Mac" \
      "ssh mac unreachable; an asleep Mac is not a smoke failure"
  else
    check "reachable on the tailnet from the Mac" \
      "http://$dns_name/api/stats -> HTTP ${mac_out:-no code}" test "$mac_out" = "200"
  fi
fi

# 12. ------------------------------------------------------------------- staleness honesty
if [[ "$QUICK" -eq 1 ]]; then
  skip "staleness honesty" "--quick"
else
  TIMER_STOPPED=1
  systemctl stop vps-stats.timer 2>/dev/null || true
  curl -s --max-time 5 "$API" -o "$SCRATCH/frozen1.json" 2>/dev/null || true
  frozen_epoch="$(field "$SCRATCH/frozen1.json" generated_at_epoch)"
  sleep 100
  curl -s --max-time 5 "$API" -o "$SCRATCH/frozen2.json" 2>/dev/null || true
  frozen_after="$(field "$SCRATCH/frozen2.json" generated_at_epoch)"

  frozen_ok=0
  if [[ "$frozen_epoch" =~ ^[0-9]+$ && "$frozen_epoch" = "$frozen_after" ]]; then
    frozen_ok=1
  fi
  check "document freezes when the timer stops" \
    "at stop: ${frozen_epoch:-?} after 100 s: ${frozen_after:-?}" test "$frozen_ok" -eq 1

  frozen_age="unknown"
  age_ok=0
  if [[ "$frozen_epoch" =~ ^[0-9]+$ ]]; then
    frozen_age=$(( $(date +%s) - frozen_epoch ))
    [[ "$frozen_age" -gt 90 ]] && age_ok=1
  fi
  check "frozen document ages past the 90 s red line" "age ${frozen_age} s" test "$age_ok" -eq 1

  curl -s --max-time 5 "$PAGE" -o "$SCRATCH/page.html" 2>/dev/null || true
  # The page's age maths is the thing that must not regress, and `grep -q 'Date.now()'` cannot
  # detect its regression: Date.now() also appears in the degraded no-Date-header path and in
  # the 1 s re-render, so deleting the server-clock anchor outright left the check green while
  # the original false-green failure came straight back. So run the page's own unit tests when
  # node is available, and otherwise require both halves of the anchor wiring — and say which
  # of the two ran, because the grep is the weaker check.
  clock_ok=0
  clock_observed=""
  page_test_path="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)/tests/test_page.mjs"
  if command -v node >/dev/null 2>&1 && [[ -f "$page_test_path" ]]; then
    if page_test_out="$(node "$page_test_path" 2>&1)"; then
      clock_ok=1
      clock_observed="node tests/test_page.mjs -> $(printf '%s' "$page_test_out" | tail -n1)"
    else
      clock_observed="node tests/test_page.mjs failed -> $(printf '%s' "$page_test_out" | tail -n1)"
    fi
  else
    anchor_reads=0
    anchor_uses=0
    grep -q "headers.get('date')" "$SCRATCH/page.html" && anchor_reads=1
    grep -q 'ageAnchor.serverEpoch' "$SCRATCH/page.html" && anchor_uses=1
    [[ "$anchor_reads" -eq 1 && "$anchor_uses" -eq 1 ]] && clock_ok=1
    clock_observed="grep fallback (no node): Date header read=$anchor_reads, anchor used=$anchor_uses"
  fi
  check "page ages its own numbers from the server clock" "$clock_observed" \
    test "$clock_ok" -eq 1

  systemctl start vps-stats.timer 2>/dev/null || true
  fresh_start="$(date +%s)"
  fresh_epoch="$frozen_after"
  while [[ $(( $(date +%s) - fresh_start )) -lt 45 ]]; do
    curl -s --max-time 5 "$API" -o "$SCRATCH/fresh.json" 2>/dev/null || true
    candidate="$(field "$SCRATCH/fresh.json" generated_at_epoch)"
    if [[ "$candidate" =~ ^[0-9]+$ && -n "$frozen_after" ]] \
      && [[ "$candidate" -gt "$frozen_after" ]]; then
      fresh_epoch="$candidate"
      break
    fi
    sleep 2
  done
  fresh_secs=$(( $(date +%s) - fresh_start ))
  fresh_ok=0
  if [[ "$fresh_epoch" =~ ^[0-9]+$ && -n "$frozen_after" ]] \
    && [[ "$fresh_epoch" -gt "$frozen_after" ]]; then
    fresh_ok=1
  fi
  check "fresh document within 45 s of restart" \
    "fresh epoch ${fresh_epoch:-?} after ${fresh_secs}s" test "$fresh_ok" -eq 1
  TIMER_STOPPED=0
fi

# 13. ------------------------------- served state is readable by the nginx worker, and private
# The served document must be group-readable by the nginx worker through the setgid state
# directory, and must never become world-readable. Prove the group read rather than trusting
# the mode bits alone.
state_dir=/var/lib/vps-stats
served_file="$state_dir/stats.json"
state_stat="$(stat -c '%a %U %G' "$state_dir" 2>/dev/null || true)"
served_stat="$(stat -c '%a %U %G' "$served_file" 2>/dev/null || true)"
served_mode="${served_stat%% *}"
# The nginx master also answers to `ps -C nginx` and runs as root; reading as root would pass
# whatever the mode, so drop it and use a worker.
worker_user="$(ps -o user= -C nginx 2>/dev/null | awk '{print $1}' \
  | sort -u | grep -vx 'root' | head -1)"
worker_user="${worker_user:-www-data}"

world_readable=0
if [[ "$served_mode" =~ ^[0-9]+$ ]] && [[ $(( 0$served_mode & 0o004 )) -ne 0 ]]; then
  world_readable=1
fi
mode_ok=0
if [[ "$state_stat" = "2750 vpsstats www-data" && "$served_stat" = "640 vpsstats www-data" ]]; then
  mode_ok=1
fi

probe_tool=""
probe_ok=0
if command -v runuser >/dev/null 2>&1; then
  probe_tool="runuser -u $worker_user"
  if runuser -u "$worker_user" -- head -c 1 "$served_file" >/dev/null 2>&1; then
    probe_ok=1
  fi
elif command -v setpriv >/dev/null 2>&1; then
  worker_group="$(id -gn "$worker_user" 2>/dev/null || true)"
  worker_group="${worker_group:-www-data}"
  probe_tool="setpriv --reuid=$worker_user --regid=$worker_group --clear-groups"
  if setpriv --reuid="$worker_user" --regid="$worker_group" --clear-groups \
    head -c 1 "$served_file" >/dev/null 2>&1; then
    probe_ok=1
  fi
fi

name13="state files are readable by the nginx worker and world files are refused"
observed13="dir[$state_stat] stats.json[$served_stat]"
if [[ "$world_readable" -eq 1 ]]; then
  fail "$name13" "$observed13 — stats.json is world-readable"
elif [[ "$mode_ok" -ne 1 ]]; then
  fail "$name13" "$observed13 — want dir 2750 vpsstats www-data, file 640 vpsstats www-data"
elif [[ "$probe_ok" -eq 1 ]]; then
  pass "$name13" "$observed13 — $probe_tool can read stats.json"
elif [[ -z "$probe_tool" ]]; then
  skip "$name13" "$observed13 — neither runuser nor setpriv is available for the read probe"
else
  fail "$name13" "$observed13 — $probe_tool could not read stats.json"
fi

printf '\n%d passed, %d failed, %d skipped\n' "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT"
if [[ "$FAIL_COUNT" -eq 0 ]]; then
  exit 0
fi
exit 1
