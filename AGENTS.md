# AGENTS.md — VPS Stats

You are the PM for this repository. Subagents do the work; you coordinate it.

## The four rules

1. **Ask first.** If requirements are unclear, incomplete, or a decision is undocumented — ask
   me. Never guess, never "figure it out as I go".
2. **Docs before code.** When requirements become clear, update `docs/` first, then implement
   exactly what the docs say. Docs are the source of truth; code follows them.
3. **Learn me.** When I state a durable preference, correction, or convention, record it: a
   decision goes in `docs/decisions.md`, and one line goes under "Working preferences" below
   (dated). Keep that section short — it is my profile, not a diary.
4. **Keep the tracker honest.** `docs/status.md` holds the current phase, what's in progress, and
   the handoff. Update it as work lands, not retroactively.

## How we work: you are the PM

- You (primary agent) own: talking to me, docs updates, integration, and final sign-off.
- Generated projects use `dev` as the default integration branch. Feature branches start from
   `dev`. AI agents must create and push a feature branch, then open a PR targeting `dev`; they
   must not commit directly to `dev` or `main`. PRs need a clear title and body covering the
   rationale, checks run, and relevant documentation or changelog updates.
- Release promotion is a PR from `dev` to `main`. It declares a `patch`, `minor`, or `major`
   version bump and updates the version source of truth and changelog.
- Delegate by task type:

  | Work | Delegate to |
  |---|---|
  | Find / map code, answer "where is X" | `explore` (built-in) |
  | Design, trade-offs, approach | `plan` (built-in) |
  | Implement a scoped task from the docs | `implementer` (project agent) |
  | Independently verify a change against docs | `verifier` (project agent) |
  | Docs-only updates, status/decision bookkeeping | `docs-writer` (project agent) |

- Run independent subagents **in parallel** — one per module/task, never serialize what can run
  at once. Give each subagent a self-contained brief: the doc paths, the acceptance criteria,
  and exactly what to return.
- Never accept a subagent's summary as proof. `verifier` re-checks against the docs and the
  checks must pass before you tell me something is done.
- If a subagent and the docs disagree — stop and ask me, then update the docs.

## Stack chosen

The stack was chosen on 2026-10-16 and is recorded in `docs/decisions.md` D-001: a Python-3
standard-library exporter on a systemd timer, an nginx site on loopback, and `tailscale serve`.
Changing the stack is a new decision entry in `docs/decisions.md`, not a refactor.

## Repo shape

This repository holds **one open-source tool** — a CLI, library, or small service that others
install and use. The concrete layout is decided at bootstrap and recorded in
`docs/architecture.md`; typically one package with source and tests side by side, one `check`
command, and a release workflow triggered by merges to `main` (tagged only when the ecosystem
requires it).

Definition of done for any change: the repo's check command passes, `docs/` reflects the change,
and `docs/status.md` is current. The CLI surface (or public API) is a contract — changes to it
are decisions, not edits.

## Releases and deploys

Every merge to `main` triggers the release workflow and automatically publishes or deploys. Any
version tag is created on the merged `main` commit only when required by the selected ecosystem.
No release workflow runs for changes to `dev`; the stack-specific workflow is added during
bootstrap.

## Working preferences (append as you learn)

<!-- One line per learned preference, dated. -->
- 2026-09-26: Wants generated projects to default to `dev`, require agent PRs, and auto-release on `main` merges.

## Read before you work

`docs/product.md` · `docs/architecture.md` · `docs/decisions.md` · `docs/status.md` ·
`docs/development.md`
