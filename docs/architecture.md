# Architecture

## Shape

One unprivileged oneshot systemd unit on a timer, one static HTML file, one nginx site on
loopback, and one `tailscale serve` binding. There is no resident metrics daemon, no database and
no container. Each tick is a fresh `python3` process that reads local state, optionally probes the
Mac over ssh, and rewrites four small JSON files; systemd serialises ticks, so a slow Mac probe
delays the next tick rather than stacking a second copy.

## Components

| Piece | Where | Responsibility |
|---|---|---|
| Exporter | `exporter/stats.py` | Samples `/proc` and the root filesystem, probes the Mac, maintains the four state files, and builds the served document. Python 3 standard library only. |
| Service unit | `systemd/vps-stats.service` | Runs the exporter once per tick as `User=vpsstats`, with `HOME=/var/lib/vps-stats` and CPU/memory caps. `Type=oneshot`; no `[Install]` section, so the timer owns the schedule. |
| Timer unit | `systemd/vps-stats.timer` | Triggers the service every 15 s (`OnBootSec=30s`, `OnUnitActiveSec=15s`, `AccuracySec=1s`). |
| nginx site | `deploy/nginx.conf` | Serves `/` from `/opt/vps-stats/web` and `/api/stats` from the state file, bound to `127.0.0.1:8080` only, with cache and security headers. |
| Page | `web/index.html` | The whole UI in one file: fetches `/api/stats`, renders two cards, sparklines and status bands, and ages its own numbers. No build step. |
| Test suite | `tests/test_exporter.py` | Standard-library `unittest` checks for the parser, ring, staleness bands, redaction and file modes, using recorded fixtures under `tests/fixtures/`. |
| Installer | `deploy/install.sh` | Idempotent root install: packages, user, state directory, files, Mac key, units, nginx, `tailscale serve`. |
| Smoke test | `deploy/smoke.sh` | Independent post-install verification on the box; one result per check, exit 0 only when nothing failed. |

## Contracts

### The JSON document (`schema: 1`)

Top-level keys: `schema`, `version`, `generated_at`, `generated_at_epoch`, `interval_s`, `hosts`,
`history`. Each host (`hosts.vps`, `hosts.mac`) carries `kind`, `name`, `status`, `generated_at`,
`generated_at_epoch`, `age_s`, `field`, and the blocks `cpu` (`cores`, `busy_pct`), `memory`,
`swap`, `disk`, `load` (`1m`/`5m`/`15m`), `uptime_s` and `uptime`; the Mac adds `model`, `screen`
and `checked_at_epoch`, and a failed probe carries a redacted `detail`. `history.{vps,mac}` holds
parallel arrays (`t`, `cpu_pct`, `mem_pct`, and `status` on the Mac) bounded to `capacity` (240).

### The exporter CLI and exit codes

Flags: `--state-dir`, `--proc-dir`, `--mac-host`, `--name`, `--interval`, `--mac-interval`,
`--capacity`, `--no-mac`, `--force-mac`, `--print`, `--json`, `--version`. Exit `0` when this box
was sampled (an asleep Mac is still `0`) and `2` when the local sample itself failed.

### The state files

Under the state directory: `stats.json` (the served document, mode `0640`), and the private
`history.json`, `prev.json` and `mac.json` (mode `0600`). `prev.json` stores the previous aggregate
CPU tick pair so busy percentage is a delta between invocations rather than a `sleep()` inside a
run; `mac.json` stores the last good Mac reading so a failed probe can be reported without erasing
it.

### The HTTP surface

`GET /` serves the page with `Cache-Control: public, max-age=300`; `GET /api/stats` serves the
document with `Cache-Control: no-store`. Both locations repeat the full security header set
(`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a
strict `Content-Security-Policy`) because nginx inherits `add_header` only from a block that
defines none of its own.

### Environment variables

`VPS_STATS_STATE_DIR`, `VPS_STATS_PROC_DIR`, `VPS_STATS_MAC_HOST` and `VPS_STATS_NAME` are the
exporter's defaults for the matching flags. `HOME=/var/lib/vps-stats` is set by the unit so the
unprivileged user's private `ssh` config is found for the Mac probe.

## Boundaries and invariants

- No secret or token appears in the document; anything resembling one is redacted by
  `_safe_detail` before a failure `detail` is written.
- The history ring never grows past its capacity; all parallel series are trimmed in place and
  asserted parallel.
- A failed Mac probe never erases the last good reading, but it always switches the card to
  `dark`; a stale reading is only ever shown as last-known, never as current.
- One tick costs tens of milliseconds of CPU on a 1-vCPU box — the ssh round trip is waiting, not
  computing.
- Nothing ever binds a public interface; `tailscale serve` is the only thing that fronts nginx.

### Permission contract

`/var/lib/vps-stats` is installed setgid, mode `2750`, owned `vpsstats:www-data`, so files created
inside it inherit the `www-data` group. The exporter writes the served `stats.json` as mode `0640`
and the private state files (`history.json`, `prev.json`, `mac.json`) as mode `0600`. That pair is
what lets the nginx worker read the served document by group while nothing on the box is
world-readable. The exporter's own process group stays `vpsstats`: the directory supplies the file
group, not the process. A reader who tidies the mode or drops the setgid bit will get a `403` on
`/api/stats` and a page that cannot load its own data.
