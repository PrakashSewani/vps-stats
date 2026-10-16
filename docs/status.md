# Status

Persistent project tracker and handoff. The agent updates this as work lands — see `AGENTS.md`,
rule 4. Keep exactly one phase `in progress`.

## Phase tracker

| Phase | Scope | Status |
|---|---|---|
| 0 | Requirements + stack selection: fill `docs/product.md`, choose the stack, record D-001 | done |
| 1 | Scaffold: structure, checks, units, deploy scripts, release path — recorded in `docs/architecture.md` / `development.md` | done |
| 2 | Core behavior: exporter tick, bounded ring, Mac probe, page, staleness — end to end, with tests | done |
| 3 | Polish: README, error messages, docs — the parts users judge first | in progress |
| 4 | Release: install and smoke-verify on the box; deployment checked from a clean environment | not started |

## Current handoff

- **Phase:** 3 — polish; documentation (README and `docs/`) is the work in progress and everything
  before it has landed.
- **Done this session:** rewrote `README.md`; filled `docs/product.md`, `docs/architecture.md` and
  `docs/development.md`; recorded D-001 (stack) and D-003 (tailnet-only serving) and updated
  `docs/status.md`; corrected the template-rename wording in the skills and `CHANGELOG.md`.
- **Verified:** `python3 tests/test_exporter.py` (standard-library `unittest` suite, exit 0) and
  `bash -n deploy/install.sh && bash -n deploy/smoke.sh` (script syntax). The deploy path itself
  has not been run on a box: no install and no smoke run has happened.
- **Blocked by:** nothing.
- **Next action:** install on the box with `sudo deploy/install.sh`, then run
  `sudo deploy/smoke.sh` and confirm it exits 0.

---

### Handoff note format (replace the section above when you stop mid-phase)

- **Phase:** <number and name>
- **Done this session:** <what actually landed>
- **Verified:** <what was run, what was observed — not "it works">
- **Blocked by:** <nothing, or the exact question waiting on the human>
- **Next action:** <the single first thing to do next>
