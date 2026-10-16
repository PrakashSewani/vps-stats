# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository scaffold from the `template-open-source-tool` template (docs-first skeleton; stack
  chosen at bootstrap).
- Standard-library Python exporter that samples the VPS and probes the Mac, with a bounded
  240-sample history ring and honest stale/asleep states.
- systemd units: a oneshot `vps-stats.service` and a 15-second `vps-stats.timer`.
- Tailnet-only nginx site bound to `127.0.0.1:8080`, published with `tailscale serve`.
- The static page that renders both hosts and ages its own numbers.
- Install and smoke-test scripts for deploying and verifying the box.
- Test suite (`python3 tests/test_exporter.py`) covering the Mac probe parser, the bounded
  ring, the freshness bands, secret redaction and the served-file mode.

### Fixed

- The Mac card's `screen` field now reads `CGSSessionScreenIsLocked` instead of the `/dev/console`
  owner, which macOS keeps on the logged-in user while the screen is locked — a locked Mac was
  reported `unlocked` (review round 1, major).
- A CPU tick whose window is too short to be a measurement (systemd can fire two ticks back to
  back after a slow one) now reports the lifetime average instead of the sampler's own start-up;
  `prev.json` records when the sample was taken and the timer re-arms from the end of the tick.
- The banner and the card floors age to minutes, so one document cannot show two different ages;
  `node tests/test_page.mjs` pins the page's age maths, which the smoke test now runs when node
  is available.
