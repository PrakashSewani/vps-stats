# Decisions

Append-only log of settled decisions. New entries get the next number, a date, and a sentence of
context. If a decision is reversed, add a new entry that supersedes the old one — never edit
history. The agent records decisions here **before** implementing them (see `AGENTS.md`, rule 2).

## D-001: Stack selection — pending

**Date:** —

**Decision:** Not made yet, on purpose. The stack is chosen when the tool's requirements are
known — see the `project-bootstrap` skill.

Replace this entry before scaffolding, and include:

- Language / runtime — with the exact versions resolved **live** at that moment (not from memory,
  not copied from anywhere).
- Distribution: where users install it from (registry, release binaries, container), and how CI
  produces that artifact.
- Test runner, lint/format, build tool, package manager.
- What was considered and rejected, and why (one line each).

The chosen stack is then described in `docs/architecture.md`, and its commands in
`docs/development.md`.

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
