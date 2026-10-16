# VPS Stats

One page, two cards, tailnet only. A Python-3-standard-library exporter samples this VPS every
15 s and a Mac every 60 s, writes a small JSON document, and a static page served on loopback
renders both hosts. The page is reachable only from devices logged into the same tailnet; nothing
is published to the public internet.

## What you get

- **The page** (`/`) — one dark HTML card per host with CPU, RAM, disk, swap, load and uptime,
  a 30-minute sparkline behind CPU and RAM, and a status pill. The page refreshes every 30 s and
  ages its own numbers once a second.
- **The endpoint** (`/api/stats`) — the same numbers as a small JSON document (`schema: 1`),
  served with `Cache-Control: no-store`, so `curl` and widgets can read it too.
- **Honest staleness** — a reading is `fresh`, then `amber`, then `stale` (VPS amber at 45 s /
  stale at 90 s; Mac amber at 90 s / stale at 180 s). A Mac that cannot be reached is shown as
  `asleep` (ssh exit 255) or `error` with a redacted one-line `detail`, never as numbers
  pretending to be current. The browser works out each host's age from the document's
  timestamps anchored to the server's clock at fetch time (the response's `Date` header), so a
  stalled exporter is red from the first paint and frozen or edge-cached JSON can never
  render as fresh.

## How it is served

```text
systemd timer (15 s) → oneshot vps-stats.service (User=vpsstats)
    → python3 /opt/vps-stats/exporter/stats.py --state-dir /var/lib/vps-stats
        → writes /var/lib/vps-stats/{stats.json,history.json,prev.json,mac.json} atomically
nginx, listening on 127.0.0.1:8080 ONLY
    /         → /opt/vps-stats/web/index.html
    /api/stats → /var/lib/vps-stats/stats.json   (Cache-Control: no-store)
tailscale serve --bg --http=80 http://127.0.0.1:8080
    → http://<this-box>.ts.net/   (reachable only from the tailnet)
```

## Install

On the VPS, from a checkout of this repository, as root:

```bash
sudo deploy/install.sh
```

Flags (all optional; the defaults are noted):

| Flag | Effect |
|---|---|
| `--dry-run` | Print every command, change nothing. Works without root. |
| `--no-mac-key` | Skip generating and authorising the ssh key for the Mac probe. |
| `--serve-port N` | Tailnet port for `tailscale serve` (default: `80`). |
| `--repo-root DIR` | Source tree to install from (default: this script's parent directory). |
| `--mac-alias NAME` | ssh alias the exporter uses for the Mac (default: `mac`). |
| `-h`, `--help` | Show help and exit. |

What it installs where:

- `/opt/vps-stats/exporter/stats.py` and `/opt/vps-stats/web/index.html` (mode `0644`).
- `/etc/systemd/system/vps-stats.service` and `vps-stats.timer`, plus the drop-in
  `/etc/systemd/system/vps-stats.service.d/name.conf` that sets `VPS_STATS_NAME` to the short
  tailnet name.
- `/etc/nginx/sites-available/vps-stats.conf` and its `sites-enabled` symlink; the stock
  `sites-enabled/default` is removed because it would shadow this site on `127.0.0.1:8080`.
- The state directory `/var/lib/vps-stats`, owned `vpsstats:www-data`, mode `2750`.
- Unless `--no-mac-key` is given, the probe key `/var/lib/vps-stats/.ssh/id_ed25519` and a
  private `ssh` config, then the public key is authorised on the Mac.
- Best effort: `/opt/vps-stats/DEPLOYED_SHA` with the installed git revision.

It prints the page URL — `http://<tailnet DNS name>/` — and `INSTALL OK` on success.

## Verify

On the same box, as root:

```bash
sudo deploy/smoke.sh
```

The smoke test runs one independent check per line and prints `PASS`, `FAIL` or `SKIP` for each:

- only the expected ports listen (`ss -ltn`);
- nginx listens on `127.0.0.1:8080` only, and the page answers there;
- `/api/stats` is JSON with the promised shape and is never cached;
- memory, disk, load and uptime in the document match the box;
- nothing answers on the public address (only when `--public-ip IP` is supplied);
- the timer is armed and the service is `Type=oneshot`;
- freshness advances, the document freezes when the timer stops, and the page ages its own
  numbers;
- nginx and the service stay inside their resource budgets;
- the served state is readable by the nginx worker and world-readable files are refused.

`--quick` skips the slow staleness test. The script exits `0` only when nothing failed; skipped
checks do not fail the run.

## Revert / uninstall

```bash
sudo tailscale serve reset
sudo systemctl disable --now vps-stats.timer vps-stats.service
sudo rm -f /etc/systemd/system/vps-stats.service /etc/systemd/system/vps-stats.timer
sudo rm -f /etc/systemd/system/vps-stats.service.d/name.conf
sudo rm -f /etc/nginx/sites-available/vps-stats.conf /etc/nginx/sites-enabled/vps-stats.conf
sudo rm -rf /var/lib/vps-stats
sudo rm -rf /opt/vps-stats
sudo systemctl reload nginx
```

Deleting `/var/lib/vps-stats` loses the 30-minute history ring and nothing else: there is no
database and no backing store, and the next tick starts a fresh history.

## Layout

```text
exporter/    stats.py — the sampler (Python 3 standard library only)
systemd/     vps-stats.service (oneshot) and vps-stats.timer (15 s)
deploy/      nginx.conf, install.sh, smoke.sh
tests/       test_exporter.py and its recorded fixtures/
web/         index.html — the whole page, one file, no build step
docs/        product.md, architecture.md, decisions.md, status.md, development.md
```

## Checks

A contributor runs, from the repository root:

```bash
python3 tests/test_exporter.py
bash -n deploy/install.sh && bash -n deploy/smoke.sh
```

The test runner is the standard-library `unittest` suite and exits `0` on success; the tests never
touch the network (the Mac probe is a recorded fixture). There is no build step, no linter, no
formatter, no Makefile and no CI workflow in this repository.

## No dependencies

The exporter is Python 3 standard library only — no `pip install` and no third-party import.
nginx, systemd and Tailscale are the platform it is deployed onto, not dependencies it pulls in.

## Reaching it

The page is only visible from a device logged into the tailnet. Plain `http://` over the tailnet
is already WireGuard-encrypted, so the URL works as printed. If you want an `https://` URL, flip
the single toggle in the Tailscale admin console under DNS → HTTPS Certificates; nothing in this
repository changes.
