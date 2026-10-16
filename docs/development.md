# Development

## Prerequisites

- A checkout of this repository.
- Python 3.9 or newer. The exporter uses `from __future__ import annotations` with the
  `typing` generics (`Dict`, `Tuple`, `Optional`) and `shutil.disk_usage`, and the installer
  refuses anything older.
- A tailnet (and a running `tailscaled`) only if you want to run the deployed path; the unit
  tests need nothing beyond the checkout.

## Setup

Clone the repository and start. There is nothing to install: the exporter is Python 3 standard
library only, so there is no virtualenv, no lockfile and no package manager step.

```bash
git clone https://github.com/PrakashSewani/vps-stats.git
cd vps-stats
```

## Commands

| Command | What it does |
|---|---|
| `python3 tests/test_exporter.py` | The check: runs the stdlib `unittest` suite and exits 0 on success. |
| `node tests/test_page.mjs` | The page's age maths (`agedSince`, `formatAge`, `hostState`) run against `web/index.html` itself, with no browser. Needs node; it is the only check that fails if the server-clock anchor goes away, so the smoke test runs it when node is on the box. |
| `bash -n deploy/install.sh && bash -n deploy/smoke.sh` | Syntax check for the two shell scripts. |
| `python3 exporter/stats.py --state-dir /tmp/vps-stats-test --no-mac --print --json` | Local dry run against a throwaway state directory; prints the whole document. |
| `python3 exporter/stats.py --version` | Prints `stats.py <version>` and exits 0. |
| `sudo deploy/install.sh --dry-run` | Preview the install on the target box, changing nothing; works without root. |

The installer and the smoke test are run as root **on the target box**, not on a laptop — they
install systemd units, an nginx site and a state directory. The unit tests never touch the
network: the Mac probe is exercised against the recorded capture in `tests/fixtures/`.

## Environment

| Variable | Used by | Default |
|---|---|---|
| `VPS_STATS_STATE_DIR` | exporter `--state-dir` | `/var/lib/vps-stats` |
| `VPS_STATS_PROC_DIR` | exporter `--proc-dir` | `/proc` |
| `VPS_STATS_MAC_HOST` | exporter `--mac-host` | `mac` |
| `VPS_STATS_NAME` | exporter card name | the short hostname |
| `HOME` | ssh config lookup for the Mac probe | set to `/var/lib/vps-stats` by the unit |

A missing variable falls back to the default in the table; the matching command-line flag wins
over the variable.

## Branches and pull requests

Generated projects use `dev` as the GitHub default branch and integration branch. Bootstrap must
create and push `dev`, then set it as the repository default; if repository permissions do not
allow the agent to change that setting, it must tell the user how to set it in GitHub. Configure
branch protection for `dev` and `main` where available.

Feature branches start from `dev`. AI agents must not commit directly to `dev` or `main`; they
open a PR for their work targeting `dev`, with a clear title and description, checks performed,
and relevant documentation or changelog updates. Release promotion is a PR from `dev` to `main`
and must declare the version bump (`patch`, `minor`, or `major`) and update the version source of
truth and changelog.

## Releases and deploys

This repository publishes no artifact. A merge to `main` changes nothing by itself: there is no
package to push, no binary to upload and no release workflow to run. Deployment is manual and
happens on the box — check out the merged revision and run `sudo deploy/install.sh` there, then
verify with `sudo deploy/smoke.sh`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| A card stuck at `STALE — exporter silent` | `systemctl status vps-stats.timer` (armed?) then `systemctl status vps-stats.service` and `journalctl -u vps-stats.service -n 30`. |
| The page is unreachable | Check nginx listens on `127.0.0.1:8080` (`ss -ltn`), then `tailscale serve status`. |
| The Mac card is dark while the laptop sleeps | Expected — a Mac that cannot be reached is reported `asleep`, not stale numbers. |
| `/api/stats` returns `403` | The nginx worker cannot read the state file: check the state directory is setgid `2750` owned `vpsstats:www-data` and `stats.json` is `0640`. |
| `tailscale serve` failed during install | Enable Serve for the tailnet in the Tailscale admin console, then re-run `tailscale serve --bg --http=80 http://127.0.0.1:8080`. |
