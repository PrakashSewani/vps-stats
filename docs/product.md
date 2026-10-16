# Product

## What it is

VPS Stats is a tailnet-only statistics page plus the JSON endpoint behind it. A small exporter
samples this VPS every 15 s and an optional Mac every 60 s, writes `/var/lib/vps-stats/stats.json`
atomically, and nginx serves one static page and that document on loopback; `tailscale serve`
publishes them to the tailnet. There are two machines and no public surface: no Cloudflare, no
public hostname, no token, no DNS record.

## Who it's for

The owner of the box it is installed on — and anyone they have admitted to the tailnet. It is
installed from a checkout with `sudo deploy/install.sh`, not from a registry: there is no package,
no release artifact and no container. The audience already runs a VPS with systemd, nginx and
Tailscale, and wants to see this box and their laptop at a glance without a hosted monitoring
service.

## The problem it solves

Checking a small VPS usually means an ssh session and a handful of commands, repeated whenever
curiosity strikes, with no history and no view of the laptop. A full monitoring stack solves that
by installing a resident daemon, a database and a UI to read one number — far more memory and
surface than a 1-vCPU box needs. Between those two extremes sits this: a timer that costs tens of
milliseconds per tick, one static file, and a page that is honest when a collector stops.

## Interface

### The page

`GET /` returns `web/index.html`: one card for the VPS and one for the Mac, each showing CPU
(with a 30-minute sparkline), RAM (with a sparkline and a bar), disk, swap, load, uptime and —
on the Mac — the model and screen state. The page re-fetches `/api/stats` every 30 s and
re-renders each host's age once a second from the document's `generated_at_epoch`, anchored to
the server's clock from the response's `Date` header, so a stalled exporter reads as stale on
the first paint.

### `GET /api/stats`

Returns the served JSON document with `Cache-Control: no-store`. The document has
`schema: 1` and these keys:

- Top level: `schema`, `version`, `generated_at`, `generated_at_epoch`, `interval_s`, `hosts`,
  `history`.
- `hosts.vps` and `hosts.mac`: `kind`, `name`, `status`, `generated_at`, `generated_at_epoch`,
  `age_s`, `field`, and the blocks `cpu` (`cores`, `busy_pct`), `memory` (`total_gb`, `used_gb`,
  `used_pct`, and `available_gb` on the VPS or `free_gb`/`cached_gb` on the Mac), `swap`, `disk`
  (`mount`, `total_gb`, `used_gb`, `used_pct`, `free_gb`), `load` (`1m`, `5m`, `15m`), `uptime_s`
  and `uptime`.
- Mac-only extras: `model`, `screen`, `checked_at_epoch`; a failed Mac probe also carries a
  redacted one-line `detail`.
- `history.vps` and `history.mac`: parallel arrays `t`, `cpu_pct`, `mem_pct`, plus `status` on the
  Mac, bounded to a 240-sample ring (30 min at 15 s). `interval_s`, `mac_interval_s` and
  `capacity` describe it.

### Exporter CLI

`python3 exporter/stats.py` with:

| Flag | Default | Meaning |
|---|---|---|
| `--state-dir DIR` | `$VPS_STATS_STATE_DIR`, else `/var/lib/vps-stats` | Where the four state files live. |
| `--proc-dir DIR` | `$VPS_STATS_PROC_DIR`, else `/proc` | Where the local samples are read from. |
| `--mac-host HOST` | `$VPS_STATS_MAC_HOST`, else `mac` | ssh alias for the Mac probe. |
| `--name NAME` | `$VPS_STATS_NAME`, else the short hostname | Card name for this box. |
| `--interval S` | `15` | VPS sample cadence recorded in the document. |
| `--mac-interval S` | `60` | Minimum seconds between Mac probes. |
| `--capacity N` | `240` | History ring size. |
| `--no-mac` | off | Skip the Mac probe entirely. |
| `--force-mac` | off | Probe the Mac even if the last probe is recent. |
| `--print` | off | Print a one-line summary (or the document with `--json`). |
| `--json` | off | With `--print`, print the whole document as JSON. |
| `--version` | off | Print `stats.py <version>` and exit 0. |

### Exit codes

- `0` — this box was sampled. An asleep or unreachable Mac is still `0`.
- `2` — the local sample itself failed, or the arguments were invalid.

## Non-goals

- No alerting, notifications or paging — the page reports, it does not wake anyone.
- No long-term history or database — the ring is 240 samples and stops there.
- No per-process top, no disk-IO or network-throughput metrics.
- No third host: the VPS and the Mac, and that is the list.
- No Docker, no container, no container orchestration.
- No public hostname, no Cloudflare, no tunnel daemon, no DNS record.
- No VPS hardening or firewall work — this is a stats page, not a provisioning tool.
- No HTTPS until the owner flips the Tailscale HTTPS Certificates toggle.
- No backend framework; the exporter is a script and the page is one static file.

## Success looks like

Open the tailnet URL from the phone or the Mac, read both machines in about a second, and trust
what is shown: a dead collector can never look green. The first release is done when a clean
`deploy/install.sh` on the box is followed by a `deploy/smoke.sh` run that exits `0`.
