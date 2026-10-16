# Decisions

Append-only log of settled decisions. New entries get the next number, a date, and a sentence of
context. If a decision is reversed, add a new entry that supersedes the old one — never edit
history. The agent records decisions here **before** implementing them (see `AGENTS.md`, rule 2).

## D-001: Stack — Python-stdlib exporter, systemd timer, nginx on loopback, tailscale serve

**Date:** 2026-10-16

**Decision:**

- **Language / runtime:** Python 3, standard library only (the installer requires 3.9 or newer).
  There are no third-party packages, so there are no package versions to resolve or pin. The
  exporter is a plain script run on a schedule, not a service.
- **Distribution:** none in the registry sense. The tool is deployed from a checkout with
  `deploy/install.sh` on the target VPS, which writes the exporter and the page into
  `/opt/vps-stats` and installs a systemd timer and an nginx site. There is no artifact, no
  container and no package feed.
- **Scheduling and serving:** a `Type=oneshot` systemd unit on a 15 s timer, a static HTML page,
  and an nginx site bound to `127.0.0.1:8080`, published to the tailnet with `tailscale serve`.
- **Test runner:** the standard-library `unittest` runner, `python3 tests/test_exporter.py`. No
  linter, formatter or build tool — the code is the artifact and the page has no build step.

**Considered and rejected:**

- Glances REST — a resident process of about 80 MB plus an unauthenticated API to manage.
- node_exporter + VictoriaMetrics — no human UI, and the resident set alone blows the memory
  budget.
- Beszel — a hub, an agent and its own database to render one number.
- Netdata — too heavy for a 1 vCPU box.
- A resident daemon of any kind — a timer plus a static file does the same work and holds no port.
- Sleeping inside the sample run — it would hold a process open for the interval just to measure
  CPU; the delta is persisted in `prev.json` instead.
- A frontend on a Cloudflare Worker or Pages — page and protected JSON would sit on different
  origins, needing CORS and a second session to save about 100 ms.
- A test framework with third-party dependencies — the stdlib `unittest` runner is enough.

## D-002: Development and release branches

**Date:** 2026-09-26

**Decision:** Generated projects use `dev` as the default integration branch. Feature work is
submitted by PR into `dev`; release promotion is a PR from `dev` to `main` that declares the
version bump. Every merge to `main` runs the release workflow and automatically publishes or
deploys. The workflow creates a version tag on the merged `main` commit only when the chosen
ecosystem requires one. No release workflow runs for `dev` changes. `dev` may equal `main`
immediately after a release, but remains the default destination for all subsequent work.

AI agents do not commit directly to `dev` or `main`: they create a feature branch and open a PR
targeting `dev`, with an appropriate title, rationale, checks, and documentation updates. Branch
protection and the generated repository's default-branch setting are configured during bootstrap.

## D-003: Tailnet-only serving — no Cloudflare, no public hostname

**Date:** 2026-10-16

**Decision:** The page and the JSON endpoint are published only on the tailnet, by
`tailscale serve --bg --http=80 http://127.0.0.1:8080`. The earlier plan served the page publicly
on `:443` through a cloudflared tunnel, fronted by a Cloudflare Access policy and a DNS record.
Both hosts were already on the tailnet and `tailscaled` already ran on the box, so `tailscale
serve` gives the same reachability with no token, no tunnel daemon, no DNS record and no
bypassable origin. The bypass that motivated Access cannot exist when nothing is bound to the
public interface: `ss -ltn` shows only `:22`, tailscaled and `127.0.0.1:8080`.

This supersedes the serving section of the earlier plan. D-002 (branches) is unaffected.
